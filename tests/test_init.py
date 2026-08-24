"""Tests for config-entry runtime lifecycle."""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.const import CONF_ADDRESS, CONF_PASSWORD
from homeassistant.exceptions import ConfigEntryAuthFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.aqara_u200 import async_setup_entry, async_unload_entry
from custom_components.aqara_u200.client import AqaraU200BleClientAdapter
from custom_components.aqara_u200.const import (
    CONF_ACCOUNT,
    CONF_DEVICE_ID,
    CONF_REGION,
    DOMAIN,
)
from custom_components.aqara_u200.lock import (
    async_setup_entry as async_setup_lock_entry,
)

ADDRESS = "AA:BB:CC:DD:EE:FF"
AUTH_DATA = {
    CONF_ACCOUNT: "account@example.com",
    CONF_PASSWORD: "password",
}


async def test_setup_builds_real_runtime_and_forwards_lock(hass) -> None:
    """Config entry should wire the released protocol adapter."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Aqara U200",
        data={
            CONF_ADDRESS: ADDRESS,
            CONF_DEVICE_ID: "device-1234",
            CONF_REGION: "EU",
            **AUTH_DATA,
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

    assert isinstance(entry.runtime_data.client, AqaraU200BleClientAdapter)
    assert entry.runtime_data.coordinator.data.control_enabled is True
    forward.assert_awaited_once()


async def test_setup_requests_reauth_for_legacy_entry_without_credentials(hass) -> None:
    """An entry from the pending-backend revision fails into HA reauth cleanly."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Aqara U200",
        data={
            CONF_ADDRESS: ADDRESS,
            CONF_DEVICE_ID: "device-legacy",
            CONF_REGION: "EU",
        },
    )
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.aqara_u200.bluetooth.bluetooth.async_ble_device_from_address",
            return_value=None,
        ),
        pytest.raises(ConfigEntryAuthFailed) as error,
    ):
        await async_setup_entry(hass, entry)

    assert "credentials" in str(error.value)


async def test_runtime_and_lock_platform_integrate(hass) -> None:
    """Runtime wiring and native entity expose confirmed operations when reachable."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Aqara U200",
        data={
            CONF_ADDRESS: ADDRESS,
            CONF_DEVICE_ID: "device-5678",
            CONF_REGION: "EU",
            **AUTH_DATA,
        },
    )
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.aqara_u200.bluetooth.bluetooth.async_ble_device_from_address",
            return_value=object(),
        ),
        patch(
            "custom_components.aqara_u200.bluetooth.bluetooth.async_register_callback",
            return_value=Mock(),
        ),
        patch(
            "custom_components.aqara_u200.bluetooth.bluetooth.async_track_unavailable",
            return_value=Mock(),
        ),
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            new=AsyncMock(),
        ),
    ):
        assert await async_setup_entry(hass, entry) is True

    entities = []
    await async_setup_lock_entry(hass, entry, entities.extend)

    assert len(entities) == 1
    entity = entities[0]
    assert entity.coordinator is entry.runtime_data.coordinator
    assert entity.unique_id == f"{ADDRESS}_lock"
    assert entry.runtime_data.coordinator.data.reachable is True
    assert entry.runtime_data.coordinator.data.control_enabled is True
    assert entity.available is True


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
