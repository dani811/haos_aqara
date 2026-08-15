"""Tests for Home Assistant Bluetooth routing."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from custom_components.aqara_u200.bluetooth import AqaraU200BluetoothManager

ADDRESS = "AA:BB:CC:DD:EE:FF"


def test_manager_uses_ha_connectable_lookup(hass) -> None:
    """Reachability must be resolved through HA, not an owned scanner."""
    ble_device = object()
    with patch(
        "custom_components.aqara_u200.bluetooth.bluetooth.async_ble_device_from_address",
        return_value=ble_device,
    ) as resolver:
        manager = AqaraU200BluetoothManager(hass, ADDRESS)

    assert manager.state.reachable is True
    resolver.assert_called_once_with(hass, ADDRESS, connectable=True)


def test_discovery_unavailable_and_cleanup(hass) -> None:
    """Callbacks must push state and expose an unload cancellation function."""
    discovery_callback = None
    unavailable_callback = None
    cancel_discovery = Mock()
    cancel_unavailable = Mock()

    def register_callback(hass_arg, callback, matcher, mode):
        nonlocal discovery_callback
        assert hass_arg is hass
        assert matcher == {"address": ADDRESS, "connectable": True}
        discovery_callback = callback
        return cancel_discovery

    def track_unavailable(hass_arg, callback, address, *, connectable):
        nonlocal unavailable_callback
        assert hass_arg is hass
        assert address == ADDRESS
        assert connectable is True
        unavailable_callback = callback
        return cancel_unavailable

    with (
        patch(
            "custom_components.aqara_u200.bluetooth.bluetooth.async_ble_device_from_address",
            return_value=None,
        ),
        patch(
            "custom_components.aqara_u200.bluetooth.bluetooth.async_register_callback",
            side_effect=register_callback,
        ),
        patch(
            "custom_components.aqara_u200.bluetooth.bluetooth.async_track_unavailable",
            side_effect=track_unavailable,
        ),
    ):
        manager = AqaraU200BluetoothManager(hass, ADDRESS)
        states = []
        cancel = manager.async_start(states.append)

        assert discovery_callback is not None
        discovery_callback(SimpleNamespace(rssi=-52), object())
        assert states[-1].reachable is True
        assert states[-1].rssi == -52
        assert states[-1].last_seen is not None

        assert unavailable_callback is not None
        unavailable_callback(SimpleNamespace())
        assert states[-1].reachable is False

        cancel()

    cancel_discovery.assert_called_once_with()
    cancel_unavailable.assert_called_once_with()
