"""Runtime coordinator for Aqara U200."""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .bluetooth import AqaraU200BluetoothManager, AqaraU200BluetoothState
from .client import AqaraU200Client
from .const import (
    BATTERY_INITIAL_DELAY_SECONDS,
    BATTERY_POLL_SECONDS,
    DOMAIN,
    REALTIME_GAP_SECONDS,
    REALTIME_SESSION_SECONDS,
)
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
    #: Battery charge percentage read over BLE (None until the first read).
    battery_percent: int | None = None


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
        self._battery_percent: int | None = None
        self._realtime_task: asyncio.Task[None] | None = None
        self._listen_handle: asyncio.Task[None] | None = None
        self._realtime_stop = asyncio.Event()
        self._battery_task: asyncio.Task[None] | None = None
        self._battery_stop = asyncio.Event()
        self.data = self._build_snapshot(bluetooth_manager.state)

    @callback
    def async_start_realtime(self) -> None:
        """Start the opt-in persistent BLE state listener (real-time)."""
        if self._realtime_task is not None:
            return
        self._realtime_stop.clear()
        self._realtime_task = self.config_entry.async_create_background_task(
            self.hass, self._async_realtime_loop(), f"{DOMAIN}_realtime"
        )

    async def async_stop_realtime(self) -> None:
        """Stop the real-time listener (on unload or when the option is off)."""
        self._realtime_stop.set()
        self._preempt_listen()
        task, self._realtime_task = self._realtime_task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    @callback
    def _on_realtime_state(self, locked: bool) -> None:
        """Push a real bolt-position change (from the held ff62 session)."""
        if locked != self._is_locked:
            self._is_locked = locked
            self.async_set_updated_data(
                self._build_snapshot(self.bluetooth_manager.state)
            )

    def _preempt_listen(self) -> None:
        """Cancel the held listen so an actuation can take the BLE connection."""
        handle = self._listen_handle
        if handle is not None and not handle.done():
            handle.cancel()

    async def _async_realtime_loop(self) -> None:
        """Hold ONE low-power session open, streaming ff62 state, until stopped.

        Shares ``_operation_lock`` with actuations: an actuation preempts the held
        listen (``_preempt_listen``) so it releases the connection instantly, then
        the loop reconnects. No polling, no per-window reconnects.
        """
        while not self._realtime_stop.is_set():
            if not self.bluetooth_manager.state.reachable:
                await asyncio.sleep(REALTIME_GAP_SECONDS)
                continue
            try:
                async with self._operation_lock:
                    self._listen_handle = asyncio.ensure_future(
                        self.client.async_listen_realtime(
                            self._on_realtime_state, REALTIME_SESSION_SECONDS
                        )
                    )
                    try:
                        await self._listen_handle
                    finally:
                        self._listen_handle = None
            except asyncio.CancelledError:
                if self._realtime_stop.is_set():
                    raise
                # Preempted by an actuation; reconnect once it releases the lock.
            except Exception as err:  # noqa: BLE001 - transient BLE/cloud errors
                _LOGGER.debug("real-time listen ended (%s)", type(err).__name__)
            await asyncio.sleep(REALTIME_GAP_SECONDS)

    @callback
    def async_start_battery(self) -> None:
        """Start the periodic BLE battery poll (once after startup, then hourly-ish)."""
        if self._battery_task is not None:
            return
        self._battery_stop.clear()
        self._battery_task = self.config_entry.async_create_background_task(
            self.hass, self._async_battery_loop(), f"{DOMAIN}_battery"
        )

    async def async_stop_battery(self) -> None:
        """Stop the battery poll (on unload)."""
        self._battery_stop.set()
        task, self._battery_task = self._battery_task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _async_battery_loop(self) -> None:
        """Read the battery over BLE on a slow cadence, sharing the operation lock.

        Sleeps a short delay after startup, then reads every ``BATTERY_POLL_SECONDS``.
        Each read preempts any held real-time listen and takes ``_operation_lock`` so
        it never collides with an actuation. Failures keep the last known value.
        """
        try:
            await asyncio.wait_for(
                self._battery_stop.wait(), timeout=BATTERY_INITIAL_DELAY_SECONDS
            )
            return  # stopped during the initial delay
        except TimeoutError:
            pass
        while not self._battery_stop.is_set():
            await self._async_refresh_battery()
            try:
                await asyncio.wait_for(
                    self._battery_stop.wait(), timeout=BATTERY_POLL_SECONDS
                )
                return
            except TimeoutError:
                continue

    async def _async_refresh_battery(self) -> None:
        """Read the battery once (guarded), updating the snapshot on success."""
        if not self.bluetooth_manager.state.reachable:
            return
        self._preempt_listen()
        try:
            async with self._operation_lock:
                percent = await self.client.async_read_battery()
        except asyncio.CancelledError:
            raise
        except AqaraU200AuthenticationError as err:
            self._last_error_type = type(err).__name__
            self._entry.async_start_reauth(self.hass)
            return
        except Exception as err:  # noqa: BLE001 - transient BLE/cloud errors
            _LOGGER.debug("battery read failed (%s)", type(err).__name__)
            return
        if percent is not None and percent != self._battery_percent:
            self._battery_percent = percent
            self.async_set_updated_data(
                self._build_snapshot(self.bluetooth_manager.state)
            )

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
        # If a real-time listen holds the connection, preempt it so this actuation
        # takes the BLE connection without waiting.
        self._preempt_listen()
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
            battery_percent=self._battery_percent,
        )
