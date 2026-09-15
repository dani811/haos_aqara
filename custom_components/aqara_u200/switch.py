"""Switch platform for Aqara U200 — bidirectional boolean back-panel settings.

Three toggles are exposed whose full ON/OFF state is byte-confirmed in
``aqara_ble`` (0xe8 turn-assist; 0xc4 auxiliary-locking full mask):

- **Turn assist** (``assist_turn``) — the lock's motorised turn assist.
- **Auto-lock on close** (``auxiliary_close_to_lock``) — 'Bloqueo automático al
  cerrar'.
- **Security re-lock** (``auxiliary_resume_lock``) — 'Re-bloqueo de seguridad'.

Unlike the one-way ``button`` enables (kept for back-compat), these have a
confirmed read side and a confirmed OFF frame, so a real toggle is honest. The
two auxiliary toggles share one 4-bit mask on the wire, so the coordinator writes
them read-modify-write (flip one bit, preserve the rest). All three are back-panel
settings — no keypad-presence wake is needed.
"""

from collections.abc import Awaitable, Callable

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import AqaraU200ConfigEntry
from .const import DOMAIN
from .coordinator import AqaraU200Coordinator, AqaraU200RuntimeSnapshot
from .exceptions import AqaraU200Error


def _close_to_lock(data: AqaraU200RuntimeSnapshot) -> bool | None:
    """Return the auto-lock-on-close bit, or None until the mask is read."""
    if data.auxiliary_locking is None:
        return None
    return data.auxiliary_locking.get("close_to_lock")


def _resume_lock(data: AqaraU200RuntimeSnapshot) -> bool | None:
    """Return the security-re-lock bit, or None until the mask is read."""
    if data.auxiliary_locking is None:
        return None
    return data.auxiliary_locking.get("resume_lock")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AqaraU200ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Aqara U200 boolean-setting switches."""
    del hass
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [
            AqaraU200SettingSwitch(
                entry,
                coordinator,
                key="assist_turn",
                is_on_fn=lambda data: data.assist_turn,
                setter=coordinator.async_set_assist_turn,
            ),
            AqaraU200SettingSwitch(
                entry,
                coordinator,
                key="auxiliary_close_to_lock",
                is_on_fn=_close_to_lock,
                setter=coordinator.async_set_auxiliary_close_to_lock,
            ),
            AqaraU200SettingSwitch(
                entry,
                coordinator,
                key="auxiliary_resume_lock",
                is_on_fn=_resume_lock,
                setter=coordinator.async_set_auxiliary_resume_lock,
            ),
        ]
    )


class AqaraU200SettingSwitch(CoordinatorEntity[AqaraU200Coordinator], SwitchEntity):
    """A byte-confirmed boolean setting with both a read side and an OFF frame."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        entry: AqaraU200ConfigEntry,
        coordinator: AqaraU200Coordinator,
        *,
        key: str,
        is_on_fn: Callable[[AqaraU200RuntimeSnapshot], bool | None],
        setter: Callable[[bool], Awaitable[None]],
    ) -> None:
        """Initialize a boolean-setting switch."""
        super().__init__(coordinator)
        self._is_on_fn = is_on_fn
        self._setter = setter
        self._attr_translation_key = key
        address = entry.runtime_data.address
        self._attr_unique_id = f"{address}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            manufacturer="Aqara",
            model="U200",
            name=entry.title,
        )

    @property
    def is_on(self) -> bool | None:
        """Return the toggle state, or None (unknown) until read over BLE."""
        return self._is_on_fn(self.coordinator.data)

    async def async_turn_on(self, **kwargs: object) -> None:
        """Enable the setting over BLE."""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: object) -> None:
        """Disable the setting over BLE."""
        await self._async_set(False)

    async def _async_set(self, enabled: bool) -> None:
        """Send the confirmed SET frame and surface a failed write as an error."""
        try:
            await self._setter(enabled)
        except AqaraU200Error as err:
            raise HomeAssistantError(str(err)) from err
