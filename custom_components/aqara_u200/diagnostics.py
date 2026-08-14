"""Diagnostics for Aqara U200 BLE."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import AqaraU200ConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: AqaraU200ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics without account credentials or session material."""
    runtime = entry.runtime_data
    return {
        "entry": {
            "title": entry.title,
            "version": entry.version,
        },
        "device": {
            "address": runtime.address,
            "device_id": runtime.device_id,
            "region": runtime.region,
        },
        "control_enabled": False,
        "control_blocker": "protocol library cloud I/O must be made async-safe before HA control is enabled",
    }
