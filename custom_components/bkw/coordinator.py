"""Import BKW consumption into Home Assistant's long-term statistics."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import EnergyConverter

from .api import BkwApi, BkwApiError, BkwAuthError
from .const import CONF_FIXED_FEE, CONF_PRICE, CONF_PRICE_ENTITY, CONF_REFRESH_TOKEN, DOMAIN

_LOGGER = logging.getLogger(__name__)

CHUNK = timedelta(days=30)
HOUR = timedelta(hours=1)
# BKW publishes a day's readings some time the next day: poll hourly until
# yesterday is complete, then fall back to a slow interval.
CAUGHT_UP_INTERVAL = timedelta(hours=6)
WAITING_INTERVAL = timedelta(hours=1)


class BkwCoordinator(DataUpdateCoordinator[None]):
    """Fetches the readings BKW has published since the last imported hour."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: BkwApi) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=WAITING_INTERVAL,
        )
        self.api = api

    async def _async_update_data(self) -> None:
        try:
            await self.api.async_refresh()
            # Persist at once: the previous refresh token is no longer valid.
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={**self.config_entry.data, CONF_REFRESH_TOKEN: self.api.refresh_token},
            )
            caught_up = [await self._import(point) for point in await self.api.async_metering_points()]
            self.update_interval = CAUGHT_UP_INTERVAL if all(caught_up) else WAITING_INTERVAL
        except BkwAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except BkwApiError as err:
            raise UpdateFailed(str(err)) from err

    def _price(self) -> float | None:
        """Return the configured price per kWh, or None when costs are off or unknown."""
        options = self.config_entry.options
        if entity_id := options.get(CONF_PRICE_ENTITY):
            state = self.hass.states.get(entity_id)
            try:
                return float(state.state) if state else None
            except ValueError:
                return None
        price = options.get(CONF_PRICE)
        return float(price) if price is not None else None

    async def _import(self, point: dict[str, Any]) -> bool:
        """Import new hours for one metering point; return True once yesterday is complete."""
        code = point["meteringPointCode"]
        first = dt_util.as_utc(datetime.fromisoformat(point["dataAvailableFrom"]))
        consumption = await _Series.load(
            self.hass,
            first,
            StatisticMetaData(
                mean_type=StatisticMeanType.NONE,
                has_sum=True,
                name=f"BKW {code[-6:]} consumption",
                source=DOMAIN,
                statistic_id=f"{DOMAIN}:{code.lower()}_consumption",
                unit_class=EnergyConverter.UNIT_CLASS,
                unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            ),
        )
        series = [consumption]
        # Hours are priced when they are imported, normally the day after:
        # Home Assistant keeps no history of what a price entity said earlier.
        price = self._price()
        # Base fees are billed per day; spread them evenly over the hours.
        fee_per_hour = float(self.config_entry.options.get(CONF_FIXED_FEE) or 0) / 365 / 24
        cost = None
        if price is not None:
            cost = await _Series.load(
                self.hass,
                first,
                StatisticMetaData(
                    mean_type=StatisticMeanType.NONE,
                    has_sum=True,
                    name=f"BKW {code[-6:]} cost",
                    source=DOMAIN,
                    statistic_id=f"{DOMAIN}:{code.lower()}_cost",
                    unit_class=None,
                    unit_of_measurement=self.hass.config.currency,
                ),
            )
            series.append(cost)

        start = min(s.next_hour for s in series)
        end = dt_util.as_utc(dt_util.start_of_local_day())
        while start < end:
            stop = min(start + CHUNK, end)
            hours: dict[datetime, list[float]] = defaultdict(list)
            for moment, kwh in await self.api.async_consumption(code, start, stop):
                hours[dt_util.as_utc(moment).replace(minute=0, second=0, microsecond=0)].append(kwh)
            # Only complete hours: the next run starts after the last imported
            # hour, so readings still missing at the end are picked up then.
            for hour in sorted(hours):
                if len(hours[hour]) == 4:
                    kwh = sum(hours[hour])
                    consumption.add(hour, kwh)
                    if cost is not None:
                        cost.add(hour, kwh * price + fee_per_hour)
            start = stop

        for s in series:
            s.save(self.hass)
        return consumption.next_hour >= end


class _Series:
    """One external statistic and the hour its import continues from."""

    def __init__(self, metadata: StatisticMetaData, next_hour: datetime, total: float) -> None:
        self.metadata = metadata
        self.next_hour = next_hour
        self.total = total
        self.rows: list[StatisticData] = []

    @classmethod
    async def load(
        cls, hass: HomeAssistant, first: datetime, metadata: StatisticMetaData
    ) -> _Series:
        statistic_id = metadata["statistic_id"]
        last = await get_instance(hass).async_add_executor_job(
            get_last_statistics, hass, 1, statistic_id, True, {"sum"}
        )
        if not last:
            return cls(metadata, first, 0.0)
        row = last[statistic_id][0]
        return cls(metadata, dt_util.utc_from_timestamp(row["start"]) + HOUR, float(row["sum"] or 0))

    def add(self, hour: datetime, value: float) -> None:
        if hour >= self.next_hour:
            self.total += value
            self.rows.append(StatisticData(start=hour, state=value, sum=self.total))
            self.next_hour = hour + HOUR

    def save(self, hass: HomeAssistant) -> None:
        if self.rows:
            _LOGGER.debug("Importing %d hours for %s", len(self.rows), self.metadata["statistic_id"])
            async_add_external_statistics(hass, self.metadata, self.rows)
