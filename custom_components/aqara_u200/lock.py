"""Native lock platform for Aqara U200."""

from typing import Any

import voluptuous as vol
from homeassistant.components.lock import LockEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import AqaraU200ConfigEntry
from .const import DOMAIN
from .coordinator import AqaraU200Coordinator
from .exceptions import AqaraU200Error

SERVICE_ADD_VISITOR_PASSWORD = "add_visitor_password"
SERVICE_DELETE_USER = "delete_user"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AqaraU200ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Aqara U200 lock entity and its services."""
    del hass
    async_add_entities([AqaraU200Lock(entry, entry.runtime_data.coordinator)])

    # Entity service: users target the lock and enrol a visitor PIN over BLE.
    # In real HA this runs inside the platform-setup context; a unit test may call
    # this function directly (no current platform) — skip registration there.
    try:
        platform = entity_platform.async_get_current_platform()
    except RuntimeError:
        return
    platform.async_register_entity_service(
        SERVICE_ADD_VISITOR_PASSWORD,
        {
            vol.Required("pin"): vol.All(cv.string, vol.Match(r"^\d+$"), vol.Length(min=4)),
            vol.Optional("group_id", default=1): vol.All(int, vol.Range(min=0, max=255)),
        },
        "async_add_visitor_password",
    )
    # Entity service: delete a credential (and its user) by the lock's user id.
    platform.async_register_entity_service(
        SERVICE_DELETE_USER,
        {
            vol.Required("user_id"): vol.All(int, vol.Range(min=0, max=0xFFFFFFFF)),
        },
        "async_delete_user",
    )


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
        """Return the lock state (optimistic until a real state read lands).

        The U200 does not push its bolt position on this path yet, so the state
        reflects the last confirmed actuation (lock/unlock) and is ``None``
        (unknown) until the first one after setup.
        """
        return self.coordinator.data.is_locked

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

    async def async_add_visitor_password(self, pin: str, group_id: int = 1) -> None:
        """Enrol a visitor PIN over BLE (service target: this lock).

        Offline-capable (uses the library's ``add_visitor_password``). The PIN is
        an even number of digits; the front keypad panel must be awake (the
        coordinator wakes it / asks you first).
        """
        try:
            await self.coordinator.async_add_visitor_password(pin, group_id)
        except AqaraU200Error as err:
            raise HomeAssistantError(str(err)) from err

    async def async_delete_user(self, user_id: int) -> None:
        """Delete a credential + its user over BLE (service target: this lock).

        ``user_id`` is the lock's full user id (as the credentials sensor / cloud
        report it). Offline-capable; the front keypad panel must be awake (the
        coordinator wakes it / asks you first, and errors if it stays asleep
        instead of silently doing nothing).
        """
        try:
            await self.coordinator.async_delete_user(user_id)
        except AqaraU200Error as err:
            raise HomeAssistantError(str(err)) from err
