"""Protocol-independent client boundary for Aqara U200."""

from typing import Protocol

from .exceptions import AqaraU200BackendNotReadyError


class AqaraU200Client(Protocol):
    """Contract consumed by the Home Assistant runtime.

    Real protocol/session/KDF details stay behind an adapter implementing this
    contract. Entities must never depend directly on aqara-u200-ble internals.
    """

    @property
    def control_enabled(self) -> bool:
        """Return whether real lock control is safe and enabled."""
        ...

    async def async_lock(self) -> None:
        """Lock the device."""
        ...

    async def async_unlock(self) -> None:
        """Unlock the device."""
        ...


class PendingAqaraU200Client:
    """Fail-closed client used until the real protocol adapter is ready."""

    @property
    def control_enabled(self) -> bool:
        """Real control is intentionally disabled in this implementation."""
        return False

    async def async_lock(self) -> None:
        """Reject lock without performing BLE or cloud I/O."""
        raise AqaraU200BackendNotReadyError(
            "Aqara U200 control backend is not enabled yet"
        )

    async def async_unlock(self) -> None:
        """Reject unlock without performing BLE or cloud I/O."""
        raise AqaraU200BackendNotReadyError(
            "Aqara U200 control backend is not enabled yet"
        )
