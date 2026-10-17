"""Client for the myBKW energy monitoring API."""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
import hashlib
import secrets
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import aiohttp

from .const import (
    API_URL,
    AUTH_URL,
    CLIENT_ID,
    DATA_TYPE_CONSUMPTION,
    REDIRECT_URI,
    TOKEN_URL,
)


class BkwAuthError(Exception):
    """The refresh token or authorization code was refused."""


class BkwApiError(Exception):
    """The API could not be reached or answered unexpectedly."""


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class PkceLogin:
    """One browser login: the URL to open and the verifier to redeem its code."""

    def __init__(self) -> None:
        self.verifier = secrets.token_urlsafe(64)
        self.state = secrets.token_urlsafe(16)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        self.url = AUTH_URL + "?" + urlencode(
            {
                "client_id": CLIENT_ID,
                "redirect_uri": REDIRECT_URI,
                "response_type": "code",
                "response_mode": "fragment",
                "scope": "openid offline_access",
                "state": self.state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )

    def code_from(self, redirected_url: str) -> str:
        """Extract the authorization code from the address the browser landed on."""
        parts = urlsplit(redirected_url.strip())
        params = parse_qs(parts.fragment or parts.query)
        if params.get("state", [None])[0] != self.state or "code" not in params:
            raise BkwAuthError("address does not hold a code from this login")
        return params["code"][0]


class BkwApi:
    """Access to one myBKW account, kept alive by an offline refresh token."""

    def __init__(self, session: aiohttp.ClientSession, refresh_token: str | None = None) -> None:
        self._session = session
        self.refresh_token = refresh_token
        self._access_token: str | None = None

    async def async_login(self, login: PkceLogin, redirected_url: str) -> None:
        """Redeem the code from a browser login for an offline refresh token."""
        await self._token(
            {
                "grant_type": "authorization_code",
                "code": login.code_from(redirected_url),
                "redirect_uri": REDIRECT_URI,
                "code_verifier": login.verifier,
            }
        )

    async def async_refresh(self) -> None:
        """Get a new access token. Keycloak rotates the refresh token on every call."""
        await self._token({"grant_type": "refresh_token", "refresh_token": self.refresh_token})

    async def _token(self, form: dict[str, str | None]) -> None:
        try:
            async with self._session.post(TOKEN_URL, data={"client_id": CLIENT_ID, **form}) as resp:
                body = await resp.json(content_type=None)
                status = resp.status
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise BkwApiError(f"token endpoint: {err}") from err
        if status in (400, 401):
            raise BkwAuthError(body.get("error_description") or body.get("error") or str(status))
        if status != 200:
            raise BkwApiError(f"token endpoint returned {status}")
        self._access_token = body["access_token"]
        self.refresh_token = body["refresh_token"]

    async def _get(self, path: str, params: dict[str, str] | None = None) -> Any:
        try:
            async with self._session.get(
                f"{API_URL}/{path}",
                params=params,
                headers={"Authorization": f"Bearer {self._access_token}"},
            ) as resp:
                if resp.status == 401:
                    raise BkwAuthError("access token refused")
                if resp.status != 200:
                    raise BkwApiError(f"{path} returned {resp.status}")
                return await resp.json()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise BkwApiError(f"{path}: {err}") from err

    async def async_metering_points(self) -> list[dict[str, Any]]:
        """Return the account's metering points."""
        return await self._get("meteringpoint")

    async def async_consumption(
        self, metering_point: str, start: datetime, end: datetime
    ) -> list[tuple[datetime, float]]:
        """Return 15-minute consumption in kWh for the intervals starting in [start, end)."""
        rows = await self._get(
            "metering-data",
            {
                "resolution": "PT15M",
                "measurementValidityStart": _iso(start),
                # The web app asks for an inclusive stop, one millisecond before end.
                "measurementValidityStop": _iso(end - timedelta(milliseconds=1)),
                "dataType": DATA_TYPE_CONSUMPTION,
                "meteringPointCode": metering_point,
            },
        )
        return [(datetime.fromisoformat(r["t"]), float(r["v"])) for r in rows if r.get("v") is not None]
