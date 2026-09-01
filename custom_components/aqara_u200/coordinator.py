"""Runtime coordinator for Aqara U200."""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from aqara_ble import LockEvent

from .bluetooth import AqaraU200BluetoothManager, AqaraU200BluetoothState
from .client import AqaraU200Client, LockSettings
from .const import (
    BATTERY_INITIAL_DELAY_SECONDS,
    CONF_POLL_HOURS,
    DEFAULT_POLL_HOURS,
    DOMAIN,
    REALTIME_GAP_SECONDS,
    REALTIME_SESSION_SECONDS,
    REFRESH_GAP_SECONDS,
    ROTATION_FILL_SECONDS,
    ROTATION_POLL_SECONDS,
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
    #: Static feature settings read over BLE (None fields until first read).
    door_type: str | None = None
    assist_turn: bool | None = None
    pull_spring_enabled: bool | None = None
    pull_spring_retraction_s: int | None = None
    #: Configuration settings read over BLE (feature 002; None until first read).
    system_volume: int | None = None
    language: str | None = None
    alert_volume: str | None = None
    alarm_volume: str | None = None


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
        self._settings = LockSettings()
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
    def _on_realtime_event(self, event: LockEvent) -> None:
        """Consume one live ff62 event: update state/battery and fire an HA event.

        The lock pushes typed events over the held session — lock/unlock (with a
        source: manual/key/keypad/etc.), a periodic status heartbeat, and its own
        battery reports. We apply the state and battery to the coordinator and
        fire ``aqara_u200_event`` on the HA bus so the logbook, automations, and
        the card's own notification badge can react — entirely over Bluetooth
        (no Matter/cloud).

        "unknown" (an ff62 opcode ``decode_event`` doesn't recognize yet) is
        included on purpose, not filtered out: a wrong-code/keypad-failure push
        — if the lock sends one at all — would currently decode as exactly this,
        carrying its ``raw_hex`` but no interpreted meaning. Firing it means a
        live capture immediately shows up as a real HA event (and the card can
        show a generic "something happened" badge) instead of silently
        vanishing until ``decode_event`` is taught the opcode. "status" (the
        periodic heartbeat) is excluded — it is not a notable event, just a
        keepalive with no position.
        """
        changed = False
        if event.locked is not None and event.locked != self._is_locked:
            self._is_locked = event.locked
            changed = True
        if (
            event.battery_percent is not None
            and event.battery_percent != self._battery_percent
        ):
            self._battery_percent = event.battery_percent
            changed = True
        if event.kind in ("locked", "unlocked", "unknown"):
            self.hass.bus.async_fire(
                f"{DOMAIN}_event",
                {
                    "entry_id": self._entry.entry_id,
                    "kind": event.kind,
                    "locked": event.locked,
                    "source": event.source,
                    "timestamp": event.timestamp,
                    "raw_hex": event.raw_hex,
                },
            )
        if changed:
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
                            self._on_realtime_event, REALTIME_SESSION_SECONDS
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
    def async_start_initial_sync(self) -> None:
        """Kick off one full BLE read rotation in the background, unconditionally.

        Runs once per config-entry setup — both on a fresh install and on every
        Home Assistant restart — so entities populate on their own within a few
        minutes instead of staying 'unknown' until the user presses the Refresh
        button or opts into background polling. Fire-and-forget: `setup_entry`
        must not block on this (a full rotation takes ~2-3 minutes, see
        `REFRESH_GAP_SECONDS`), so it's scheduled as a background task exactly
        like the real-time listener and the battery poll.
        """
        self.config_entry.async_create_background_task(
            self.hass, self.async_refresh_all(), f"{DOMAIN}_initial_sync"
        )

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
        tasks = ("state", "battery", "door_type", "assist_turn", "pull_spring")
        index = 0
        while not self._battery_stop.is_set():
            # HA's Bluetooth proxy reliably serves only ONE connect+read per burst
            # for this lock — a second back-to-back read times out. So read exactly
            # one value per cycle and rotate, giving each read a clean connection.
            await self._async_do_read(tasks[index % len(tasks)])
            index += 1
            have_all = (
                self._battery_percent is not None
                and self._settings.door_type is not None
                and self._settings.assist_turn is not None
                and self._settings.pull_spring_enabled is not None
            )
            interval = self._poll_seconds if have_all else ROTATION_FILL_SECONDS
            try:
                await asyncio.wait_for(self._battery_stop.wait(), timeout=interval)
                return
            except TimeoutError:
                continue

    @property
    def _poll_seconds(self) -> float:
        """Steady background poll interval (per read) from options, in seconds."""
        hours = self._entry.options.get(CONF_POLL_HOURS, DEFAULT_POLL_HOURS)
        try:
            hours = float(hours)
        except (TypeError, ValueError):
            hours = float(DEFAULT_POLL_HOURS)
        return hours * 3600.0 if hours > 0 else ROTATION_POLL_SECONDS

    async def async_refresh_all(self) -> None:
        """Read every value once over BLE, retrying whatever didn't land.

        On-demand: rotates through state/battery/settings sequentially so each read
        gets a clean connection (HA's Bluetooth proxy dislikes back-to-back reads).

        Confirmed live 2026-08-31: one full pass can silently drop a read (the
        'config' burst — volume/language — failed once through a flaky proxy
        connection while every other read succeeded). ``_async_do_read`` already
        swallows failures per-item so one bad read doesn't abort the rotation;
        this adds a single retry pass over just the names still unread after the
        first lap, so a one-off proxy hiccup doesn't leave a value stuck
        'unknown' until the next restart or a manual Refresh press.
        """
        order = ("state", "battery", "door_type", "assist_turn", "pull_spring", "config")
        await self._async_refresh_pass(order, gap_before_first=False)

        missing = [name for name in order if self._is_unread(name)]
        if missing:
            await self._async_refresh_pass(missing, gap_before_first=True)

    async def _async_refresh_pass(self, names: tuple[str, ...] | list[str], *, gap_before_first: bool) -> None:
        """Read each name in order, pacing every read with REFRESH_GAP_SECONDS."""
        for index, name in enumerate(names):
            if self._battery_stop.is_set():
                return
            if index > 0 or gap_before_first:
                await asyncio.sleep(REFRESH_GAP_SECONDS)
            await self._async_do_read(name)

    def _is_unread(self, name: str) -> bool:
        """Return whether ``name`` still has no value from a completed read."""
        if name == "state":
            return self._is_locked is None
        if name == "battery":
            return self._battery_percent is None
        if name == "door_type":
            return self._settings.door_type is None
        if name == "assist_turn":
            return self._settings.assist_turn is None
        if name == "pull_spring":
            return self._settings.pull_spring_enabled is None
        # "config" is one burst read (volume/language) — retry it if any part
        # of the burst is still missing.
        return (
            self._settings.system_volume is None
            or self._settings.language is None
            or self._settings.alert_volume is None
            or self._settings.alarm_volume is None
        )

    async def _async_do_read(self, name: str) -> None:
        """Read ONE value over BLE (guarded), updating the snapshot on change.

        Skipped only when the lock is unreachable. Any held real-time listen is
        preempted so the read gets the connection, then it reconnects.
        """
        if not self.bluetooth_manager.state.reachable:
            return
        # Preempt any held real-time listen so this read gets the connection; the
        # real-time loop reconnects afterwards. (Earlier this skipped state/settings
        # whenever real-time was on — the actual cause of their staying 'unknown'.)
        self._preempt_listen()
        try:
            async with self._operation_lock:
                value = await self._async_read_one(name)
        except asyncio.CancelledError:
            raise
        except AqaraU200AuthenticationError as err:
            self._last_error_type = type(err).__name__
            self._entry.async_start_reauth(self.hass)
            return
        except Exception as err:  # noqa: BLE001 - transient BLE/cloud errors
            _LOGGER.debug("%s read failed (%s)", name, type(err).__name__)
            return
        if value is not None and self._apply_read(name, value):
            self.async_set_updated_data(
                self._build_snapshot(self.bluetooth_manager.state)
            )

    async def _async_read_one(self, name: str) -> object:
        """Dispatch a single named BLE read to the client boundary."""
        if name == "state":
            return await self.client.async_read_lock_status()
        if name == "battery":
            return await self.client.async_read_battery()
        if name == "door_type":
            return await self.client.async_read_door_type()
        if name == "assist_turn":
            return await self.client.async_read_assist_turn()
        if name == "config":
            return await self.client.async_read_settings()
        return await self.client.async_read_pull_spring()

    @callback
    def _apply_read(self, name: str, value: object) -> bool:
        """Store a read value into local state; return whether it changed."""
        if name == "state":
            if value != self._is_locked:
                self._is_locked = value
                return True
            return False
        if name == "battery":
            if value != self._battery_percent:
                self._battery_percent = value
                return True
            return False
        if name == "door_type":
            new = replace(self._settings, door_type=value)
        elif name == "assist_turn":
            new = replace(self._settings, assist_turn=value)
        elif name == "config":  # LockSettings burst -> volume/language/alert/alarm
            new = replace(
                self._settings,
                system_volume=value.system_volume,
                language=value.language,
                alert_volume=value.alert_volume,
                alarm_volume=value.alarm_volume,
            )
        else:  # pull_spring -> (enabled, retraction_seconds)
            new = replace(
                self._settings,
                pull_spring_enabled=value[0],
                pull_spring_retraction_s=value[1],
            )
        if new != self._settings:
            self._settings = new
            return True
        return False

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

    async def async_set_alert_volume(self, level: int) -> None:
        """Serialize an alert-volume SET, then re-read it to confirm the real value."""
        await self._async_run_set_operation(
            "set_alert_volume", lambda: self.client.async_set_alert_volume(level)
        )

    async def async_set_alarm_volume(self, *, silent: bool) -> None:
        """Serialize an alarm-volume SET, then re-read it to confirm the real value."""
        await self._async_run_set_operation(
            "set_alarm_volume", lambda: self.client.async_set_alarm_volume(silent=silent)
        )

    async def async_set_alert_delay(self, seconds: int) -> None:
        """Serialize an open-door alarm-delay SET ('Retraso de alerta')."""
        await self._async_run_set_operation(
            "set_alert_delay", lambda: self.client.async_set_alert_delay(seconds)
        )

    async def async_set_verify_fail_time(self, seconds: int) -> None:
        """Serialize a keypad-lockout-duration SET ('Bloqueo de verificación')."""
        await self._async_run_set_operation(
            "set_verify_fail_time", lambda: self.client.async_set_verify_fail_time(seconds)
        )

    async def async_set_auto_lockup_relock_delay(self, seconds: int) -> None:
        """Serialize a 'Re-bloqueo de seguridad' delay SET."""
        await self._async_run_set_operation(
            "set_auto_lockup_relock_delay",
            lambda: self.client.async_set_auto_lockup_relock_delay(seconds),
        )

    async def async_set_auto_lock_on_close_delay(self, seconds: int) -> None:
        """Serialize a 'Bloqueo automático al cerrar' delay SET."""
        await self._async_run_set_operation(
            "set_auto_lock_on_close_delay",
            lambda: self.client.async_set_auto_lock_on_close_delay(seconds),
        )

    async def async_enable_auxiliary_locking_on_close(self) -> None:
        """Serialize enabling 'Bloqueo automático al cerrar'.

        One-directional: no confirmed disable frame exists yet (see client.py).
        """
        await self._async_run_set_operation(
            "enable_auxiliary_locking_on_close",
            lambda: self.client.async_enable_auxiliary_locking_on_close(),
        )

    async def async_enable_auxiliary_locking_relock(self) -> None:
        """Serialize enabling 'Re-bloqueo de seguridad'.

        One-directional: no confirmed disable frame exists yet (see client.py).
        """
        await self._async_run_set_operation(
            "enable_auxiliary_locking_relock",
            lambda: self.client.async_enable_auxiliary_locking_relock(),
        )

    async def _async_run_set_operation(
        self, operation: str, action: Callable[[], Awaitable[None]]
    ) -> None:
        """Run one settings-write operation, then re-read the config burst.

        Unlike ``_async_run_operation`` (lock/unlock), a SET write has no bolt
        position to observe — it confirms itself by re-reading the same
        ``config`` burst the SET belongs to, so the entity ends up showing
        what the lock actually reports now, not an optimistic guess of what
        the write probably did.
        """
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
                await action()
                value = await self.client.async_read_settings()
                if value is not None:
                    self._apply_read("config", value)
            except AqaraU200AuthenticationError as err:
                self._last_error_type = type(err).__name__
                self._entry.async_start_reauth(self.hass)
                raise
            except AqaraU200Error as err:
                self._last_error_type = type(err).__name__
                raise
            except Exception as err:
                self._last_error_type = type(err).__name__
                raise AqaraU200OperationError(f"Aqara U200 {operation} failed") from err
            finally:
                self._operation_in_progress = False
                self.async_set_updated_data(
                    self._build_snapshot(self.bluetooth_manager.state)
                )

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
            door_type=self._settings.door_type,
            assist_turn=self._settings.assist_turn,
            pull_spring_enabled=self._settings.pull_spring_enabled,
            pull_spring_retraction_s=self._settings.pull_spring_retraction_s,
            system_volume=self._settings.system_volume,
            language=self._settings.language,
            alert_volume=self._settings.alert_volume,
            alarm_volume=self._settings.alarm_volume,
        )
