"""Diagnostics for Aqara U200 BLE."""

from typing import Any

from homeassistant.core import HomeAssistant

from . import AqaraU200ConfigEntry


def _redact_address(address: str) -> str:
    """Return a useful but non-identifying Bluetooth address suffix."""
    parts = address.split(":")
    if len(parts) >= 2:
        return "**:**:**:**:" + ":".join(parts[-2:])
    return "***" + address[-4:]


def _suffix(value: str) -> str:
    """Return only a short identifier suffix."""
    return "***" + value[-4:] if value else "***"


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: AqaraU200ConfigEntry
) -> dict[str, Any]:
    """Return sanitized diagnostics without account/session credentials."""
    del hass
    runtime = entry.runtime_data
    state = runtime.coordinator.data
    return {
        "entry": {
            "title": entry.title,
            "version": entry.version,
        },
        "device": {
            "address": _redact_address(runtime.address),
            "device_id_suffix": _suffix(runtime.device_id),
            "region": runtime.region,
        },
        "runtime": {
            "reachable": state.reachable,
            "last_seen": state.last_seen,
            "rssi": state.rssi,
            "control_enabled": state.control_enabled,
            "operation_in_progress": state.operation_in_progress,
            "last_operation": state.last_operation,
            "last_error_type": state.last_error_type,
        },
        "control_blocker": (
            None
            if state.control_enabled
            else "real protocol adapter intentionally not enabled"
        ),
    }
