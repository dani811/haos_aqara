"""Constants for the Aqara U200 integration."""

DOMAIN = "aqara_u200"

# The library only needs account + password (it bakes appid/appkey and
# generates phone_id/client_id), so those are no longer collected or stored.
CONF_ACCOUNT = "account"
CONF_DEVICE_ID = "device_id"
CONF_REGION = "region"

# Opt-in: keep a persistent BLE session listening for real-time state (ff62),
# including external changes (Matter/key/keypad). Costs extra lock battery.
CONF_REALTIME_STATE = "realtime_state"
DEFAULT_REALTIME_STATE = False
#: Real-time mode: hold ONE low-power session open this long, then reconnect
#: (an actuation preempts it instantly, so it is not a latency bound). Short gap
#: between reconnects to yield the connection.
REALTIME_SESSION_SECONDS = 3600.0
REALTIME_GAP_SECONDS = 2.0

DEFAULT_REGION = "EU"
SUPPORTED_REGIONS = ("EU", "US", "CN")

AUTH_SERVICE_UUID = "0000fcb9-0000-1000-8000-00805f9b34fb"

FRONTEND_URL_PATH = "/aqara_u200_frontend"
FRONTEND_MODULE_URL = f"{FRONTEND_URL_PATH}/aqara-u200-card.js"
