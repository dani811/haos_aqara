"""Tests for explicit Aqara cloud credential configuration and reauth."""

from unittest.mock import AsyncMock, patch

from aqara_ble import CloudServiceError
from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_USER
from homeassistant.const import CONF_ADDRESS, CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.aqara_u200.config_flow import AqaraU200ConfigFlow
from custom_components.aqara_u200.const import (
    CONF_ACCOUNT,
    CONF_DEVICE_ID,
    CONF_REGION,
    DOMAIN,
)

ADDRESS = "AA:BB:CC:DD:EE:FF"
RESOLVED_DEVICE_ID = "matt.resolved0000"
USER_INPUT = {
    CONF_ADDRESS: ADDRESS,
    CONF_REGION: "EU",
    CONF_ACCOUNT: "account@example.com",
    CONF_PASSWORD: "password",
}


async def test_user_flow_validates_and_auto_resolves_device_id(hass) -> None:
    """The user supplies only account + password; the device id is resolved."""
    flow = AqaraU200ConfigFlow()
    flow.hass = hass
    flow.context = {"source": SOURCE_USER}

    with (
        patch(
            "custom_components.aqara_u200.config_flow.async_validate_cloud_auth",
            new=AsyncMock(),
        ) as validate,
        patch(
            "custom_components.aqara_u200.config_flow.async_resolve_device_id",
            new=AsyncMock(return_value=RESOLVED_DEVICE_ID),
        ) as resolve,
    ):
        result = await flow.async_step_user(dict(USER_INPUT))

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {**USER_INPUT, CONF_DEVICE_ID: RESOLVED_DEVICE_ID}
    validate.assert_awaited_once()
    resolve.assert_awaited_once()


async def test_user_flow_maps_invalid_auth_without_raw_details(hass) -> None:
    """Aqara rejection details are reduced to a translated flow error key."""
    flow = AqaraU200ConfigFlow()
    flow.hass = hass
    flow.context = {"source": SOURCE_USER}
    error = CloudServiceError(
        code=810,
        message="raw-password-detail",
        endpoint="raw-endpoint",
    )

    with patch(
        "custom_components.aqara_u200.config_flow.async_validate_cloud_auth",
        new=AsyncMock(side_effect=error),
    ):
        result = await flow.async_step_user(dict(USER_INPUT))

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert "raw" not in repr(result["errors"])


async def test_reauth_upgrades_entry_missing_cloud_credentials(hass) -> None:
    """Entries created by the pending-backend branch can collect required auth."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Aqara U200",
        unique_id=ADDRESS,
        data={
            CONF_ADDRESS: ADDRESS,
            CONF_DEVICE_ID: "device-1234",
            CONF_REGION: "EU",
        },
    )
    entry.add_to_hass(hass)
    flow = AqaraU200ConfigFlow()
    flow.hass = hass
    flow.context = {"source": SOURCE_REAUTH, "entry_id": entry.entry_id}
    auth_input = {
        key: value
        for key, value in USER_INPUT.items()
        if key not in (CONF_ADDRESS, CONF_DEVICE_ID, CONF_REGION)
    }

    with (
        patch(
            "custom_components.aqara_u200.config_flow.async_validate_cloud_auth",
            new=AsyncMock(),
        ),
        patch.object(
            hass.config_entries, "async_reload", new=AsyncMock(return_value=True)
        ),
    ):
        result = await flow.async_step_reauth_confirm(auth_input)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    for key, value in auth_input.items():
        assert entry.data[key] == value
