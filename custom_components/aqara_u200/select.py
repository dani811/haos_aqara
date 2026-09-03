"""Select platform for Aqara U200 (settable configuration values).

Replaces the old read-only ``alert_volume``/``alarm_volume`` sensors: these
two settings are both readable AND writable over BLE (byte-confirmed SET
frames in ``aqara_ble``), so they belong here instead, where the card and any
dashboard can change them, not just display them. Other settings
(system volume, language) stay sensor-only for now — their SET side either
has no confirmed enum for every level (system volume) or carries real risk of
leaving the lock's spoken language wrong if guessed (see
docs/devices/u200/operations.md's 2026-08-30 language write-up).
"""

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import AqaraU200ConfigEntry
from .const import DOMAIN, LANGUAGE_OPTIONS
from .coordinator import AqaraU200Coordinator
from .exceptions import AqaraU200Error

#: Alert-volume option -> the byte the write frame expects (1=Alto..4=Silencio),
#: matching aqara_ble.lock_state.decode_alert_volume's read-side enum exactly.
_ALERT_VOLUME_LEVELS = {"high": 1, "medium": 2, "low": 3, "silent": 4}

#: Alarm (siren) volume: only 2 levels exist on the wire (0x83). The read side
#: (aqara_ble.decode_alarm_volume) is not pinned to named levels yet — it
#: returns the raw value hex — so map the two confirmed bytes here rather than
#: depending on a decoder this integration doesn't fully trust yet.
_ALARM_VOLUME_READ = {"00": "silent", "10": "normal"}
_ALARM_VOLUME_IS_SILENT = {"normal": False, "silent": True}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AqaraU200ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Aqara U200 select entities (settable settings)."""
    del hass
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [
            AqaraU200AlertVolumeSelect(entry, coordinator),
            AqaraU200AlarmVolumeSelect(entry, coordinator),
            AqaraU200LanguageSelect(entry, coordinator),
        ]
    )


class _AqaraU200SelectBase(CoordinatorEntity[AqaraU200Coordinator], SelectEntity):
    """Shared device-info wiring for the settable feature-setting selects."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

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


class AqaraU200AlertVolumeSelect(_AqaraU200SelectBase):
    """Alert-volume level (Alto/Medio/Bajo/Silencio) — read AND set over BLE."""

    _attr_translation_key = "alert_volume"
    _attr_options = list(_ALERT_VOLUME_LEVELS)

    def __init__(self, entry: AqaraU200ConfigEntry, coordinator: AqaraU200Coordinator) -> None:
        """Initialize the alert-volume select."""
        super().__init__(entry, coordinator, "alert_volume")

    @property
    def current_option(self) -> str | None:
        """Return the alert volume level, or None until read / if unrecognised."""
        value = self.coordinator.data.alert_volume
        return value if value in self._attr_options else None

    async def async_select_option(self, option: str) -> None:
        """Set the alert volume to ``option`` over BLE."""
        try:
            await self.coordinator.async_set_alert_volume(_ALERT_VOLUME_LEVELS[option])
        except AqaraU200Error as err:
            raise HomeAssistantError(str(err)) from err


class AqaraU200AlarmVolumeSelect(_AqaraU200SelectBase):
    """Alarm (siren) volume (Normal/Silencio) — read AND set over BLE."""

    _attr_translation_key = "alarm_volume"
    _attr_options = list(_ALARM_VOLUME_IS_SILENT)

    def __init__(self, entry: AqaraU200ConfigEntry, coordinator: AqaraU200Coordinator) -> None:
        """Initialize the alarm-volume select."""
        super().__init__(entry, coordinator, "alarm_volume")

    @property
    def current_option(self) -> str | None:
        """Return 'normal'/'silent' decoded from the raw read value, or None."""
        raw = self.coordinator.data.alarm_volume
        return _ALARM_VOLUME_READ.get(raw) if raw is not None else None

    async def async_select_option(self, option: str) -> None:
        """Set the alarm volume to ``option`` over BLE."""
        try:
            await self.coordinator.async_set_alarm_volume(
                silent=_ALARM_VOLUME_IS_SILENT[option]
            )
        except AqaraU200Error as err:
            raise HomeAssistantError(str(err)) from err


class AqaraU200LanguageSelect(_AqaraU200SelectBase):
    """Spoken-prompt language — changed via the cloud voice-pack OTA.

    Selecting a language starts a ~10-minute OTA that the lock gates behind a
    physical keypad press (the coordinator fires an event + notification so a
    fingerbot automation can authorise it). It runs in the background, so the
    UI call returns at once; the shown value updates when the new language is
    read back after the transfer. Only 'es' reads back today (the library's
    decoder), so a just-changed non-Spanish language may show blank until its
    read-side code is added — the change itself still applies.
    """

    _attr_translation_key = "language"
    _attr_options = list(LANGUAGE_OPTIONS)

    def __init__(self, entry: AqaraU200ConfigEntry, coordinator: AqaraU200Coordinator) -> None:
        """Initialize the language select."""
        super().__init__(entry, coordinator, "language")

    @property
    def current_option(self) -> str | None:
        """Return the read-back language code, or None until read / if unknown."""
        value = self.coordinator.data.language
        return value if value in self._attr_options else None

    async def async_select_option(self, option: str) -> None:
        """Start the language-change OTA in the background (does not block the UI)."""
        self.coordinator.config_entry.async_create_background_task(
            self.coordinator.hass,
            self.coordinator.async_change_language(option),
            f"{DOMAIN}_change_language",
        )
