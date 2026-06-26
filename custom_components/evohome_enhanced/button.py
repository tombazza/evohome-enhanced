"""Button platform for evohome_enhanced (reset overrides)."""

from __future__ import annotations

from typing import TYPE_CHECKING, override

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import EvoDataUpdateCoordinator
from .entity import EvoDevice, evo_device_info, evo_uid, is_valid_zone

if TYPE_CHECKING:
    from . import EvoConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EvoConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up reset buttons for the system, zones and DHW."""
    coordinator = entry.runtime_data.coordinator
    tcs = entry.runtime_data.tcs

    entities: list[EvoResetButton] = [EvoResetButton(coordinator, tcs)]
    entities += [EvoResetButton(coordinator, z) for z in tcs.zones if is_valid_zone(z)]
    if tcs.hotwater:
        entities.append(EvoResetButton(coordinator, tcs.hotwater))

    async_add_entities(entities)


class EvoResetButton(CoordinatorEntity[EvoDataUpdateCoordinator], ButtonEntity):
    """A button that resets an evohome device to its scheduled operating mode."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True
    _attr_translation_key = "reset"

    def __init__(
        self, coordinator: EvoDataUpdateCoordinator, device: EvoDevice
    ) -> None:
        """Initialise a reset button."""
        super().__init__(coordinator, context=device.id)
        self._evo_device = device
        self._attr_unique_id = f"{evo_uid(device)}_reset"
        self._attr_device_info = evo_device_info(coordinator, device)

    @override
    async def async_press(self) -> None:
        """Reset the device to its base operating mode."""
        await self.coordinator.call_client_api(self._evo_device.reset())
