"""Tests for explicit Aqara cloud credential configuration and reauth."""

from unittest.mock import AsyncMock, patch

from aqara_u200_ble import CloudServiceError
from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_USER
from homeassistant.const import CONF_ADDRESS, CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.aqara_u200.config_flow import AqaraU200ConfigFlow
from custom_components.aqara_u200.const import (
    CONF_ACCOUNT,
    CONF_APP_ID,
    CONF_APP_KEY,
    CONF_CLIENT_ID,
    CONF_DEVICE_ID,
    CONF_DISTRICT,
    CONF_PHONE_ID,
    CONF_REGION,
    DOMAIN,
)

ADDRESS = "AA:BB:CC:DD:EE:FF"
USER_INPUT = {
    CONF_ADDRESS: ADDRESS,
    CONF_DEVICE_ID: "device-1234",
    CONF_REGION: "EU",
    CONF_ACCOUNT: "account@example.com",
    CONF_PASSWORD: "password",
    CONF_APP_ID: "app-id",
    CONF_APP_KEY: "app-key",
    CONF_CLIENT_ID: "client-id",
    CONF_PHONE_ID: "phone-id",
    CONF_DISTRICT: "ES",
}


async def test_user_flow_validates_and_stores_explicit_credentials(hass) -> None:
    """Production auth data comes from the config entry, never environment vars."""
    flow = AqaraU200ConfigFlow()
    flow.hass = hass
    flow.context = {"source": SOURCE_USER}

    with patch(
        "custom_components.aqara_u200.config_flow.async_validate_cloud_auth",
        new=AsyncMock(),
    ) as validate:
        result = await flow.async_step_user(dict(USER_INPUT))

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == USER_INPUT
    validate.assert_awaited_once_with(hass, USER_INPUT)


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
