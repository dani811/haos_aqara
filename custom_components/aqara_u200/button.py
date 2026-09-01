"""Button platform for Aqara U200 — on-demand BLE refresh + one-way SET actions."""

from collections.abc import Awaitable, Callable

from homeassistant.components.button import ButtonEntity
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
    """Set up the Aqara U200 refresh button and the auxiliary-locking enables."""
    del hass
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [
            AqaraU200Refresh(entry, coordinator),
            AqaraU200EnableAction(
                entry,
                coordinator,
                key="enable_auxiliary_locking_on_close",
                action=coordinator.async_enable_auxiliary_locking_on_close,
            ),
            AqaraU200EnableAction(
                entry,
                coordinator,
                key="enable_auxiliary_locking_relock",
                action=coordinator.async_enable_auxiliary_locking_relock,
            ),
        ]
    )


class AqaraU200Refresh(CoordinatorEntity[AqaraU200Coordinator], ButtonEntity):
    """Read battery, bolt position and settings over BLE, once, on demand.

    The integration does no background polling by default (it would saturate a
    shared Bluetooth proxy); press this to pull fresh values when you want them.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "refresh"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        entry: AqaraU200ConfigEntry,
        coordinator: AqaraU200Coordinator,
    ) -> None:
        """Initialize the refresh button."""
        super().__init__(coordinator)
        address = entry.runtime_data.address
        self._attr_unique_id = f"{address}_refresh"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            manufacturer="Aqara",
            model="U200",
            name=entry.title,
        )

    async def async_press(self) -> None:
        """Trigger a one-shot BLE read of every value (runs in the background)."""
        self.coordinator.config_entry.async_create_background_task(
            self.coordinator.hass,
            self.coordinator.async_refresh_all(),
            f"{DOMAIN}_refresh_button",
        )


class AqaraU200EnableAction(CoordinatorEntity[AqaraU200Coordinator], ButtonEntity):
    """A byte-confirmed 'enable X' SET with no confirmed disable frame yet.

    ``aqara_ble``'s auxiliary-locking builders (0xc4) only have a captured
    ENABLE frame for each of "Bloqueo automático al cerrar" and "Re-bloqueo de
    seguridad" — no OFF-state frame was ever isolated in a live capture, so
    there is nothing honest to expose as a toggle switch yet. A button that
    only turns the setting ON is the accurate shape for what's actually
    confirmed; see aqara_ble.lock_ops for the byte-level provenance.
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        entry: AqaraU200ConfigEntry,
        coordinator: AqaraU200Coordinator,
        *,
        key: str,
        action: Callable[[], Awaitable[None]],
    ) -> None:
        """Initialize a one-way enable action button."""
        super().__init__(coordinator)
        self._action = action
        self._attr_translation_key = key
        address = entry.runtime_data.address
        self._attr_unique_id = f"{address}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            manufacturer="Aqara",
            model="U200",
            name=entry.title,
        )

    async def async_press(self) -> None:
        """Send the confirmed ENABLE frame over BLE."""
        try:
            await self._action()
        except AqaraU200Error as err:
            raise HomeAssistantError(str(err)) from err
