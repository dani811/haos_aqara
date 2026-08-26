"""Config flow for Aqara U200 BLE."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, override

import voluptuous as vol
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_ADDRESS, CONF_PASSWORD
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .client import (
    AUTH_CONFIG_KEYS,
    async_resolve_device_id,
    async_validate_cloud_auth,
    is_invalid_auth_error,
)
from .const import (
    CONF_ACCOUNT,
    CONF_DEVICE_ID,
    CONF_POLL_HOURS,
    CONF_REALTIME_STATE,
    CONF_REGION,
    DEFAULT_POLL_HOURS,
    DEFAULT_REALTIME_STATE,
    DEFAULT_REGION,
    DOMAIN,
    MAX_POLL_HOURS,
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
    """Return the Aqara account fields (account + masked password).

    Only account + password are collected: aqara-ble bakes the app-global
    appid/appkey and generates the per-install phone_id/client_id, so the user
    never has to supply values captured from the app. ``include_all`` is kept for
    signature stability but no longer changes the fields.
    """
    del include_all
    return {
        vol.Required(CONF_ACCOUNT): _NON_EMPTY_TEXT,
        vol.Required(CONF_PASSWORD): _NON_EMPTY_PASSWORD,
    }


def _entry_data(user_input: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize non-password text; skip non-string fields (e.g. the toggle)."""
    return {
        key: value if key == CONF_PASSWORD else value.strip()
        for key, value in user_input.items()
        if isinstance(value, str)
    }


async def _async_auth_error(hass: HomeAssistant, data: Mapping[str, Any]) -> str | None:
    """Validate Aqara credentials and return a sanitized flow error key."""
    try:
        await async_validate_cloud_auth(hass, data)
    except Exception as err:  # noqa: BLE001 - map all library/network failures
        return "invalid_auth" if is_invalid_auth_error(err) else "cannot_connect"
    return None


async def _async_resolve_device_id(
    hass: HomeAssistant, data: Mapping[str, Any], mac: str
) -> tuple[str | None, str | None]:
    """Resolve the lock's device id from the account; return (device_id, error)."""
    try:
        return await async_resolve_device_id(hass, data, mac=mac), None
    except Exception:  # noqa: BLE001 - no lock found / ambiguous / transient
        return None, "no_device"


class AqaraU200ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle Aqara U200 configuration."""

    VERSION = 2

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovered_address: str | None = None
        self._discovered_name = "Aqara U200"

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> AqaraU200OptionsFlow:
        """Return the options flow (real-time BLE state toggle)."""
        return AqaraU200OptionsFlow()

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
            data[CONF_ADDRESS] = self._discovered_address
            error = await _async_auth_error(self.hass, data)
            if not error:
                device_id, error = await _async_resolve_device_id(
                    self.hass, data, self._discovered_address
                )
            if error:
                return self.async_show_form(
                    step_id="confirm",
                    data_schema=self._confirm_schema(),
                    errors={"base": error},
                    description_placeholders={"name": self._discovered_name},
                )
            data[CONF_DEVICE_ID] = device_id
            return self.async_create_entry(
                title=self._discovered_name,
                data=data,
                options={
                    CONF_REALTIME_STATE: user_input.get(
                        CONF_REALTIME_STATE, DEFAULT_REALTIME_STATE
                    )
                },
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
            error = await _async_auth_error(self.hass, data)
            if not error:
                device_id, error = await _async_resolve_device_id(
                    self.hass, data, address
                )
            if error:
                return self.async_show_form(
                    step_id="user",
                    data_schema=self._user_schema(),
                    errors={"base": error},
                )
            data[CONF_DEVICE_ID] = device_id
            return self.async_create_entry(
                title=f"Aqara U200 {address}",
                data=data,
                options={
                    CONF_REALTIME_STATE: user_input.get(
                        CONF_REALTIME_STATE, DEFAULT_REALTIME_STATE
                    )
                },
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
        """Return Bluetooth-discovery confirmation fields (account + password)."""
        return vol.Schema(
            {
                vol.Required(CONF_REGION, default=DEFAULT_REGION): vol.In(
                    SUPPORTED_REGIONS
                ),
                **_auth_schema(),
                vol.Required(
                    CONF_REALTIME_STATE, default=DEFAULT_REALTIME_STATE
                ): bool,
            }
        )

    @staticmethod
    def _user_schema() -> vol.Schema:
        """Return manual setup fields (address + account + password)."""
        return vol.Schema(
            {
                vol.Required(CONF_ADDRESS): _NON_EMPTY_TEXT,
                vol.Required(CONF_REGION, default=DEFAULT_REGION): vol.In(
                    SUPPORTED_REGIONS
                ),
                **_auth_schema(),
                vol.Required(
                    CONF_REALTIME_STATE, default=DEFAULT_REALTIME_STATE
                ): bool,
            }
        )


class AqaraU200OptionsFlow(OptionsFlow):
    """Options: opt in to a persistent real-time BLE state session."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Toggle the real-time BLE state session (off by default)."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        options = self.config_entry.options
        realtime = options.get(CONF_REALTIME_STATE, DEFAULT_REALTIME_STATE)
        poll_hours = options.get(CONF_POLL_HOURS, DEFAULT_POLL_HOURS)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_REALTIME_STATE, default=realtime): bool,
                    vol.Required(CONF_POLL_HOURS, default=poll_hours): NumberSelector(
                        NumberSelectorConfig(
                            min=0,
                            max=MAX_POLL_HOURS,
                            step=1,
                            unit_of_measurement="h",
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
        )
