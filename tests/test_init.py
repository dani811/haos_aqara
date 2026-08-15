"""Tests for config-entry runtime lifecycle."""

from unittest.mock import AsyncMock, Mock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.aqara_u200 import async_setup_entry, async_unload_entry
from custom_components.aqara_u200.client import PendingAqaraU200Client
from custom_components.aqara_u200.const import CONF_DEVICE_ID, CONF_REGION, DOMAIN
from homeassistant.const import CONF_ADDRESS

ADDRESS = "AA:BB:CC:DD:EE:FF"


async def test_setup_builds_fail_closed_runtime_and_forwards_lock(hass) -> None:
    """Config entry should wire runtime without importing real protocol backend."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Aqara U200",
        data={
            CONF_ADDRESS: ADDRESS,
            CONF_DEVICE_ID: "device-1234",
            CONF_REGION: "EU",
        },
    )
    entry.add_to_hass(hass)

    cancel_discovery = Mock()
    cancel_unavailable = Mock()

    with (
        patch(
            "custom_components.aqara_u200.bluetooth.bluetooth.async_ble_device_from_address",
            return_value=None,
        ),
        patch(
            "custom_components.aqara_u200.bluetooth.bluetooth.async_register_callback",
            return_value=cancel_discovery,
        ),
        patch(
            "custom_components.aqara_u200.bluetooth.bluetooth.async_track_unavailable",
            return_value=cancel_unavailable,
        ),
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            new=AsyncMock(),
        ) as forward,
    ):
        assert await async_setup_entry(hass, entry) is True

    assert isinstance(entry.runtime_data.client, PendingAqaraU200Client)
    assert entry.runtime_data.coordinator.data.control_enabled is False
    forward.assert_awaited_once()


async def test_unload_unloads_platforms(hass) -> None:
    """Unload delegates to HA platform lifecycle."""
    entry = MockConfigEntry(domain=DOMAIN, data={})

    with patch.object(
        hass.config_entries,
        "async_unload_platforms",
        new=AsyncMock(return_value=True),
    ) as unload:
        assert await async_unload_entry(hass, entry) is True

    unload.assert_awaited_once()
