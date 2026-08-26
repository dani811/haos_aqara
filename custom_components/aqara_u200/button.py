"""Button platform for Aqara U200 — on-demand BLE refresh."""

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import AqaraU200ConfigEntry
from .const import DOMAIN
from .coordinator import AqaraU200Coordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AqaraU200ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Aqara U200 on-demand refresh button."""
    del hass
    async_add_entities([AqaraU200Refresh(entry, entry.runtime_data.coordinator)])


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
