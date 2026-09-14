"""Config flow for Aqara U200 BLE.

Setup offers three modes (a menu on both manual add and Bluetooth discovery):

- **cloud**: Aqara account + password; sessions log in through the cloud (current
  behaviour). The offline toggle in Options can later fetch the LTMK once.
- **local**: paste the lock's MAC + device id + 32-byte LTMK; the integration
  never contacts the cloud. For users who already hold the LTMK.
- **cloud_cutter**: account + password used ONCE at setup to fetch the device id +
  LTMK, then the entry operates fully local (offline on by default).
"""

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
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .client import (
    AUTH_CONFIG_KEYS,
    async_fetch_ltmk,
    async_resolve_device_id,
    async_validate_cloud_auth,
    is_invalid_auth_error,
    parse_ltmk,
)
from .const import (
    CONF_ACCOUNT,
    CONF_DEVICE_ID,
    CONF_KEYPAD_WAKE_SWITCH,
    CONF_LTMK,
    CONF_OFFLINE_MODE,
    CONF_POLL_HOURS,
    CONF_REALTIME_STATE,
    CONF_REGION,
    CONF_SETUP_MODE,
    DEFAULT_KEYPAD_WAKE_SWITCH,
    DEFAULT_OFFLINE_MODE,
    DEFAULT_POLL_HOURS,
    DEFAULT_REALTIME_STATE,
    DEFAULT_REGION,
    DOMAIN,
    MAX_POLL_HOURS,
    SETUP_MODE_CLOUD,
    SETUP_MODE_CLOUD_CUTTER,
    SETUP_MODE_LOCAL,
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
_MENU_OPTIONS = [SETUP_MODE_CLOUD, SETUP_MODE_LOCAL, SETUP_MODE_CLOUD_CUTTER]


def _auth_schema(*, include_all: bool = True) -> dict[vol.Marker, Any]:
    """Return the Aqara account fields (account + masked password).

    Only account + password are collected: aqara-ble bakes the app-global
    appid/appkey and generates the per-install phone_id/client_id.
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
        """Discovered lock: present the setup-mode menu."""
        if self._discovered_address is None:
            return self.async_abort(reason="discovery_info_missing")
        # The confirm menu title uses {name}; a menu still needs the placeholder or
        # the frontend throws a formatjs MISSING_VALUE for it.
        return self.async_show_menu(
            step_id="confirm",
            menu_options=_MENU_OPTIONS,
            description_placeholders={"name": self._discovered_name},
        )

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manual add: present the setup-mode menu."""
        return self.async_show_menu(step_id="user", menu_options=_MENU_OPTIONS)

    # ── mode: cloud ──────────────────────────────────────────────────────────
    async def async_step_cloud(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Cloud mode: account + password; per-operation cloud login."""
        return await self._async_cloud_step(SETUP_MODE_CLOUD, user_input)

    async def async_step_cloud_cutter(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Cloud-cutter mode: fetch the LTMK once, then operate fully local."""
        return await self._async_cloud_step(SETUP_MODE_CLOUD_CUTTER, user_input)

    async def _async_cloud_step(
        self, mode: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        """Shared cloud/cloud-cutter step (validate → resolve → maybe fetch LTMK)."""
        manual = self._discovered_address is None
        if user_input is not None:
            data = _entry_data(user_input)
            address = self._discovered_address or data[CONF_ADDRESS]
            if manual:
                await self.async_set_unique_id(address)
                self._abort_if_unique_id_configured()
            data[CONF_ADDRESS] = address
            error = await _async_auth_error(self.hass, data)
            # A device id the user typed in wins: it skips the account lookup
            # (``/dev/query``), which the Aqara cloud does not always answer.
            device_id: str | None = data.get(CONF_DEVICE_ID) or None
            if not error and device_id is None:
                device_id, error = await _async_resolve_device_id(
                    self.hass, data, address
                )
            ltmk_hex: str | None = None
            if not error and mode == SETUP_MODE_CLOUD_CUTTER:
                try:
                    assert device_id is not None
                    ltmk = await async_fetch_ltmk(self.hass, data, device_id)
                    ltmk_hex = ltmk.hex()
                except Exception:  # noqa: BLE001 - LTMK fetch failed
                    error = "ltmk_fetch"
            if error:
                return self.async_show_form(
                    step_id=mode,
                    data_schema=self._cloud_schema(manual),
                    errors={"base": error},
                    description_placeholders={"name": self._discovered_name},
                )
            data[CONF_DEVICE_ID] = device_id
            data[CONF_SETUP_MODE] = mode
            options: dict[str, Any] = {
                CONF_REALTIME_STATE: user_input.get(
                    CONF_REALTIME_STATE, DEFAULT_REALTIME_STATE
                )
            }
            if ltmk_hex is not None:
                data[CONF_LTMK] = ltmk_hex
                options[CONF_OFFLINE_MODE] = True
            title = self._discovered_name if not manual else f"Aqara U200 {address}"
            return self.async_create_entry(title=title, data=data, options=options)

        return self.async_show_form(
            step_id=mode,
            data_schema=self._cloud_schema(manual),
            description_placeholders={"name": self._discovered_name},
        )

    # ── mode: local ──────────────────────────────────────────────────────────
    async def async_step_local(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Local mode: MAC + device id + LTMK, no cloud contact at all."""
        manual = self._discovered_address is None
        errors: dict[str, str] = {}
        if user_input is not None:
            data = _entry_data(user_input)
            address = self._discovered_address or data[CONF_ADDRESS]
            try:
                ltmk_hex = parse_ltmk(data[CONF_LTMK]).hex()
            except ValueError:
                errors[CONF_LTMK] = "invalid_ltmk"
            if not errors:
                if manual:
                    await self.async_set_unique_id(address)
                    self._abort_if_unique_id_configured()
                entry_data = {
                    CONF_ADDRESS: address,
                    CONF_DEVICE_ID: data[CONF_DEVICE_ID],
                    CONF_LTMK: ltmk_hex,
                    CONF_SETUP_MODE: SETUP_MODE_LOCAL,
                }
                title = (
                    self._discovered_name if not manual else f"Aqara U200 {address}"
                )
                return self.async_create_entry(
                    title=title,
                    data=entry_data,
                    options={
                        CONF_REALTIME_STATE: user_input.get(
                            CONF_REALTIME_STATE, DEFAULT_REALTIME_STATE
                        ),
                        CONF_OFFLINE_MODE: True,
                    },
                )

        return self.async_show_form(
            step_id=SETUP_MODE_LOCAL,
            data_schema=self._local_schema(manual),
            errors=errors,
            description_placeholders={"name": self._discovered_name},
        )

    # ── reauth (cloud only) ──────────────────────────────────────────────────
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

    # ── schemas ──────────────────────────────────────────────────────────────
    def _cloud_schema(self, manual: bool) -> vol.Schema:
        """Cloud / cloud-cutter fields (address only when not discovered).

        ``device_id`` is optional: left blank the flow tries to auto-detect it
        from the account, but that lookup (``/dev/query``) is not always
        available, so the field lets the user paste the ``matt.<…>`` DID (visible
        in the Aqara app) to skip auto-detection entirely.
        """
        fields: dict[vol.Marker, Any] = {}
        if manual:
            fields[vol.Required(CONF_ADDRESS)] = _NON_EMPTY_TEXT
        fields[vol.Required(CONF_REGION, default=DEFAULT_REGION)] = vol.In(
            SUPPORTED_REGIONS
        )
        fields.update(_auth_schema())
        fields[vol.Optional(CONF_DEVICE_ID)] = _NON_EMPTY_TEXT
        fields[vol.Required(CONF_REALTIME_STATE, default=DEFAULT_REALTIME_STATE)] = bool
        return vol.Schema(fields)

    def _local_schema(self, manual: bool) -> vol.Schema:
        """Local fields: address (if not discovered) + device id + LTMK."""
        fields: dict[vol.Marker, Any] = {}
        if manual:
            fields[vol.Required(CONF_ADDRESS)] = _NON_EMPTY_TEXT
        fields[vol.Required(CONF_DEVICE_ID)] = _NON_EMPTY_TEXT
        fields[vol.Required(CONF_LTMK)] = _NON_EMPTY_TEXT
        fields[vol.Required(CONF_REALTIME_STATE, default=DEFAULT_REALTIME_STATE)] = bool
        return vol.Schema(fields)


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
        offline = options.get(CONF_OFFLINE_MODE, DEFAULT_OFFLINE_MODE)
        wake_switch = options.get(CONF_KEYPAD_WAKE_SWITCH, DEFAULT_KEYPAD_WAKE_SWITCH)
        # A pure-local entry (no cloud account) is always offline and cannot toggle it.
        is_local = CONF_ACCOUNT not in self.config_entry.data
        schema: dict[vol.Marker, Any] = {
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
        if not is_local:
            schema[vol.Required(CONF_OFFLINE_MODE, default=offline)] = bool
        schema[
            vol.Optional(
                CONF_KEYPAD_WAKE_SWITCH,
                description={"suggested_value": wake_switch or None},
            )
        ] = EntitySelector(EntitySelectorConfig(domain="switch"))
        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema))
