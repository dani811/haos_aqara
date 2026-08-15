"""Tests for the push runtime coordinator."""

import asyncio

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.aqara_u200.bluetooth import AqaraU200BluetoothState
from custom_components.aqara_u200.coordinator import AqaraU200Coordinator
from custom_components.aqara_u200.exceptions import AqaraU200OperationError


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
