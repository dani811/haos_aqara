"""Tests for the Aqara U200 config flow: cloud / local / cloud-cutter + reauth."""

from unittest.mock import AsyncMock, patch

from aqara_ble import CloudServiceError
from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_USER
from homeassistant.const import CONF_ADDRESS, CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.aqara_u200.client import build_cloud_auth
from custom_components.aqara_u200.config_flow import AqaraU200ConfigFlow
from custom_components.aqara_u200.const import (
    CONF_ACCOUNT,
    CONF_DEVICE_ID,
    CONF_DISTRICT,
    CONF_LTMK,
    CONF_OFFLINE_MODE,
    CONF_REGION,
    CONF_SETUP_MODE,
    DOMAIN,
)

ADDRESS = "AA:BB:CC:DD:EE:FF"
RESOLVED_DEVICE_ID = "matt.resolved0000"
TEST_LTMK_HEX = "00" * 32  # synthetic 32-byte key (no real secret in the repo)
USER_INPUT = {
    CONF_ADDRESS: ADDRESS,
    CONF_REGION: "EU",
    CONF_DISTRICT: "CZ",
    CONF_ACCOUNT: "account@example.com",
    CONF_PASSWORD: "password",
}


def _flow(hass, source=SOURCE_USER):
    flow = AqaraU200ConfigFlow()
    flow.hass = hass
    flow.context = {"source": source}
    return flow


async def test_user_step_shows_mode_menu(hass) -> None:
    """Manual add offers the cloud / local / cloud-cutter menu."""
    result = await _flow(hass).async_step_user()
    assert result["type"] is FlowResultType.MENU
    assert set(result["menu_options"]) == {"cloud", "local", "cloud_cutter"}


async def test_cloud_flow_validates_and_auto_resolves_device_id(hass) -> None:
    """Cloud mode: account + password; the device id is resolved from the account."""
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
        result = await _flow(hass).async_step_cloud(dict(USER_INPUT))

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        **USER_INPUT,
        CONF_DEVICE_ID: RESOLVED_DEVICE_ID,
        CONF_SETUP_MODE: "cloud",
    }
    assert CONF_LTMK not in result["data"]
    validate.assert_awaited_once()
    resolve.assert_awaited_once()


async def test_cloud_flow_uses_manual_device_id_and_skips_resolution(hass) -> None:
    """A device id typed in cloud mode is used as-is; auto-resolution is skipped."""
    with (
        patch(
            "custom_components.aqara_u200.config_flow.async_validate_cloud_auth",
            new=AsyncMock(),
        ),
        patch(
            "custom_components.aqara_u200.config_flow.async_resolve_device_id",
            new=AsyncMock(return_value=RESOLVED_DEVICE_ID),
        ) as resolve,
    ):
        result = await _flow(hass).async_step_cloud(
            {**USER_INPUT, CONF_DEVICE_ID: "matt.manual0000"}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_DEVICE_ID] == "matt.manual0000"
    resolve.assert_not_awaited()


async def test_cloud_flow_maps_invalid_auth_without_raw_details(hass) -> None:
    """Aqara rejection details are reduced to a translated flow error key."""
    error = CloudServiceError(code=810, message="raw-password", endpoint="raw-endpoint")
    with patch(
        "custom_components.aqara_u200.config_flow.async_validate_cloud_auth",
        new=AsyncMock(side_effect=error),
    ):
        result = await _flow(hass).async_step_cloud(dict(USER_INPUT))

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert "raw" not in repr(result["errors"])


async def test_cloud_flow_logs_only_sanitized_error_metadata(hass, caplog) -> None:
    """Unexpected cloud failures are diagnosable without leaking exception text."""
    secret = "account@example.com:super-secret-password"
    with patch(
        "custom_components.aqara_u200.config_flow.async_validate_cloud_auth",
        new=AsyncMock(side_effect=RuntimeError(secret)),
    ):
        result = await _flow(hass).async_step_cloud(dict(USER_INPUT))

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert "RuntimeError" in caplog.text
    assert secret not in caplog.text
    assert "super-secret-password" not in caplog.text


def test_build_cloud_auth_uses_account_country_and_keeps_legacy_fallback() -> None:
    """The real account country reaches aqara-ble; old entries still default to ES."""
    auth = build_cloud_auth(USER_INPUT)
    assert auth.region == "EU"
    assert auth.district == "CZ"

    legacy = build_cloud_auth(
        {
            CONF_ACCOUNT: USER_INPUT[CONF_ACCOUNT],
            CONF_PASSWORD: USER_INPUT[CONF_PASSWORD],
            CONF_REGION: "EU",
        }
    )
    assert legacy.district == "ES"


async def test_cloud_cutter_fetches_ltmk_and_stores_it_offline(hass) -> None:
    """Cloud-cutter mode fetches the LTMK once and stores it; offline on by default."""
    with (
        patch(
            "custom_components.aqara_u200.config_flow.async_validate_cloud_auth",
            new=AsyncMock(),
        ),
        patch(
            "custom_components.aqara_u200.config_flow.async_resolve_device_id",
            new=AsyncMock(return_value=RESOLVED_DEVICE_ID),
        ),
        patch(
            "custom_components.aqara_u200.config_flow.async_fetch_ltmk",
            new=AsyncMock(return_value=bytes.fromhex(TEST_LTMK_HEX)),
        ) as fetch,
    ):
        result = await _flow(hass).async_step_cloud_cutter(dict(USER_INPUT))

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_LTMK] == TEST_LTMK_HEX
    assert result["data"][CONF_SETUP_MODE] == "cloud_cutter"
    assert result["options"][CONF_OFFLINE_MODE] is True
    fetch.assert_awaited_once()


async def test_cloud_cutter_maps_ltmk_fetch_failure(hass) -> None:
    """A failed LTMK fetch surfaces the ltmk_fetch error, not a crash."""
    with (
        patch(
            "custom_components.aqara_u200.config_flow.async_validate_cloud_auth",
            new=AsyncMock(),
        ),
        patch(
            "custom_components.aqara_u200.config_flow.async_resolve_device_id",
            new=AsyncMock(return_value=RESOLVED_DEVICE_ID),
        ),
        patch(
            "custom_components.aqara_u200.config_flow.async_fetch_ltmk",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ),
    ):
        result = await _flow(hass).async_step_cloud_cutter(dict(USER_INPUT))

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "ltmk_fetch"}


async def test_local_flow_no_cloud(hass) -> None:
    """Local mode stores address + device id + LTMK, no cloud credentials."""
    result = await _flow(hass).async_step_local(
        {
            CONF_ADDRESS: ADDRESS,
            CONF_DEVICE_ID: RESOLVED_DEVICE_ID,
            CONF_LTMK: TEST_LTMK_HEX,
        }
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_ADDRESS: ADDRESS,
        CONF_DEVICE_ID: RESOLVED_DEVICE_ID,
        CONF_LTMK: TEST_LTMK_HEX,
        CONF_SETUP_MODE: "local",
    }
    assert CONF_ACCOUNT not in result["data"]
    assert CONF_PASSWORD not in result["data"]
    assert result["options"][CONF_OFFLINE_MODE] is True


async def test_local_flow_rejects_bad_ltmk(hass) -> None:
    """A malformed LTMK yields the invalid_ltmk field error."""
    result = await _flow(hass).async_step_local(
        {
            CONF_ADDRESS: ADDRESS,
            CONF_DEVICE_ID: RESOLVED_DEVICE_ID,
            CONF_LTMK: "not-hex",
        }
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_LTMK: "invalid_ltmk"}


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
    flow = _flow(hass, SOURCE_REAUTH)
    flow.context["entry_id"] = entry.entry_id
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
