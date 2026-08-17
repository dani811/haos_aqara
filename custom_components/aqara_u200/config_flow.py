"""Config flow for Aqara U200 BLE."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, override

import voluptuous as vol
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .client import AUTH_CONFIG_KEYS, async_validate_cloud_auth, is_invalid_auth_error
from .const import (
    CONF_ACCOUNT,
    CONF_APP_ID,
    CONF_APP_KEY,
    CONF_CLIENT_ID,
    CONF_DEVICE_ID,
    CONF_DISTRICT,
    CONF_PHONE_ID,
    CONF_REGION,
    DEFAULT_DISTRICT,
    DEFAULT_REGION,
    DOMAIN,
    SUPPORTED_REGIONS,
)

_NON_EMPTY_TEXT = vol.All(str, vol.Strip, vol.Length(min=1))
_PASSWORD_SELECTOR = TextSelector(
    TextSelectorConfig(
        type=TextSelectorType.PASSWORD,
        autocomplete="current-password",
    )
)
_NON_EMPTY_PASSWORD = vol.All(_PASSWORD_SELECTOR, vol.Length(min=1))


def _auth_schema(*, include_all: bool = True) -> dict[vol.Marker, Any]:
    """Return auth fields, masking the password in the frontend."""
    fields: dict[vol.Marker, Any] = {
        vol.Required(CONF_ACCOUNT): _NON_EMPTY_TEXT,
        vol.Required(CONF_PASSWORD): _NON_EMPTY_PASSWORD,
    }
    if include_all:
        fields.update(
            {
                vol.Required(CONF_APP_ID): _NON_EMPTY_TEXT,
                vol.Required(CONF_APP_KEY): _NON_EMPTY_PASSWORD,
                vol.Required(CONF_CLIENT_ID): _NON_EMPTY_TEXT,
                vol.Required(CONF_PHONE_ID): _NON_EMPTY_TEXT,
                vol.Required(CONF_DISTRICT, default=DEFAULT_DISTRICT): _NON_EMPTY_TEXT,
            }
        )
    return fields


def _entry_data(user_input: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize non-password text while preserving password bytes exactly."""
    return {
        key: value if key == CONF_PASSWORD else value.strip()
        for key, value in user_input.items()
    }


async def _async_auth_error(hass: HomeAssistant, data: Mapping[str, Any]) -> str | None:
    """Validate Aqara credentials and return a sanitized flow error key."""
    try:
        await async_validate_cloud_auth(hass, data)
    except Exception as err:  # noqa: BLE001 - map all library/network failures
        return "invalid_auth" if is_invalid_auth_error(err) else "cannot_connect"
    return None


class AqaraU200ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle Aqara U200 configuration."""

    VERSION = 2

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovered_address: str | None = None
        self._discovered_name = "Aqara U200"

    @override
    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle discovery through Home Assistant Bluetooth."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured(
            updates={CONF_ADDRESS: discovery_info.address}
        )

        self._discovered_address = discovery_info.address
        self._discovered_name = discovery_info.name or "Aqara U200"
        self.context["title_placeholders"] = {"name": self._discovered_name}
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm a discovered lock and collect its Aqara device id."""
        if self._discovered_address is None:
            return self.async_abort(reason="discovery_info_missing")

        if user_input is not None:
            data = _entry_data(user_input)
            data.update(
                {
                    CONF_ADDRESS: self._discovered_address,
                    CONF_DEVICE_ID: data[CONF_DEVICE_ID],
                    CONF_REGION: data[CONF_REGION],
                }
            )
            if error := await _async_auth_error(self.hass, data):
                return self.async_show_form(
                    step_id="confirm",
                    data_schema=self._confirm_schema(),
                    errors={"base": error},
                    description_placeholders={"name": self._discovered_name},
                )
            return self.async_create_entry(
                title=self._discovered_name,
                data=data,
            )

        return self.async_show_form(
            step_id="confirm",
            data_schema=self._confirm_schema(),
            description_placeholders={"name": self._discovered_name},
        )

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle manual setup."""
        if user_input is not None:
            data = _entry_data(user_input)
            address = data[CONF_ADDRESS]
            await self.async_set_unique_id(address)
            self._abort_if_unique_id_configured()
            if error := await _async_auth_error(self.hass, data):
                return self.async_show_form(
                    step_id="user",
                    data_schema=self._user_schema(),
                    errors={"base": error},
                )
            return self.async_create_entry(
                title=f"Aqara U200 {address}",
                data=data,
            )

        return self.async_show_form(
            step_id="user",
            data_schema=self._user_schema(),
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start credential reauthentication."""
        del entry_data
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Validate and replace cloud credentials without exposing stored secrets."""
        entry = self._get_reauth_entry()
        missing = any(key not in entry.data for key in AUTH_CONFIG_KEYS)
        schema = vol.Schema(_auth_schema(include_all=missing))
        errors: dict[str, str] = {}

        if user_input is not None:
            updates = _entry_data(user_input)
            candidate = {**entry.data, **updates}
            if error := await _async_auth_error(self.hass, candidate):
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates=updates,
                )

        suggested = {
            CONF_ACCOUNT: entry.data.get(CONF_ACCOUNT, ""),
        }
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
        )

    @staticmethod
    def _confirm_schema() -> vol.Schema:
        """Return Bluetooth-discovery confirmation fields."""
        return vol.Schema(
            {
                vol.Required(CONF_DEVICE_ID): _NON_EMPTY_TEXT,
                vol.Required(CONF_REGION, default=DEFAULT_REGION): vol.In(
                    SUPPORTED_REGIONS
                ),
                **_auth_schema(),
            }
        )

    @staticmethod
    def _user_schema() -> vol.Schema:
        """Return manual setup fields."""
        return vol.Schema(
            {
                vol.Required(CONF_ADDRESS): _NON_EMPTY_TEXT,
                vol.Required(CONF_DEVICE_ID): _NON_EMPTY_TEXT,
                vol.Required(CONF_REGION, default=DEFAULT_REGION): vol.In(
                    SUPPORTED_REGIONS
                ),
                **_auth_schema(),
            }
        )
