"""Tests for the push runtime coordinator."""

import asyncio
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.aqara_u200.bluetooth import AqaraU200BluetoothState
from custom_components.aqara_u200.client import LockSettings
from custom_components.aqara_u200.coordinator import AqaraU200Coordinator
from custom_components.aqara_u200.exceptions import (
    AqaraU200AuthenticationError,
    AqaraU200OperationError,
)


class FakeBluetoothManager:
    """Small fake exposing only the coordinator contract."""

    def __init__(self, reachable: bool = True) -> None:
        self.state = AqaraU200BluetoothState(reachable=reachable)


class BlockingClient:
    """Enabled client used to prove HA-side serialization."""

    control_enabled = True

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.first_started = asyncio.Event()
        self.release_first = asyncio.Event()

    async def async_unlock(self) -> None:
        self.calls.append("unlock")
        self.first_started.set()
        await self.release_first.wait()

    async def async_lock(self) -> None:
        self.calls.append("lock")


class FailingClient:
    """Enabled client that raises an unexpected exception."""

    control_enabled = True

    async def async_lock(self) -> None:
        raise RuntimeError("unsafe-detail-must-not-be-copied")

    async def async_unlock(self) -> None:
        raise RuntimeError("unsafe-detail-must-not-be-copied")


class AuthFailingClient:
    """Enabled client that asks Home Assistant to start reauth."""

    control_enabled = True

    async def async_lock(self) -> None:
        raise AqaraU200AuthenticationError("sanitized")

    async def async_unlock(self) -> None:
        raise AqaraU200AuthenticationError("sanitized")


def _entry() -> MockConfigEntry:
    return MockConfigEntry(domain="aqara_u200", data={})


async def test_same_entry_operations_are_serialized(hass) -> None:
    """A second HA action waits until the first client call completes."""
    client = BlockingClient()
    coordinator = AqaraU200Coordinator(hass, _entry(), FakeBluetoothManager(), client)

    first = asyncio.create_task(coordinator.async_unlock())
    await client.first_started.wait()

    second = asyncio.create_task(coordinator.async_lock())
    await asyncio.sleep(0)

    assert client.calls == ["unlock"]
    assert coordinator.operation_in_progress is True

    client.release_first.set()
    await asyncio.gather(first, second)

    assert client.calls == ["unlock", "lock"]
    assert coordinator.operation_in_progress is False
    assert coordinator.data.last_operation == "lock"


async def test_different_entries_can_operate_concurrently(hass) -> None:
    """Per-entry locks must not serialize different physical locks."""
    first_client = BlockingClient()
    second_client = BlockingClient()
    first_coordinator = AqaraU200Coordinator(
        hass, _entry(), FakeBluetoothManager(), first_client
    )
    second_coordinator = AqaraU200Coordinator(
        hass, _entry(), FakeBluetoothManager(), second_client
    )

    first_task = asyncio.create_task(first_coordinator.async_unlock())
    second_task = asyncio.create_task(second_coordinator.async_unlock())

    await asyncio.wait_for(
        asyncio.gather(
            first_client.first_started.wait(), second_client.first_started.wait()
        ),
        timeout=1,
    )

    assert first_coordinator.operation_in_progress is True
    assert second_coordinator.operation_in_progress is True

    first_client.release_first.set()
    second_client.release_first.set()
    await asyncio.gather(first_task, second_task)


async def test_operation_state_resets_after_error(hass) -> None:
    """An error must not leave HA-side operation state stuck busy."""
    coordinator = AqaraU200Coordinator(
        hass, _entry(), FakeBluetoothManager(), FailingClient()
    )

    with pytest.raises(AqaraU200OperationError) as error:
        await coordinator.async_lock()

    assert "unsafe-detail" not in str(error.value)
    assert coordinator.operation_in_progress is False
    assert coordinator.data.operation_in_progress is False
    assert coordinator.data.last_error_type == "RuntimeError"


async def test_auth_failure_starts_config_entry_reauth(hass) -> None:
    """A typed auth failure should launch one HA reauthentication flow."""
    entry = _entry()
    coordinator = AqaraU200Coordinator(
        hass, entry, FakeBluetoothManager(), AuthFailingClient()
    )

    with (
        patch.object(entry, "async_start_reauth") as start_reauth,
        pytest.raises(AqaraU200AuthenticationError),
    ):
        await coordinator.async_lock()

    start_reauth.assert_called_once_with(hass)
    assert coordinator.data.last_error_type == "AqaraU200AuthenticationError"


async def test_cancellation_releases_operation_state_and_lock(hass) -> None:
    """Cancellation must not leave this config entry permanently busy."""
    client = BlockingClient()
    coordinator = AqaraU200Coordinator(hass, _entry(), FakeBluetoothManager(), client)

    task = asyncio.create_task(coordinator.async_unlock())
    await client.first_started.wait()
    assert coordinator.operation_in_progress is True

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert coordinator.operation_in_progress is False
    assert coordinator.data.operation_in_progress is False

    # Prove the asyncio.Lock itself was also released by executing another action.
    await coordinator.async_lock()
    assert client.calls == ["unlock", "lock"]


class FullReadClient:
    """Client answering every read the initial-sync rotation performs."""

    control_enabled = True

    async def async_read_lock_status(self) -> bool | None:
        return True

    async def async_read_battery(self) -> int | None:
        return 88

    async def async_read_door_type(self) -> str | None:
        return "eu"

    async def async_read_assist_turn(self) -> bool | None:
        return False

    async def async_read_pull_spring(self) -> tuple[bool, int] | None:
        return (True, 2)

    async def async_read_settings(self) -> LockSettings:
        return LockSettings(
            system_volume=5,
            language="es",
            alert_volume="high",
            alarm_volume="10",
        )


async def test_initial_sync_reads_everything_on_setup(hass) -> None:
    """async_start_initial_sync must populate every value without user action.

    This is the fix for 'nothing shows until I press Refresh' — it schedules
    the same rotation the Refresh button uses as a background task so a fresh
    install or an HA restart eventually reads everything on its own.
    """
    coordinator = AqaraU200Coordinator(
        hass, _entry(), FakeBluetoothManager(), FullReadClient()
    )

    with patch("custom_components.aqara_u200.coordinator.asyncio.sleep"):
        coordinator.async_start_initial_sync()
        await hass.async_block_till_done()

    assert coordinator.data.is_locked is True
    assert coordinator.data.battery_percent == 88
    assert coordinator.data.door_type == "eu"
    assert coordinator.data.assist_turn is False
    assert coordinator.data.pull_spring_enabled is True
    assert coordinator.data.pull_spring_retraction_s == 2
    assert coordinator.data.system_volume == 5
    assert coordinator.data.language == "es"
    assert coordinator.data.alert_volume == "high"
    assert coordinator.data.alarm_volume == "10"


class FlakyConfigReadClient(FullReadClient):
    """Fails the 'config' burst exactly once, like the flaky proxy seen live."""

    def __init__(self) -> None:
        self.settings_calls = 0

    async def async_read_settings(self) -> LockSettings:
        self.settings_calls += 1
        if self.settings_calls == 1:
            raise TimeoutError("proxy dropped the connection")
        return await super().async_read_settings()


async def test_refresh_all_retries_a_read_that_failed_once(hass) -> None:
    """A single failed read must not stay unpopulated for the whole rotation.

    Confirmed live 2026-08-31: the 'config' burst (volume/language) can fail
    once through a flaky Bluetooth-proxy connection while every other read in
    the same rotation succeeds. async_refresh_all must retry just that gap
    instead of leaving it 'unknown' until the next restart or a manual
    Refresh press.
    """
    client = FlakyConfigReadClient()
    coordinator = AqaraU200Coordinator(hass, _entry(), FakeBluetoothManager(), client)

    with patch("custom_components.aqara_u200.coordinator.asyncio.sleep"):
        await coordinator.async_refresh_all()

    assert client.settings_calls == 2
    assert coordinator.data.language == "es"
    assert coordinator.data.system_volume == 5
    # Everything else read fine on the first pass — no wasted retries.
    assert coordinator.data.is_locked is True
    assert coordinator.data.battery_percent == 88
