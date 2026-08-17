"""Tests for the protocol-independent client boundary and real BLE adapter."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from aqara_u200_ble import CloudServiceError
from bleak_retry_connector import BleakConnectionError

from custom_components.aqara_u200.client import AqaraU200BleClientAdapter
from custom_components.aqara_u200.exceptions import (
    AqaraU200AuthenticationError,
    AqaraU200BluetoothUnavailableError,
    AqaraU200OperationError,
)


def _adapter(manager: Mock) -> AqaraU200BleClientAdapter:
    return AqaraU200BleClientAdapter(manager, Mock(), "device-secret", "EU")


async def test_adapter_uses_fresh_ha_routed_connection_per_operation() -> None:
    """Every action wraps a fresh connector client and disconnects it."""
    ble_device = object()
    manager = Mock()
    manager.async_get_ble_device.return_value = ble_device
    first_connection = SimpleNamespace(disconnect=AsyncMock())
    second_connection = SimpleNamespace(disconnect=AsyncMock())
    protocol_client = SimpleNamespace(lock=AsyncMock(), unlock=AsyncMock())

    with (
        patch(
            "custom_components.aqara_u200.client.establish_connection",
            new=AsyncMock(side_effect=[first_connection, second_connection]),
        ) as connect,
        patch(
            "custom_components.aqara_u200.client.ProtocolU200Client.from_gatt",
            return_value=protocol_client,
        ) as from_gatt,
    ):
        adapter = _adapter(manager)
        await adapter.async_lock()
        await adapter.async_unlock()

    assert adapter.control_enabled is True
    assert connect.await_count == 2
    assert from_gatt.call_count == 2
    protocol_client.lock.assert_awaited_once_with()
    protocol_client.unlock.assert_awaited_once_with()
    first_connection.disconnect.assert_awaited_once_with()
    second_connection.disconnect.assert_awaited_once_with()
    _, first_device, _ = connect.await_args_list[0].args
    assert first_device is ble_device
    assert connect.await_args_list[0].kwargs["ble_device_callback"]() is ble_device


async def test_adapter_fails_before_connect_when_ha_cannot_resolve_device() -> None:
    """No scanner or connection is attempted when HA has no connectable path."""
    manager = Mock()
    manager.async_get_ble_device.return_value = None

    with (
        patch(
            "custom_components.aqara_u200.client.establish_connection", new=AsyncMock()
        ) as connect,
        pytest.raises(AqaraU200BluetoothUnavailableError),
    ):
        await _adapter(manager).async_lock()

    connect.assert_not_awaited()


async def test_adapter_sanitizes_connection_failure() -> None:
    """Raw connector details must not cross the integration boundary."""
    manager = Mock()
    manager.async_get_ble_device.return_value = object()

    with (
        patch(
            "custom_components.aqara_u200.client.establish_connection",
            new=AsyncMock(side_effect=BleakConnectionError("raw-secret")),
        ),
        pytest.raises(AqaraU200BluetoothUnavailableError) as error,
    ):
        await _adapter(manager).async_unlock()

    assert "raw-secret" not in str(error.value)


async def test_adapter_maps_invalid_auth_and_disconnects() -> None:
    """Aqara code 810 maps to a sanitized integration auth error."""
    manager = Mock()
    manager.async_get_ble_device.return_value = object()
    connection = SimpleNamespace(disconnect=AsyncMock())
    cloud_error = CloudServiceError(
        code=810,
        message="raw-password-detail",
        endpoint="raw-endpoint",
    )
    wrapped_error = RuntimeError("raw-wrapper")
    wrapped_error.__cause__ = cloud_error
    protocol_client = SimpleNamespace(
        lock=AsyncMock(side_effect=wrapped_error), unlock=AsyncMock()
    )

    with (
        patch(
            "custom_components.aqara_u200.client.establish_connection",
            new=AsyncMock(return_value=connection),
        ),
        patch(
            "custom_components.aqara_u200.client.ProtocolU200Client.from_gatt",
            return_value=protocol_client,
        ),
        pytest.raises(AqaraU200AuthenticationError) as error,
    ):
        await _adapter(manager).async_lock()

    assert "raw" not in str(error.value)
    protocol_client.lock.assert_awaited_once_with()
    connection.disconnect.assert_awaited_once_with()


async def test_adapter_never_retries_after_operation_starts() -> None:
    """An ambiguous post-actuation failure is returned after exactly one call."""
    manager = Mock()
    manager.async_get_ble_device.return_value = object()
    connection = SimpleNamespace(disconnect=AsyncMock())
    protocol_client = SimpleNamespace(
        lock=AsyncMock(), unlock=AsyncMock(side_effect=RuntimeError("raw-crypto"))
    )

    with (
        patch(
            "custom_components.aqara_u200.client.establish_connection",
            new=AsyncMock(return_value=connection),
        ) as connect,
        patch(
            "custom_components.aqara_u200.client.ProtocolU200Client.from_gatt",
            return_value=protocol_client,
        ),
        pytest.raises(AqaraU200OperationError) as error,
    ):
        await _adapter(manager).async_unlock()

    assert "raw-crypto" not in str(error.value)
    connect.assert_awaited_once()
    protocol_client.unlock.assert_awaited_once_with()
    connection.disconnect.assert_awaited_once_with()
