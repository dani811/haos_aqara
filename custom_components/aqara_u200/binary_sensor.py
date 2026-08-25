"""Binary sensor platform for Aqara U200 (Bluetooth connectivity)."""

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
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
    """Set up the Aqara U200 binary sensors (connectivity, assist turn, pull spring)."""
    del hass
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [
            AqaraU200Connectivity(entry, coordinator),
            AqaraU200AssistTurn(entry, coordinator),
            AqaraU200PullSpring(entry, coordinator),
        ]
    )


class _AqaraU200FeatureBinary(
    CoordinatorEntity[AqaraU200Coordinator], BinarySensorEntity
):
    """Shared device-info wiring for the diagnostic feature-setting binary sensors."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        entry: AqaraU200ConfigEntry,
        coordinator: AqaraU200Coordinator,
        key: str,
    ) -> None:
        super().__init__(coordinator)
        address = entry.runtime_data.address
        self._attr_unique_id = f"{address}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            manufacturer="Aqara",
            model="U200",
            name=entry.title,
        )


class AqaraU200AssistTurn(_AqaraU200FeatureBinary):
    """Whether turn-assist is enabled (read over BLE)."""

    _attr_translation_key = "assist_turn"

    def __init__(self, entry: AqaraU200ConfigEntry, coordinator: AqaraU200Coordinator) -> None:
        """Initialize the assist-turn sensor."""
        super().__init__(entry, coordinator, "assist_turn")

    @property
    def is_on(self) -> bool | None:
        """Return whether turn-assist is enabled, or None until read."""
        return self.coordinator.data.assist_turn


class AqaraU200PullSpring(_AqaraU200FeatureBinary):
    """Whether the pull-spring function is enabled (read over BLE)."""

    _attr_translation_key = "pull_spring"

    def __init__(self, entry: AqaraU200ConfigEntry, coordinator: AqaraU200Coordinator) -> None:
        """Initialize the pull-spring sensor."""
        super().__init__(entry, coordinator, "pull_spring")

    @property
    def is_on(self) -> bool | None:
        """Return whether the pull-spring function is enabled, or None until read."""
        return self.coordinator.data.pull_spring_enabled


class AqaraU200Connectivity(
    CoordinatorEntity[AqaraU200Coordinator], BinarySensorEntity
):
    """Whether the lock is reachable over Home Assistant Bluetooth."""

    _attr_has_entity_name = True
    _attr_translation_key = "connectivity"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        entry: AqaraU200ConfigEntry,
        coordinator: AqaraU200Coordinator,
    ) -> None:
        """Initialize the connectivity sensor."""
        super().__init__(coordinator)
        address = entry.runtime_data.address
        self._attr_unique_id = f"{address}_connectivity"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            manufacturer="Aqara",
            model="U200",
            name=entry.title,
        )

    @property
    def is_on(self) -> bool:
        """Return True while the lock advertises to a connectable adapter."""
        return self.coordinator.data.reachable
