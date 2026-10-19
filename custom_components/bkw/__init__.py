"""The BKW Smart Meter integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import BkwApi
from .const import CONF_REFRESH_TOKEN
from .coordinator import BkwCoordinator

type BkwConfigEntry = ConfigEntry[BkwCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: BkwConfigEntry) -> bool:
    """Start importing statistics for one myBKW account."""
    api = BkwApi(async_get_clientsession(hass), entry.data[CONF_REFRESH_TOKEN])
    coordinator = BkwCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()
    # The coordinator only polls while something listens, and this integration
    # has no entities to do that.
    entry.async_on_unload(coordinator.async_add_listener(lambda: None))
    entry.runtime_data = coordinator
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BkwConfigEntry) -> bool:
    """Stop importing. The statistics already imported stay in the recorder."""
    return True
