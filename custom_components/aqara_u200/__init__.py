"""Aqara U200 BLE integration."""

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .bluetooth import AqaraU200BluetoothManager
from .client import AqaraU200BleClientAdapter, AqaraU200Client, build_cloud_auth
from .const import (
    CONF_DEVICE_ID,
    CONF_REALTIME_STATE,
    CONF_REGION,
    DEFAULT_REALTIME_STATE,
    DEFAULT_REGION,
    DOMAIN,
)
from .coordinator import AqaraU200Coordinator
from .frontend import async_register_frontend

PLATFORMS: tuple[Platform, ...] = (
    Platform.LOCK,
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
)

# This integration is configured through the UI (config entries) only; it takes
# no YAML configuration under its domain.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass(slots=True)
class AqaraU200RuntimeData:
    """Typed runtime resources for one configured U200."""

    address: str
    device_id: str
    region: str
    bluetooth: AqaraU200BluetoothManager
    client: AqaraU200Client
    coordinator: AqaraU200Coordinator


type AqaraU200ConfigEntry = ConfigEntry[AqaraU200RuntimeData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up integration-global resources."""
    del config
    await async_register_frontend(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: AqaraU200ConfigEntry) -> bool:
    """Set up an Aqara U200 config entry."""
    address = entry.data[CONF_ADDRESS]
    bluetooth_manager = AqaraU200BluetoothManager(hass, address)

    try:
        auth = build_cloud_auth(entry.data)
    except KeyError as err:
        raise ConfigEntryAuthFailed(
            "Aqara cloud credentials are incomplete; reauthentication is required"
        ) from err

    device_id = entry.data[CONF_DEVICE_ID]
    region = entry.data.get(CONF_REGION, DEFAULT_REGION)
    client: AqaraU200Client = AqaraU200BleClientAdapter(
        bluetooth_manager, auth, device_id, region
    )
    coordinator = AqaraU200Coordinator(hass, entry, bluetooth_manager, client)

    entry.runtime_data = AqaraU200RuntimeData(
        address=address,
        device_id=device_id,
        region=region,
        bluetooth=bluetooth_manager,
        client=client,
        coordinator=coordinator,
    )

    entry.async_on_unload(
        bluetooth_manager.async_start(coordinator.async_handle_bluetooth_state)
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Opt-in real-time BLE state (persistent listen). Off by default.
    entry.async_on_unload(coordinator.async_stop_realtime)
    if entry.options.get(CONF_REALTIME_STATE, DEFAULT_REALTIME_STATE):
        coordinator.async_start_realtime()
    entry.async_on_unload(entry.add_update_listener(_async_reload_on_options))
    return True


async def _async_reload_on_options(
    hass: HomeAssistant, entry: AqaraU200ConfigEntry
) -> None:
    """Reload the entry when options (the real-time toggle) change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: AqaraU200ConfigEntry) -> bool:
    """Unload platforms; entry unload callbacks release Bluetooth subscriptions."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
