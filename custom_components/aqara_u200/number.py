"""Number platform for Aqara U200 — settable timer values.

Four SET frames are byte-confirmed in ``aqara_ble`` (real live captures, see
``docs/devices/u200/operations.md``): the alert delay ("Retraso de alerta",
``no_close_delay`` in the 0x18 unlock-alarm struct), the keypad-lockout
duration ("Bloqueo de verificación", 0xaf), and both auto-lock timers
("Re-bloqueo de seguridad" / "Bloqueo automático al cerrar", 0xd5/0xad).

All four now read back over BLE, so their ``native_value`` reflects what the
lock actually reports (via ``coordinator.data``, the same way select.py reads
alert/alarm volume):

* ``auto_lockup_relock_delay`` — GET 0xd6 (PROVEN)
* ``auto_lock_on_close_delay`` — GET 0xae (PROVEN)
* ``verify_fail_time`` — GET 0xb0 (INFERRED, best-effort: may stay unknown
  until the decoder is live-confirmed; the coordinator never blocks its steady
  poll on it)
* ``alert_delay`` — read from the unlock-alarm struct (``no_close_delay``,
  aqara-ble 1.17.5). Front-panel gated: the struct is only readable while the
  keypad alarm subsystem is awake, so it renders as unknown while the keypad
  sleeps (consistent with volume/language) rather than echoing the last value
  this integration happened to send; the coordinator never blocks its steady
  poll on it either.

The alert-delay SET is read-modify-write in the library (it rewrites the whole
0x18 struct, changing only ``no_close_delay``) and RAISES if it cannot read the
struct first, so it never clobbers the three sibling alarm settings.
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
from .coordinator import AqaraU200Coordinator, AqaraU200RuntimeSnapshot
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
                # Read-back via the unlock-alarm struct (no_close_delay). Front-
                # panel gated, so it shows the value when the keypad alarm
                # subsystem is awake and stays unknown otherwise (like volume/
                # language). See docstring.
                value_fn=lambda data: data.alert_delay,
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
                # Best-effort read (0xb0, INFERRED): shows the value when it
                # decodes, stays unknown otherwise.
                value_fn=lambda data: data.verify_fail_time,
            ),
            AqaraU200TimerNumber(
                entry,
                coordinator,
                key="auto_lockup_relock_delay",
                native_min_value=0,
                native_max_value=65535,
                setter=coordinator.async_set_auto_lockup_relock_delay,
                value_fn=lambda data: data.auto_lockup_relock_delay,
            ),
            AqaraU200TimerNumber(
                entry,
                coordinator,
                key="auto_lock_on_close_delay",
                native_min_value=0,
                native_max_value=65535,
                setter=coordinator.async_set_auto_lock_on_close_delay,
                value_fn=lambda data: data.auto_lock_on_close_delay,
            ),
        ]
    )


class AqaraU200TimerNumber(CoordinatorEntity[AqaraU200Coordinator], NumberEntity):
    """A byte-confirmed timer SET, optionally read back from ``coordinator.data``.

    ``value_fn`` reads the entity's current value out of the coordinator
    snapshot exactly like select.py's ``current_option``. Passing ``None`` keeps
    the entity write-only (``native_value`` stays ``None`` -> unknown) for a key
    whose read side has no confirmed decoder yet (``alert_delay``).
    """

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
        value_fn: Callable[[AqaraU200RuntimeSnapshot], float | None] | None = None,
    ) -> None:
        """Initialize a timer number entity (read-back optional via ``value_fn``)."""
        super().__init__(coordinator)
        self._setter = setter
        self._value_fn = value_fn
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
        """Return the value read from ``coordinator.data``, or None if write-only.

        Write-only keys (no confirmed read decoder, e.g. ``alert_delay``) pass no
        ``value_fn`` and stay None (unknown), rather than echoing the last value
        written — see the module docstring.
        """
        if self._value_fn is None:
            return None
        return self._value_fn(self.coordinator.data)

    async def async_set_native_value(self, value: float) -> None:
        """Send the confirmed SET frame for ``value`` seconds over BLE."""
        try:
            await self._setter(int(value))
        except AqaraU200Error as err:
            raise HomeAssistantError(str(err)) from err
