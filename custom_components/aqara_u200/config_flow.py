"""Config flow for Aqara U200 BLE."""

from __future__ import annotations

from typing import Any, override

import voluptuous as vol

from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS

from .const import (
    CONF_DEVICE_ID,
    CONF_REGION,
    DEFAULT_REGION,
    DOMAIN,
    SUPPORTED_REGIONS,
)


class AqaraU200ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle Aqara U200 configuration."""

    VERSION = 1

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
            return self.async_create_entry(
                title=self._discovered_name,
                data={
                    CONF_ADDRESS: self._discovered_address,
                    CONF_DEVICE_ID: user_input[CONF_DEVICE_ID].strip(),
                    CONF_REGION: user_input[CONF_REGION],
                },
            )

        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE_ID): vol.All(str, vol.Strip),
                    vol.Required(CONF_REGION, default=DEFAULT_REGION): vol.In(
                        SUPPORTED_REGIONS
                    ),
                }
            ),
            description_placeholders={"name": self._discovered_name},
        )

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle manual setup."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS].strip()
            await self.async_set_unique_id(address)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=f"Aqara U200 {address}",
                data={
                    CONF_ADDRESS: address,
                    CONF_DEVICE_ID: user_input[CONF_DEVICE_ID].strip(),
                    CONF_REGION: user_input[CONF_REGION],
                },
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.All(str, vol.Strip),
                    vol.Required(CONF_DEVICE_ID): vol.All(str, vol.Strip),
                    vol.Required(CONF_REGION, default=DEFAULT_REGION): vol.In(
                        SUPPORTED_REGIONS
                    ),
                }
            ),
        )
