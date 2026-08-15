"""Aqara U200 BLE integration."""

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .bluetooth import AqaraU200BluetoothManager
from .client import AqaraU200Client, PendingAqaraU200Client
from .const import CONF_DEVICE_ID, CONF_REGION, DEFAULT_REGION
from .coordinator import AqaraU200Coordinator
from .frontend import async_register_frontend

PLATFORMS: tuple[Platform, ...] = (Platform.LOCK,)


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
    """Set up an Aqara U200 config entry without enabling unsafe actuation."""
    address = entry.data[CONF_ADDRESS]
    bluetooth_manager = AqaraU200BluetoothManager(hass, address)

    # Deliberately fail closed until aqara-u200-ble publishes the async-safe
    # cloud/session behavior and a real adapter is pinned here.
    client: AqaraU200Client = PendingAqaraU200Client()
    coordinator = AqaraU200Coordinator(hass, entry, bluetooth_manager, client)

    entry.runtime_data = AqaraU200RuntimeData(
        address=address,
        device_id=entry.data[CONF_DEVICE_ID],
        region=entry.data.get(CONF_REGION, DEFAULT_REGION),
        bluetooth=bluetooth_manager,
        client=client,
        coordinator=coordinator,
    )

    entry.async_on_unload(
        bluetooth_manager.async_start(coordinator.async_handle_bluetooth_state)
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AqaraU200ConfigEntry) -> bool:
    """Unload platforms; entry unload callbacks release Bluetooth subscriptions."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
