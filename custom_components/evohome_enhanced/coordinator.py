"""DataUpdateCoordinator for the evohome_enhanced integration."""

from __future__ import annotations

import logging
from collections.abc import Awaitable
from datetime import timedelta
from http import HTTPStatus
from typing import Any

import evohomeasync as ec1
import evohomeasync2 as ec2
from evohomeasync2.typedefs import EvoLocStatusT
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed


class EvoDataUpdateCoordinator(DataUpdateCoordinator[EvoLocStatusT]):
    """Single coordinator that fans out to every evohome platform.

    All entities are read-only views over ``self.data`` (v2 location status) and
    ``self.temps`` (optional v1 high-precision temperatures), so adding sensors
    costs no extra API calls.
    """

    loc: ec2.Location
    tcs: ec2.ControlSystem

    def __init__(
        self,
        hass: HomeAssistant,
        logger: logging.Logger,
        client_v2: ec2.EvohomeClient,
        *,
        name: str,
        update_interval: timedelta,
        location_idx: int,
        client_v1: ec1.EvohomeClient | None = None,
        config_entry: ConfigEntry | None = None,
    ) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            logger,
            config_entry=config_entry,
            name=name,
            update_interval=update_interval,
        )
        self.client = client_v2
        self.client_v1 = client_v1
        self.loc_idx = location_idx
        self.temps: dict[str, float | None] = {}
        self._first_refresh_done = False  # fetch schedules only after first refresh

    async def _async_setup(self) -> None:
        """Fetch user/location configuration (not status) once, at startup."""
        try:
            await self.client.update(dont_update_status=True)
        except ec2.EvohomeError as err:
            raise UpdateFailed(err) from err

        try:
            self.loc = self.client.locations[self.loc_idx]
        except IndexError as err:
            raise UpdateFailed(
                f"'location_idx' = {self.loc_idx} is out of range "
                f"(0-{len(self.client.locations) - 1})"
            ) from err

        self.tcs = self.loc.gateways[0].systems[0]

    async def call_client_api(
        self,
        client_api: Awaitable[dict[str, Any] | None],
        request_refresh: bool = True,
    ) -> dict[str, Any] | None:
        """Invoke a client API call, then (optionally) refresh coordinator state."""
        try:
            result = await client_api
        except ec2.InvalidSystemModeError:
            raise
        except ec2.ApiRequestFailedError as err:
            self.logger.error(err)
            return None

        if request_refresh:  # let the system quiesce, then re-read state
            await self.async_request_refresh()
        return result

    async def _update_v1_api_temps(self) -> None:
        """Refresh high-precision temperatures; never fatal to the update cycle."""
        assert self.client_v1 is not None  # mypy

        try:
            await self.client_v1.update()
        except ec1.BadUserCredentialsError as err:
            self.logger.warning(
                "Disabling high-precision temperatures until restart: %r", err
            )
            self.client_v1 = None
        except ec1.EvohomeError as err:
            self.logger.warning(
                "Ignoring high-precision temperatures this cycle: %r", err
            )
            self.temps = {}
        else:
            self.temps = await self.client_v1.location_by_id[
                self.loc.id
            ].get_temperatures(dont_update_status=True)

    async def _update_v2_api_state(self) -> None:
        """Refresh modes, temperatures and setpoints for the whole location."""
        try:
            await self.loc.update()
        except ec2.ApiRequestFailedError as err:
            if err.status != HTTPStatus.TOO_MANY_REQUESTS:
                raise UpdateFailed(err) from err
            raise UpdateFailed(
                "The vendor's API rate limit was exceeded; increase the scan interval"
            ) from err
        except ec2.EvohomeError as err:
            raise UpdateFailed(err) from err

    async def _update_v2_schedules(self) -> None:
        """Refresh zone/DHW schedules (used to derive setpoint switchpoints)."""
        for zone in self.tcs.zones:
            try:
                await zone.get_schedule()
            except ec2.InvalidScheduleError as err:
                self.logger.warning(
                    "Zone '%s' has an invalid/missing schedule: %r", zone.name, err
                )

        if dhw := self.tcs.hotwater:
            try:
                await dhw.get_schedule()
            except ec2.InvalidScheduleError as err:
                self.logger.warning("DHW has an invalid/missing schedule: %r", err)

    async def _async_update_data(self) -> EvoLocStatusT:
        """Fetch the latest state of the entire location."""
        await self._update_v2_api_state()  # may raise UpdateFailed
        if self.client_v1:
            await self._update_v1_api_temps()  # never raises UpdateFailed

        # Skip schedules on the very first refresh to speed up HA startup.
        if self._first_refresh_done:
            await self._update_v2_schedules()
        else:
            self._first_refresh_done = True

        return self.loc.status
