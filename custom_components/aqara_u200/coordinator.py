"""Runtime coordinator for Aqara U200."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .bluetooth import AqaraU200BluetoothManager, AqaraU200BluetoothState
from .client import AqaraU200Client
from .const import DOMAIN
from .exceptions import (
    AqaraU200AuthenticationError,
    AqaraU200BluetoothUnavailableError,
    AqaraU200Error,
    AqaraU200OperationError,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class AqaraU200RuntimeSnapshot:
    """Safe runtime state pushed to Home Assistant entities."""

    reachable: bool
    last_seen: datetime | None
    rssi: int | None
    control_enabled: bool
    operation_in_progress: bool
    last_operation: str | None
    last_error_type: str | None
    #: Optimistic bolt position after the last confirmed actuation (None = unknown).
    is_locked: bool | None = None


class AqaraU200Coordinator(DataUpdateCoordinator[AqaraU200RuntimeSnapshot]):
    """Coordinate Bluetooth reachability and serialized HA operations."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        bluetooth_manager: AqaraU200BluetoothManager,
        client: AqaraU200Client,
    ) -> None:
        """Initialize the push coordinator."""
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            config_entry=entry,
            always_update=False,
        )
        self.bluetooth_manager = bluetooth_manager
        self.client = client
        self._entry = entry
        self._operation_lock = asyncio.Lock()
        self._operation_in_progress = False
        self._last_operation: str | None = None
        self._last_error_type: str | None = None
        self._is_locked: bool | None = None
        self.data = self._build_snapshot(bluetooth_manager.state)

    @callback
    def async_handle_bluetooth_state(self, state: AqaraU200BluetoothState) -> None:
        """Push a Home Assistant Bluetooth state change to entities."""
        self.async_set_updated_data(self._build_snapshot(state))

    @property
    def operation_in_progress(self) -> bool:
        """Return whether a Home Assistant action is currently executing."""
        return self._operation_in_progress

    async def async_lock(self) -> None:
        """Serialize and execute a lock request through the client boundary."""
        await self._async_run_operation("lock", self.client.async_lock)

    async def async_unlock(self) -> None:
        """Serialize and execute an unlock request through the client boundary."""
        await self._async_run_operation("unlock", self.client.async_unlock)

    async def _async_run_operation(
        self,
        operation: str,
        action: Callable[[], Awaitable[bool | None]],
    ) -> None:
        """Run one HA operation at a time for this config entry."""
        async with self._operation_lock:
            state = self.bluetooth_manager.state
            if not state.reachable:
                raise AqaraU200BluetoothUnavailableError(
                    "Aqara U200 is not reachable through a connectable Bluetooth adapter"
                )

            self._operation_in_progress = True
            self._last_operation = operation
            self._last_error_type = None
            self.async_set_updated_data(self._build_snapshot(state))

            try:
                observed = await action()
                # Prefer the real bolt position read from the lock (ff62 report);
                # fall back to the optimistic commanded position if none arrived.
                self._is_locked = observed if observed is not None else operation == "lock"
            except AqaraU200AuthenticationError as err:
                self._last_error_type = type(err).__name__
                self._entry.async_start_reauth(self.hass)
                raise
            except AqaraU200Error as err:
                self._last_error_type = type(err).__name__
                raise
            except Exception as err:
                self._last_error_type = type(err).__name__
                raise AqaraU200OperationError(
                    f"Aqara U200 {operation} operation failed"
                ) from err
            finally:
                self._operation_in_progress = False
                self.async_set_updated_data(
                    self._build_snapshot(self.bluetooth_manager.state)
                )

    def _build_snapshot(
        self, bluetooth_state: AqaraU200BluetoothState
    ) -> AqaraU200RuntimeSnapshot:
        """Build a sanitized immutable snapshot."""
        return AqaraU200RuntimeSnapshot(
            reachable=bluetooth_state.reachable,
            last_seen=bluetooth_state.last_seen,
            rssi=bluetooth_state.rssi,
            control_enabled=self.client.control_enabled,
            operation_in_progress=self._operation_in_progress,
            last_operation=self._last_operation,
            last_error_type=self._last_error_type,
            is_locked=self._is_locked,
        )
