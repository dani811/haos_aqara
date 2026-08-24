"""Constants for the Aqara U200 integration."""

DOMAIN = "aqara_u200"

# The library only needs account + password (it bakes appid/appkey and
# generates phone_id/client_id), so those are no longer collected or stored.
CONF_ACCOUNT = "account"
CONF_DEVICE_ID = "device_id"
CONF_REGION = "region"

DEFAULT_REGION = "EU"
SUPPORTED_REGIONS = ("EU", "US", "CN")

AUTH_SERVICE_UUID = "0000fcb9-0000-1000-8000-00805f9b34fb"

FRONTEND_URL_PATH = "/aqara_u200_frontend"
FRONTEND_MODULE_URL = f"{FRONTEND_URL_PATH}/aqara-u200-card.js"
