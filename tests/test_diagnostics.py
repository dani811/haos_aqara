"""Tests for safe diagnostics."""

from types import SimpleNamespace

from custom_components.aqara_u200.coordinator import AqaraU200RuntimeSnapshot
from custom_components.aqara_u200.diagnostics import async_get_config_entry_diagnostics


async def test_diagnostics_redact_identifiers_and_secrets(hass) -> None:
    """Diagnostics must expose runtime health without sensitive material."""
    full_address = "AA:BB:CC:DD:EE:FF"
    full_device_id = "aqara-device-secret-12345678"
    snapshot = AqaraU200RuntimeSnapshot(
        reachable=True,
        last_seen=None,
        rssi=-50,
        control_enabled=False,
        operation_in_progress=False,
        last_operation=None,
        last_error_type=None,
    )
    entry = SimpleNamespace(
        title="Aqara U200",
        version=1,
        runtime_data=SimpleNamespace(
            address=full_address,
            device_id=full_device_id,
            region="EU",
            coordinator=SimpleNamespace(data=snapshot),
        ),
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    rendered = repr(diagnostics)

    assert full_address not in rendered
    assert full_device_id not in rendered
    assert diagnostics["runtime"]["reachable"] is True
    assert diagnostics["runtime"]["control_enabled"] is False
