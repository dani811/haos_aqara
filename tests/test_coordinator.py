"""Tests for the push runtime coordinator."""

import asyncio
from unittest.mock import patch

import pytest
from aqara_ble import LockEvent
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
)

from custom_components.aqara_u200.bluetooth import AqaraU200BluetoothState
from custom_components.aqara_u200.client import LockSettings
from custom_components.aqara_u200.const import DOMAIN, EVENT_KEYPAD_PRESS_REQUIRED
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


async def test_realtime_unknown_event_fires_on_the_bus(hass) -> None:
    """An unrecognized ff62 opcode must still reach HA as a real event.

    This is the notification feature's data path: today a wrong-code/keypad-
    failure push (if the lock sends one at all) decodes as kind='unknown' —
    ``decode_event`` doesn't recognize the opcode yet, so it keeps ``raw_hex``
    but no interpreted meaning. Firing it anyway (instead of dropping it like
    the 'status' heartbeat) means a live capture immediately shows up as a
    real aqara_u200_event, and the card's notification badge can already
    react to 'something happened' before the opcode is decoded.
    """
    entry = _entry()
    coordinator = AqaraU200Coordinator(hass, entry, FakeBluetoothManager(), FullReadClient())
    events = async_capture_events(hass, f"{DOMAIN}_event")

    coordinator._on_realtime_event(
        LockEvent(raw_hex="ab00112233445566", kind="unknown")
    )
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data == {
        "entry_id": entry.entry_id,
        "kind": "unknown",
        "locked": None,
        "source": None,
        "timestamp": None,
        "raw_hex": "ab00112233445566",
    }


async def test_realtime_status_heartbeat_does_not_fire_on_the_bus(hass) -> None:
    """The periodic 0x15 heartbeat is not a notable event — must stay quiet."""
    coordinator = AqaraU200Coordinator(
        hass, _entry(), FakeBluetoothManager(), FullReadClient()
    )
    events = async_capture_events(hass, f"{DOMAIN}_event")

    coordinator._on_realtime_event(LockEvent(raw_hex="1500000000000000", kind="status"))
    await hass.async_block_till_done()

    assert events == []


class SettableClient(FullReadClient):
    """A client whose settings SET calls actually change what the next read returns.

    Mirrors the real lock's behavior closely enough to prove the coordinator
    re-reads after a SET rather than optimistically guessing: the value shown
    afterward is whatever this fake's ``read_settings`` reports, which only
    changes because the SET call mutated it — not because the coordinator
    assumed the requested value stuck.
    """

    def __init__(self) -> None:
        self.alert_volume = "high"
        self.alarm_volume = "10"
        self.set_alert_volume_calls: list[int] = []
        self.set_alarm_volume_calls: list[bool] = []

    async def async_read_settings(self) -> LockSettings:
        return LockSettings(
            system_volume=5,
            language="es",
            alert_volume=self.alert_volume,
            alarm_volume=self.alarm_volume,
        )

    async def async_set_alert_volume(self, level: int) -> None:
        self.set_alert_volume_calls.append(level)
        self.alert_volume = {1: "high", 2: "medium", 3: "low", 4: "silent"}[level]

    async def async_set_alarm_volume(self, *, silent: bool) -> None:
        self.set_alarm_volume_calls.append(silent)
        self.alarm_volume = "00" if silent else "10"


async def test_set_alert_volume_calls_the_client_then_shows_the_reread_value(hass) -> None:
    """A SET flows to the client and the resulting state is a fresh re-read."""
    client = SettableClient()
    coordinator = AqaraU200Coordinator(hass, _entry(), FakeBluetoothManager(), client)

    await coordinator.async_set_alert_volume(3)  # Bajo

    assert client.set_alert_volume_calls == [3]
    assert coordinator.data.alert_volume == "low"
    assert coordinator.operation_in_progress is False
    assert coordinator.data.last_operation == "set_alert_volume"


async def test_set_alarm_volume_calls_the_client_then_shows_the_reread_value(hass) -> None:
    """A SET flows to the client and the resulting state is a fresh re-read."""
    client = SettableClient()
    coordinator = AqaraU200Coordinator(hass, _entry(), FakeBluetoothManager(), client)

    await coordinator.async_set_alarm_volume(silent=True)

    assert client.set_alarm_volume_calls == [True]
    assert coordinator.data.alarm_volume == "00"


class LanguageClient(FullReadClient):
    """A client whose language-change 'OTA' mutates what the next read returns.

    Stands in for the real ~10-minute voice-pack OTA: records the requested
    language and, like the lock, reports it on the following settings read, so
    the test can prove the coordinator re-reads instead of guessing.
    """

    def __init__(self) -> None:
        self.language = "es"
        self.change_language_calls: list[str] = []

    async def async_read_settings(self) -> LockSettings:
        return LockSettings(
            system_volume=5,
            language=self.language,
            alert_volume="high",
            alarm_volume="10",
        )

    async def async_change_language(self, language: str) -> None:
        self.change_language_calls.append(language)
        self.language = language


async def test_change_language_fires_keypad_event_then_shows_reread_value(hass) -> None:
    """A language change announces the keypad press, calls the client, re-reads."""
    events = async_capture_events(hass, EVENT_KEYPAD_PRESS_REQUIRED)
    client = LanguageClient()
    coordinator = AqaraU200Coordinator(hass, _entry(), FakeBluetoothManager(), client)

    await coordinator.async_change_language("en")

    # The external keypad press is announced on the bus BEFORE the transfer, so a
    # fingerbot automation can authorise it inside the lock's presence window.
    assert len(events) == 1
    assert events[0].data["language"] == "en"
    assert "window_seconds" in events[0].data
    # The change flows to the client and the shown value is a fresh re-read.
    assert client.change_language_calls == ["en"]
    assert coordinator.data.language == "en"
    assert coordinator.operation_in_progress is False
    assert coordinator.data.last_operation == "change_language:en"


class TimerActionClient(FullReadClient):
    """A client recording calls to the set-only timer/enable SET operations.

    These have no confirmed read-side decoder yet (see number.py/button.py),
    so unlike ``SettableClient`` there is nothing for a re-read to reveal —
    these tests only prove the coordinator calls through and propagates a
    failed write, matching what's actually observable for this group.
    """

    def __init__(self) -> None:
        self.alert_delay_calls: list[int] = []
        self.verify_fail_time_calls: list[int] = []
        self.auto_lockup_relock_calls: list[int] = []
        self.auto_lock_on_close_calls: list[int] = []
        self.enable_on_close_calls = 0
        self.enable_relock_calls = 0

    async def async_set_alert_delay(self, seconds: int) -> None:
        self.alert_delay_calls.append(seconds)

    async def async_set_verify_fail_time(self, seconds: int) -> None:
        self.verify_fail_time_calls.append(seconds)

    async def async_set_auto_lockup_relock_delay(self, seconds: int) -> None:
        self.auto_lockup_relock_calls.append(seconds)

    async def async_set_auto_lock_on_close_delay(self, seconds: int) -> None:
        self.auto_lock_on_close_calls.append(seconds)

    async def async_enable_auxiliary_locking_on_close(self) -> None:
        self.enable_on_close_calls += 1

    async def async_enable_auxiliary_locking_relock(self) -> None:
        self.enable_relock_calls += 1


async def test_set_alert_delay_calls_the_client(hass) -> None:
    """A SET flows through to the client with the requested seconds."""
    client = TimerActionClient()
    coordinator = AqaraU200Coordinator(hass, _entry(), FakeBluetoothManager(), client)

    await coordinator.async_set_alert_delay(10)

    assert client.alert_delay_calls == [10]
    assert coordinator.data.last_operation == "set_alert_delay"


async def test_set_verify_fail_time_calls_the_client(hass) -> None:
    """A SET flows through to the client with the requested seconds."""
    client = TimerActionClient()
    coordinator = AqaraU200Coordinator(hass, _entry(), FakeBluetoothManager(), client)

    await coordinator.async_set_verify_fail_time(120)

    assert client.verify_fail_time_calls == [120]


async def test_set_auto_lockup_relock_delay_calls_the_client(hass) -> None:
    """A SET flows through to the client with the requested seconds."""
    client = TimerActionClient()
    coordinator = AqaraU200Coordinator(hass, _entry(), FakeBluetoothManager(), client)

    await coordinator.async_set_auto_lockup_relock_delay(10)

    assert client.auto_lockup_relock_calls == [10]


async def test_set_auto_lock_on_close_delay_calls_the_client(hass) -> None:
    """A SET flows through to the client with the requested seconds."""
    client = TimerActionClient()
    coordinator = AqaraU200Coordinator(hass, _entry(), FakeBluetoothManager(), client)

    await coordinator.async_set_auto_lock_on_close_delay(5)

    assert client.auto_lock_on_close_calls == [5]


async def test_enable_auxiliary_locking_on_close_calls_the_client(hass) -> None:
    """The one-way enable action flows through to the client."""
    client = TimerActionClient()
    coordinator = AqaraU200Coordinator(hass, _entry(), FakeBluetoothManager(), client)

    await coordinator.async_enable_auxiliary_locking_on_close()

    assert client.enable_on_close_calls == 1


async def test_enable_auxiliary_locking_relock_calls_the_client(hass) -> None:
    """The one-way enable action flows through to the client."""
    client = TimerActionClient()
    coordinator = AqaraU200Coordinator(hass, _entry(), FakeBluetoothManager(), client)

    await coordinator.async_enable_auxiliary_locking_relock()

    assert client.enable_relock_calls == 1


async def test_set_alert_delay_propagates_a_failed_write(hass) -> None:
    """A SET that the lock never acknowledges must surface as a real error."""

    class FailingClient(TimerActionClient):
        async def async_set_alert_delay(self, seconds: int) -> None:
            raise AqaraU200OperationError("Aqara U200 did not acknowledge set:0x18:...")

    coordinator = AqaraU200Coordinator(hass, _entry(), FakeBluetoothManager(), FailingClient())

    with pytest.raises(AqaraU200OperationError):
        await coordinator.async_set_alert_delay(10)

    assert coordinator.operation_in_progress is False
    assert coordinator.data.last_error_type == "AqaraU200OperationError"


async def test_enable_auxiliary_locking_on_close_propagates_a_failed_write(hass) -> None:
    """A SET that the lock never acknowledges must surface as a real error."""

    class FailingClient(TimerActionClient):
        async def async_enable_auxiliary_locking_on_close(self) -> None:
            raise AqaraU200OperationError("Aqara U200 did not acknowledge set:0xc4:...")

    coordinator = AqaraU200Coordinator(hass, _entry(), FakeBluetoothManager(), FailingClient())

    with pytest.raises(AqaraU200OperationError):
        await coordinator.async_enable_auxiliary_locking_on_close()

    assert coordinator.operation_in_progress is False
    assert coordinator.data.last_error_type == "AqaraU200OperationError"


async def test_set_alert_volume_propagates_a_failed_write(hass) -> None:
    """A SET that the lock never acknowledges must surface as a real error."""

    class FailingSetClient(SettableClient):
        async def async_set_alert_volume(self, level: int) -> None:
            raise AqaraU200OperationError("Aqara U200 did not acknowledge set:0x02:...")

    coordinator = AqaraU200Coordinator(hass, _entry(), FakeBluetoothManager(), FailingSetClient())

    with pytest.raises(AqaraU200OperationError):
        await coordinator.async_set_alert_volume(1)

    assert coordinator.operation_in_progress is False
    assert coordinator.data.last_error_type == "AqaraU200OperationError"
