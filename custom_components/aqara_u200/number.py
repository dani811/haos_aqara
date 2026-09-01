"""Number platform for Aqara U200 — settable timer values with no read decoder yet.

Four SET frames are byte-confirmed in ``aqara_ble`` (real live captures, see
``docs/devices/u200/operations.md``): the open-door alarm delay ("Retraso de
alerta", 0x18), the keypad-lockout duration ("Bloqueo de verificación", 0xaf),
and both auto-lock timers ("Re-bloqueo de seguridad" / "Bloqueo automático al
cerrar", both on 0xd5). Their matching GET replies (0xb0/0xd6) answer over BLE
but only as raw, undecoded bytes — no confirmed byte-to-seconds mapping exists
for the read side yet, unlike alert_volume/alarm_volume in select.py.

These entities are therefore **set-only for now**: writing them sends the
real, confirmed frame and the lock genuinely applies it (verified live,
change-then-reread), but ``native_value`` has nothing honest to report and
stays ``None`` (renders as unknown) rather than echo back the last value this
integration happened to send, which would silently drift from the lock's real
state the moment it's changed from the app or a keypad instead of here. Once
a read-side decoder for 0xb0/0xd6 lands, wire ``native_value`` to
``coordinator.data`` the same way select.py does for alert/alarm volume.
"""

from collections.abc import Awaitable, Callable

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
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
    """Set up the Aqara U200 set-only timer number entities."""
    del hass
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [
            AqaraU200TimerNumber(
                entry,
                coordinator,
                key="alert_delay",
                # App preset list tops out at 180s (3 min); the wire format is
                # a plain 1-byte seconds value (0-255), so allow the full range.
                native_min_value=0,
                native_max_value=255,
                setter=coordinator.async_set_alert_delay,
            ),
            AqaraU200TimerNumber(
                entry,
                coordinator,
                key="verify_fail_time",
                # 0xaf's seconds field is 4 bytes on the wire; the app only
                # offers up to 30 min (1800s) so cap the UI there too.
                native_min_value=0,
                native_max_value=1800,
                setter=coordinator.async_set_verify_fail_time,
            ),
            AqaraU200TimerNumber(
                entry,
                coordinator,
                key="auto_lockup_relock_delay",
                native_min_value=0,
                native_max_value=65535,
                setter=coordinator.async_set_auto_lockup_relock_delay,
            ),
            AqaraU200TimerNumber(
                entry,
                coordinator,
                key="auto_lock_on_close_delay",
                native_min_value=0,
                native_max_value=65535,
                setter=coordinator.async_set_auto_lock_on_close_delay,
            ),
        ]
    )


class AqaraU200TimerNumber(CoordinatorEntity[AqaraU200Coordinator], NumberEntity):
    """A byte-confirmed timer SET with no confirmed read-side decoder yet."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = "s"
    _attr_native_step = 1

    def __init__(
        self,
        entry: AqaraU200ConfigEntry,
        coordinator: AqaraU200Coordinator,
        *,
        key: str,
        native_min_value: float,
        native_max_value: float,
        setter: Callable[[int], Awaitable[None]],
    ) -> None:
        """Initialize a set-only timer number entity."""
        super().__init__(coordinator)
        self._setter = setter
        self._attr_translation_key = key
        self._attr_native_min_value = native_min_value
        self._attr_native_max_value = native_max_value
        address = entry.runtime_data.address
        self._attr_unique_id = f"{address}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            manufacturer="Aqara",
            model="U200",
            name=entry.title,
        )

    @property
    def native_value(self) -> float | None:
        """Return None: no confirmed read-side decoder exists yet (see module docstring)."""
        return None

    async def async_set_native_value(self, value: float) -> None:
        """Send the confirmed SET frame for ``value`` seconds over BLE."""
        try:
            await self._setter(int(value))
        except AqaraU200Error as err:
            raise HomeAssistantError(str(err)) from err
