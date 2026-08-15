"""Native lock platform for Aqara U200."""

from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import AqaraU200ConfigEntry
from .const import DOMAIN
from .coordinator import AqaraU200Coordinator
from .exceptions import AqaraU200Error


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AqaraU200ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Aqara U200 lock entity."""
    del hass
    async_add_entities([AqaraU200Lock(entry, entry.runtime_data.coordinator)])


class AqaraU200Lock(CoordinatorEntity[AqaraU200Coordinator], LockEntity):
    """Represent one Aqara U200 as a native Home Assistant lock."""

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(
        self,
        entry: AqaraU200ConfigEntry,
        coordinator: AqaraU200Coordinator,
    ) -> None:
        """Initialize the lock entity."""
        super().__init__(coordinator)
        runtime = entry.runtime_data
        self._attr_unique_id = f"{runtime.address}_lock"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, runtime.address)},
            manufacturer="Aqara",
            model="U200",
            name=entry.title,
        )

    @property
    def available(self) -> bool:
        """Expose control only when both BLE and the real backend are ready."""
        data = self.coordinator.data
        return (
            super().available
            and data is not None
            and data.reachable
            and data.control_enabled
        )

    @property
    def is_locked(self) -> bool | None:
        """Return lock state.

        Protocol-backed state reads are deliberately deferred; do not invent an
        optimistic state before the U200 state-read path is confirmed.
        """
        return None

    async def async_lock(self, **kwargs: Any) -> None:
        """Lock the U200 through the runtime boundary."""
        del kwargs
        try:
            await self.coordinator.async_lock()
        except AqaraU200Error as err:
            raise HomeAssistantError(str(err)) from err

    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock the U200 through the runtime boundary."""
        del kwargs
        try:
            await self.coordinator.async_unlock()
        except AqaraU200Error as err:
            raise HomeAssistantError(str(err)) from err
