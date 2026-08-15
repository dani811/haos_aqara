"""Tests for the native lock entity."""

from types import SimpleNamespace

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.aqara_u200.bluetooth import AqaraU200BluetoothState
from custom_components.aqara_u200.client import PendingAqaraU200Client
from custom_components.aqara_u200.coordinator import AqaraU200Coordinator
from custom_components.aqara_u200.lock import AqaraU200Lock

ADDRESS = "AA:BB:CC:DD:EE:FF"


class FakeBluetoothManager:
    def __init__(self, reachable: bool) -> None:
        self.state = AqaraU200BluetoothState(reachable=reachable)


class EnabledClient:
    """Protocol-free enabled fake used to test the HA entity contract."""

    control_enabled = True

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def async_lock(self) -> None:
        self.calls.append("lock")

    async def async_unlock(self) -> None:
        self.calls.append("unlock")


def _entity(hass, *, reachable: bool, client):
    entry = MockConfigEntry(
        domain="aqara_u200",
        title="Aqara U200",
        data={},
    )
    coordinator = AqaraU200Coordinator(
        hass,
        entry,
        FakeBluetoothManager(reachable=reachable),
        client,
    )
    entry.runtime_data = SimpleNamespace(address=ADDRESS, coordinator=coordinator)
    return AqaraU200Lock(entry, coordinator), coordinator


async def test_pending_backend_keeps_entity_unavailable(hass) -> None:
    """Entity may exist, but it must fail closed until real adapter is ready."""
    entity, _ = _entity(
        hass, reachable=True, client=PendingAqaraU200Client()
    )

    assert entity.available is False
    assert entity.is_locked is None
    assert entity.unique_id == f"{ADDRESS}_lock"
    assert entity.device_info["manufacturer"] == "Aqara"
    assert entity.device_info["model"] == "U200"


async def test_unreachable_device_keeps_enabled_entity_unavailable(hass) -> None:
    """An enabled backend must still fail closed when HA cannot reach BLE."""
    entity, _ = _entity(hass, reachable=False, client=EnabledClient())

    assert entity.available is False


async def test_reachable_enabled_entity_delegates_actions(hass) -> None:
    """The native entity delegates only through the integration client boundary."""
    client = EnabledClient()
    entity, _ = _entity(hass, reachable=True, client=client)

    assert entity.available is True

    await entity.async_unlock()
    await entity.async_lock()

    assert client.calls == ["unlock", "lock"]
