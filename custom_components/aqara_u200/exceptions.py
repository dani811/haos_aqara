"""Integration-owned exceptions for Aqara U200."""


class AqaraU200Error(Exception):
    """Base exception for the integration runtime boundary."""


class AqaraU200BackendNotReadyError(AqaraU200Error):
    """Raised when real control has deliberately not been enabled yet."""


class AqaraU200BluetoothUnavailableError(AqaraU200Error):
    """Raised when no connectable Home Assistant Bluetooth path can reach the lock."""


class AqaraU200AuthenticationError(AqaraU200Error):
    """Raised when a future protocol adapter reports authentication failure."""


class AqaraU200OperationError(AqaraU200Error):
    """Raised for a sanitized control-operation failure."""
