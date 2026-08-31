"""Sensor platform for Aqara U200 (BLE signal strength)."""

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfTime,
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
    """Set up the Aqara U200 sensors (battery, RSSI, door type, retraction)."""
    del hass
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [
            AqaraU200Battery(entry, coordinator),
            AqaraU200Rssi(entry, coordinator),
            AqaraU200DoorType(entry, coordinator),
            AqaraU200PullSpringRetraction(entry, coordinator),
            AqaraU200SystemVolume(entry, coordinator),
            AqaraU200Language(entry, coordinator),
        ]
    )


class _AqaraU200SensorBase(CoordinatorEntity[AqaraU200Coordinator], SensorEntity):
    """Shared device-info wiring for the diagnostic feature-setting sensors."""

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


class AqaraU200DoorType(_AqaraU200SensorBase):
    """The configured door-lock type (EU/UK/US), read over BLE."""

    _attr_translation_key = "door_type"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["eu", "uk", "us"]

    def __init__(self, entry: AqaraU200ConfigEntry, coordinator: AqaraU200Coordinator) -> None:
        """Initialize the door-type sensor."""
        super().__init__(entry, coordinator, "door_type")

    @property
    def native_value(self) -> str | None:
        """Return the door type ('eu'/'uk'/'us'), or None until read."""
        value = self.coordinator.data.door_type
        return value if value in self._attr_options else None


class AqaraU200PullSpringRetraction(_AqaraU200SensorBase):
    """The pull-spring bolt-retraction time (seconds), read over BLE."""

    _attr_translation_key = "pull_spring_retraction"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS

    def __init__(self, entry: AqaraU200ConfigEntry, coordinator: AqaraU200Coordinator) -> None:
        """Initialize the retraction-time sensor."""
        super().__init__(entry, coordinator, "pull_spring_retraction")

    @property
    def native_value(self) -> int | None:
        """Return the retraction time in seconds, or None until read."""
        return self.coordinator.data.pull_spring_retraction_s


class AqaraU200SystemVolume(_AqaraU200SensorBase):
    """The system/voice volume level, read over BLE (0xc3)."""

    _attr_translation_key = "system_volume"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, entry: AqaraU200ConfigEntry, coordinator: AqaraU200Coordinator) -> None:
        """Initialize the system-volume sensor."""
        super().__init__(entry, coordinator, "system_volume")

    @property
    def native_value(self) -> int | None:
        """Return the raw system-volume level, or None until read."""
        return self.coordinator.data.system_volume


class AqaraU200Language(_AqaraU200SensorBase):
    """The lock's configured language, read over BLE (0x68)."""

    _attr_translation_key = "language"

    def __init__(self, entry: AqaraU200ConfigEntry, coordinator: AqaraU200Coordinator) -> None:
        """Initialize the language sensor."""
        super().__init__(entry, coordinator, "language")

    @property
    def native_value(self) -> str | None:
        """Return the language code (e.g. 'es'), or None until read."""
        return self.coordinator.data.language


class AqaraU200Battery(CoordinatorEntity[AqaraU200Coordinator], SensorEntity):
    """The lock's battery charge, read over BLE (GET_BATTERY_INFO)."""

    _attr_has_entity_name = True
    _attr_translation_key = "battery"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        entry: AqaraU200ConfigEntry,
        coordinator: AqaraU200Coordinator,
    ) -> None:
        """Initialize the battery sensor."""
        super().__init__(coordinator)
        address = entry.runtime_data.address
        self._attr_unique_id = f"{address}_battery"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            manufacturer="Aqara",
            model="U200",
            name=entry.title,
        )

    @property
    def native_value(self) -> int | None:
        """Return the battery percentage (None until the first BLE read)."""
        return self.coordinator.data.battery_percent


class AqaraU200Rssi(CoordinatorEntity[AqaraU200Coordinator], SensorEntity):
    """The lock's last-seen BLE signal strength (RSSI)."""

    _attr_has_entity_name = True
    _attr_translation_key = "rssi"
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        entry: AqaraU200ConfigEntry,
        coordinator: AqaraU200Coordinator,
    ) -> None:
        """Initialize the RSSI sensor."""
        super().__init__(coordinator)
        address = entry.runtime_data.address
        self._attr_unique_id = f"{address}_rssi"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            manufacturer="Aqara",
            model="U200",
            name=entry.title,
        )

    @property
    def native_value(self) -> int | None:
        """Return the last-seen RSSI in dBm (None if not yet advertised)."""
        return self.coordinator.data.rssi
