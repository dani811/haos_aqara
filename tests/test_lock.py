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


async def test_pending_backend_keeps_entity_unavailable(hass) -> None:
    """Entity may exist, but it must fail closed until real adapter is ready."""
    entry = MockConfigEntry(
        domain="aqara_u200",
        title="Aqara U200",
        data={},
    )
    coordinator = AqaraU200Coordinator(
        hass,
        entry,
        FakeBluetoothManager(reachable=True),
        PendingAqaraU200Client(),
    )
    entry.runtime_data = SimpleNamespace(address=ADDRESS, coordinator=coordinator)

    entity = AqaraU200Lock(entry, coordinator)

    assert entity.available is False
    assert entity.is_locked is None
    assert entity.unique_id == f"{ADDRESS}_lock"
