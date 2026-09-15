"""Tests for the boolean-setting switch entities."""

from types import SimpleNamespace

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.aqara_u200 import switch as switch_platform
from custom_components.aqara_u200.bluetooth import AqaraU200BluetoothState
from custom_components.aqara_u200.coordinator import AqaraU200Coordinator
from custom_components.aqara_u200.switch import AqaraU200SettingSwitch

ADDRESS = "AA:BB:CC:DD:EE:FF"


class FakeBluetoothManager:
    """Small fake exposing only the coordinator contract."""

    def __init__(self, reachable: bool = True) -> None:
        self.state = AqaraU200BluetoothState(reachable=reachable)


class SwitchClient:
    """Records the coordinator's SET calls and answers the confirming re-reads.

    The auxiliary write is a FULL 4-toggle mask, so ``aux_calls`` captures exactly
    what the coordinator's read-modify-write sent — that's what proves the other
    toggles were preserved.
    """

    control_enabled = True

    def __init__(self, *, assist_turn=None, aux=None) -> None:
        self._assist_turn = assist_turn
        self._aux = dict(aux) if aux is not None else None
        self.assist_calls: list[bool] = []
        self.aux_calls: list[dict[str, bool]] = []

    async def async_read_assist_turn(self) -> bool | None:
        return self._assist_turn

    async def async_read_auxiliary_locking(self) -> dict[str, bool] | None:
        return dict(self._aux) if self._aux is not None else None

    async def async_set_assist_turn(self, *, enabled: bool) -> None:
        self.assist_calls.append(enabled)
        self._assist_turn = enabled

    async def async_set_auxiliary_locking(
        self,
        *,
        touch_to_lock: bool,
        close_to_lock: bool,
        resume_lock: bool,
        any_unlock_lock: bool,
    ) -> None:
        mask = {
            "touch_to_lock": touch_to_lock,
            "close_to_lock": close_to_lock,
            "resume_lock": resume_lock,
            "any_unlock_lock": any_unlock_lock,
        }
        self.aux_calls.append(mask)
        self._aux = mask


def _coordinator(hass, client, *, reachable: bool = True) -> AqaraU200Coordinator:
    entry = MockConfigEntry(domain="aqara_u200", title="Aqara U200", data={})
    coordinator = AqaraU200Coordinator(
        hass, entry, FakeBluetoothManager(reachable=reachable), client
    )
    entry.runtime_data = SimpleNamespace(address=ADDRESS, coordinator=coordinator)
    return coordinator


def _seed(coordinator, *, assist_turn=None, aux=None) -> None:
    """Populate the coordinator's cached settings and pushed snapshot."""
    if assist_turn is not None:
        coordinator._apply_read("assist_turn", assist_turn)
    if aux is not None:
        coordinator._apply_read("auxiliary_locking", aux)
    coordinator.data = coordinator._build_snapshot(coordinator.bluetooth_manager.state)


async def _entities(hass, coordinator) -> list[AqaraU200SettingSwitch]:
    added: list[AqaraU200SettingSwitch] = []
    await switch_platform.async_setup_entry(
        hass, coordinator.config_entry, lambda new, *a, **k: added.extend(new)
    )
    return added


async def test_all_three_switches_are_created(hass) -> None:
    """The platform exposes exactly the three boolean-setting switches."""
    coordinator = _coordinator(hass, SwitchClient())
    entities = await _entities(hass, coordinator)

    keys = {e.translation_key for e in entities}
    assert keys == {"assist_turn", "auxiliary_close_to_lock", "auxiliary_resume_lock"}
    unique_ids = {e.unique_id for e in entities}
    assert unique_ids == {
        f"{ADDRESS}_assist_turn",
        f"{ADDRESS}_auxiliary_close_to_lock",
        f"{ADDRESS}_auxiliary_resume_lock",
    }
    for entity in entities:
        assert entity.device_info["manufacturer"] == "Aqara"
        assert entity.device_info["model"] == "U200"


async def test_is_on_reflects_coordinator_settings(hass) -> None:
    """Each switch's is_on mirrors the coordinator's read state."""
    coordinator = _coordinator(hass, SwitchClient())
    _seed(
        coordinator,
        assist_turn=True,
        aux={
            "touch_to_lock": False,
            "close_to_lock": True,
            "resume_lock": False,
            "any_unlock_lock": False,
        },
    )
    entities = {e.translation_key: e for e in await _entities(hass, coordinator)}

    assert entities["assist_turn"].is_on is True
    assert entities["auxiliary_close_to_lock"].is_on is True
    assert entities["auxiliary_resume_lock"].is_on is False


async def test_is_on_is_none_until_read(hass) -> None:
    """Before any read, every switch reports unknown (None), not a false OFF."""
    coordinator = _coordinator(hass, SwitchClient())
    entities = {e.translation_key: e for e in await _entities(hass, coordinator)}

    assert entities["assist_turn"].is_on is None
    assert entities["auxiliary_close_to_lock"].is_on is None
    assert entities["auxiliary_resume_lock"].is_on is None


async def test_assist_turn_switch_calls_the_setter(hass) -> None:
    """Turning the assist-turn switch on/off calls the coordinator setter."""
    client = SwitchClient(assist_turn=False)
    coordinator = _coordinator(hass, client)
    _seed(coordinator, assist_turn=False)
    entity = {e.translation_key: e for e in await _entities(hass, coordinator)}[
        "assist_turn"
    ]

    await entity.async_turn_on()
    assert client.assist_calls == [True]
    assert coordinator.data.last_operation == "set_assist_turn"

    await entity.async_turn_off()
    assert client.assist_calls == [True, False]


async def test_auxiliary_switch_read_modify_write_preserves_other_toggles(hass) -> None:
    """Flipping one aux toggle writes the FULL mask, preserving the others.

    touch_to_lock is already ON in the cached mask; turning ON the auto-lock-on-
    close switch must send the complete state with touch_to_lock still ON, not a
    lone close_to_lock bit that would silently disable touch_to_lock.
    """
    client = SwitchClient(
        aux={
            "touch_to_lock": True,
            "close_to_lock": False,
            "resume_lock": False,
            "any_unlock_lock": False,
        }
    )
    coordinator = _coordinator(hass, client)
    _seed(
        coordinator,
        aux={
            "touch_to_lock": True,
            "close_to_lock": False,
            "resume_lock": False,
            "any_unlock_lock": False,
        },
    )
    entity = {e.translation_key: e for e in await _entities(hass, coordinator)}[
        "auxiliary_close_to_lock"
    ]

    await entity.async_turn_on()

    assert client.aux_calls == [
        {
            "touch_to_lock": True,
            "close_to_lock": True,
            "resume_lock": False,
            "any_unlock_lock": False,
        }
    ]
    assert coordinator.data.last_operation == "set_auxiliary_close_to_lock"
    # The confirming re-read updated the shown state.
    assert entity.is_on is True


async def test_resume_lock_switch_flips_only_its_own_bit(hass) -> None:
    """The security-re-lock switch flips resume_lock and preserves the rest."""
    client = SwitchClient(
        aux={
            "touch_to_lock": False,
            "close_to_lock": True,
            "resume_lock": True,
            "any_unlock_lock": False,
        }
    )
    coordinator = _coordinator(hass, client)
    _seed(
        coordinator,
        aux={
            "touch_to_lock": False,
            "close_to_lock": True,
            "resume_lock": True,
            "any_unlock_lock": False,
        },
    )
    entity = {e.translation_key: e for e in await _entities(hass, coordinator)}[
        "auxiliary_resume_lock"
    ]

    await entity.async_turn_off()

    assert client.aux_calls == [
        {
            "touch_to_lock": False,
            "close_to_lock": True,
            "resume_lock": False,
            "any_unlock_lock": False,
        }
    ]
    assert coordinator.data.last_operation == "set_auxiliary_resume_lock"


async def test_auxiliary_switch_defaults_missing_cache_to_all_false(hass) -> None:
    """With no prior aux read, the write defaults the untouched toggles to OFF."""
    client = SwitchClient()
    coordinator = _coordinator(hass, client)
    entity = {e.translation_key: e for e in await _entities(hass, coordinator)}[
        "auxiliary_close_to_lock"
    ]

    await entity.async_turn_on()

    assert client.aux_calls == [
        {
            "touch_to_lock": False,
            "close_to_lock": True,
            "resume_lock": False,
            "any_unlock_lock": False,
        }
    ]
