"""Tests for the timer number entities (SET + optional read-back)."""

from types import SimpleNamespace

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.aqara_u200 import number as number_platform
from custom_components.aqara_u200.bluetooth import AqaraU200BluetoothState
from custom_components.aqara_u200.coordinator import AqaraU200Coordinator
from custom_components.aqara_u200.number import AqaraU200TimerNumber

ADDRESS = "AA:BB:CC:DD:EE:FF"


class FakeBluetoothManager:
    """Small fake exposing only the coordinator contract."""

    def __init__(self, reachable: bool = True) -> None:
        self.state = AqaraU200BluetoothState(reachable=reachable)


class NumberClient:
    """Records the coordinator's timer SET calls."""

    control_enabled = True

    def __init__(self) -> None:
        self.alert_delay_calls: list[int] = []
        self.verify_fail_time_calls: list[int] = []
        self.auto_lockup_relock_calls: list[int] = []
        self.auto_lock_on_close_calls: list[int] = []

    async def async_set_alert_delay(self, seconds: int) -> None:
        self.alert_delay_calls.append(seconds)

    async def async_set_verify_fail_time(self, seconds: int) -> None:
        self.verify_fail_time_calls.append(seconds)

    async def async_set_auto_lockup_relock_delay(self, seconds: int) -> None:
        self.auto_lockup_relock_calls.append(seconds)

    async def async_set_auto_lock_on_close_delay(self, seconds: int) -> None:
        self.auto_lock_on_close_calls.append(seconds)


def _coordinator(hass, client, *, reachable: bool = True) -> AqaraU200Coordinator:
    entry = MockConfigEntry(domain="aqara_u200", title="Aqara U200", data={})
    coordinator = AqaraU200Coordinator(
        hass, entry, FakeBluetoothManager(reachable=reachable), client
    )
    entry.runtime_data = SimpleNamespace(address=ADDRESS, coordinator=coordinator)
    return coordinator


def _seed(coordinator, **fields) -> None:
    """Apply timer reads into the coordinator's cache and pushed snapshot."""
    for name, value in fields.items():
        coordinator._apply_read(name, value)
    coordinator.data = coordinator._build_snapshot(coordinator.bluetooth_manager.state)


async def _entities(hass, coordinator) -> list[AqaraU200TimerNumber]:
    added: list[AqaraU200TimerNumber] = []
    await number_platform.async_setup_entry(
        hass, coordinator.config_entry, lambda new, *a, **k: added.extend(new)
    )
    return added


async def test_all_four_timer_numbers_are_created(hass) -> None:
    """The platform exposes exactly the four timer number entities."""
    coordinator = _coordinator(hass, NumberClient())
    entities = await _entities(hass, coordinator)

    keys = {e.translation_key for e in entities}
    assert keys == {
        "alert_delay",
        "verify_fail_time",
        "auto_lockup_relock_delay",
        "auto_lock_on_close_delay",
    }
    unique_ids = {e.unique_id for e in entities}
    assert unique_ids == {
        f"{ADDRESS}_alert_delay",
        f"{ADDRESS}_verify_fail_time",
        f"{ADDRESS}_auto_lockup_relock_delay",
        f"{ADDRESS}_auto_lock_on_close_delay",
    }
    for entity in entities:
        assert entity.device_info["manufacturer"] == "Aqara"
        assert entity.device_info["model"] == "U200"


async def test_native_value_is_none_until_read(hass) -> None:
    """Before any read, every entity reports unknown (None)."""
    coordinator = _coordinator(hass, NumberClient())
    entities = {e.translation_key: e for e in await _entities(hass, coordinator)}

    assert entities["alert_delay"].native_value is None
    assert entities["verify_fail_time"].native_value is None
    assert entities["auto_lockup_relock_delay"].native_value is None
    assert entities["auto_lock_on_close_delay"].native_value is None


async def test_native_value_reflects_coordinator_data(hass) -> None:
    """The three wired entities mirror the coordinator's read state."""
    coordinator = _coordinator(hass, NumberClient())
    _seed(
        coordinator,
        auto_lockup_relock_delay=30,
        auto_lock_on_close_delay=5,
        verify_fail_time=120,
    )
    entities = {e.translation_key: e for e in await _entities(hass, coordinator)}

    assert entities["auto_lockup_relock_delay"].native_value == 30
    assert entities["auto_lock_on_close_delay"].native_value == 5
    assert entities["verify_fail_time"].native_value == 120


async def test_alert_delay_native_value_reflects_coordinator_data(hass) -> None:
    """alert_delay now reads back (aqara-ble 1.17.5): native_value mirrors the
    coordinator's read state instead of staying write-only."""
    coordinator = _coordinator(hass, NumberClient())
    _seed(
        coordinator,
        alert_delay=45,
        auto_lockup_relock_delay=30,
        auto_lock_on_close_delay=5,
        verify_fail_time=120,
    )
    entity = {e.translation_key: e for e in await _entities(hass, coordinator)}[
        "alert_delay"
    ]

    assert entity.native_value == 45


async def test_alert_delay_native_value_none_while_front_panel_asleep(hass) -> None:
    """Front-panel gated: with no alert_delay read, native_value stays unknown (None)
    rather than echoing the last value this integration sent."""
    coordinator = _coordinator(hass, NumberClient())
    _seed(coordinator, auto_lockup_relock_delay=30, auto_lock_on_close_delay=5)
    entity = {e.translation_key: e for e in await _entities(hass, coordinator)}[
        "alert_delay"
    ]

    assert entity.native_value is None


async def test_verify_fail_time_native_value_none_when_undecoded(hass) -> None:
    """When the best-effort 0xb0 decoder never returns, the value stays unknown."""
    coordinator = _coordinator(hass, NumberClient())
    _seed(coordinator, auto_lockup_relock_delay=30, auto_lock_on_close_delay=5)
    entity = {e.translation_key: e for e in await _entities(hass, coordinator)}[
        "verify_fail_time"
    ]

    assert entity.native_value is None
    # The proven neighbours still show their values.


async def test_set_native_value_calls_the_setter(hass) -> None:
    """Writing each entity flows through to the matching coordinator setter."""
    client = NumberClient()
    coordinator = _coordinator(hass, client)
    entities = {e.translation_key: e for e in await _entities(hass, coordinator)}

    await entities["alert_delay"].async_set_native_value(10)
    await entities["verify_fail_time"].async_set_native_value(120)
    await entities["auto_lockup_relock_delay"].async_set_native_value(30)
    await entities["auto_lock_on_close_delay"].async_set_native_value(5)

    assert client.alert_delay_calls == [10]
    assert client.verify_fail_time_calls == [120]
    assert client.auto_lockup_relock_calls == [30]
    assert client.auto_lock_on_close_calls == [5]
