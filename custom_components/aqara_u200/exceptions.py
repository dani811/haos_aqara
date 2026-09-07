"""Integration-owned exceptions for Aqara U200."""


class AqaraU200Error(Exception):
    """Base exception for the integration runtime boundary."""


class AqaraU200BluetoothUnavailableError(AqaraU200Error):
    """Raised when no connectable Home Assistant Bluetooth path can reach the lock."""


class AqaraU200AuthenticationError(AqaraU200Error):
    """Raised when Aqara rejects the configured cloud credentials."""


class AqaraU200OperationError(AqaraU200Error):
    """Raised for a sanitized control-operation failure."""


class AqaraU200PresenceRequiredError(AqaraU200Error):
    """Raised when a presence-gated op couldn't run because the keypad stayed asleep.

    The credential database and front-panel settings are fronted by the sleeping
    keypad panel; a read/write there needs it awake. When the wake window elapses
    with the panel still absent, this is raised instead of letting the write
    silently no-op (which would look like success).
    """
