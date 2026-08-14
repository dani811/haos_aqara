"""Aqara U200 BLE integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import CONF_DEVICE_ID, CONF_REGION, DEFAULT_REGION, DOMAIN
from .frontend import async_register_frontend


@dataclass(slots=True, frozen=True)
class AqaraU200RuntimeData:
    """Runtime state that is safe to expose to HA internals."""

    address: str
    device_id: str
    region: str


type AqaraU200ConfigEntry = ConfigEntry[AqaraU200RuntimeData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up integration-global resources."""
    await async_register_frontend(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: AqaraU200ConfigEntry) -> bool:
    """Set up an Aqara U200 config entry."""
    entry.runtime_data = AqaraU200RuntimeData(
        address=entry.data[CONF_ADDRESS],
        device_id=entry.data[CONF_DEVICE_ID],
        region=entry.data.get(CONF_REGION, DEFAULT_REGION),
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AqaraU200ConfigEntry) -> bool:
    """Unload an Aqara U200 config entry."""
    return True
