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
#: Background BLE poll interval, in hours. 0 = OFF (on-demand only, via the
#: Refresh button / real-time listener / operations). Configurable so a
#: battery-conscious user leaves it off and others can refresh periodically.
CONF_POLL_HOURS = "poll_hours"
DEFAULT_POLL_HOURS = 0
MAX_POLL_HOURS = 168
#: Real-time mode: hold ONE low-power session open this long, then reconnect
#: (an actuation preempts it instantly, so it is not a latency bound). Short gap
#: between reconnects to yield the connection.
REALTIME_SESSION_SECONDS = 3600.0
REALTIME_GAP_SECONDS = 2.0

#: Battery is read over BLE (GET_BATTERY_INFO 0xde). A BLE read is costly and the
#: charge moves slowly, so poll it infrequently: once shortly after startup, then
#: every few hours.
BATTERY_POLL_SECONDS = 6 * 3600.0
BATTERY_INITIAL_DELAY_SECONDS = 30.0
#: Until every value (battery + settings) has been read at least once, retry on
#: this short interval instead of waiting the full poll period.
BATTERY_RETRY_SECONDS = 300.0
#: One value is read per poll cycle (rotating), because HA's Bluetooth proxy only
#: reliably serves one connect+read per burst to this lock. While any value is
#: still unread, rotate fast; once all have landed, rotate slowly (each of the ~5
#: values then refreshes about every 5x this).
ROTATION_FILL_SECONDS = 45.0
ROTATION_POLL_SECONDS = 3600.0
#: The U200 rejects an immediate reconnect (~5 s). Space every BLE read in a poll
#: cycle (state, battery, and each setting) by this much so back-to-back reads
#: don't fail on the reconnect rejection.
BLE_READ_GAP_SECONDS = 8.0
#: HA's Bluetooth proxy occasionally drops the lock's notify response (the read
#: times out and returns None). Retry each read up to this many times.
BLE_READ_ATTEMPTS = 3

DEFAULT_REGION = "EU"
SUPPORTED_REGIONS = ("EU", "US", "CN")

AUTH_SERVICE_UUID = "0000fcb9-0000-1000-8000-00805f9b34fb"

FRONTEND_URL_PATH = "/aqara_u200_frontend"
FRONTEND_MODULE_URL = f"{FRONTEND_URL_PATH}/aqara-u200-card.js"
