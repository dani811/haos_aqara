"""Protocol-independent client boundary and real Aqara U200 adapter."""

import asyncio
import logging
from collections.abc import Mapping
from functools import partial
from typing import Any, Protocol

from aqara_ble import (
    CloudAuthManager,
    CloudServiceError,
    FlowPhase,
    LockOperation,
    OperationInProgressError,
    U200ClientError,
)
from aqara_ble import (
    U200Client as ProtocolU200Client,
)
from bleak.exc import BleakError
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    BleakConnectionError,
    establish_connection,
)
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .bluetooth import AqaraU200BluetoothManager
from .const import (
    CONF_ACCOUNT,
    CONF_REGION,
    DEFAULT_REGION,
)
from .exceptions import (
    AqaraU200AuthenticationError,
    AqaraU200BluetoothUnavailableError,
    AqaraU200OperationError,
)

_LOGGER = logging.getLogger(__name__)
_CONNECTION_NAME = "Aqara U200"
_DISCONNECT_TIMEOUT = 10
#: Seconds to keep the session open after an actuation to read the lock's real
#: bolt position from the ff62 report channel.
_STATE_LISTEN_SECONDS = 3.0

AUTH_CONFIG_KEYS = (
    CONF_ACCOUNT,
    CONF_PASSWORD,
)


class AqaraU200Client(Protocol):
    """Contract consumed by the Home Assistant runtime.

    Real protocol/session/KDF details stay behind an adapter implementing this
    contract. Entities must never depend directly on aqara-ble internals.
    """

    @property
    def control_enabled(self) -> bool:
        """Return whether real lock control is safe and enabled."""
        ...

    async def async_lock(self) -> bool | None:
        """Lock the device; return the real bolt position if observed."""
        ...

    async def async_unlock(self) -> bool | None:
        """Unlock the device; return the real bolt position if observed."""
        ...

    async def async_read_state(self, listen_after: float) -> bool | None:
        """Read the real bolt position over BLE without actuating."""
        ...


def build_cloud_auth(config: Mapping[str, Any]) -> CloudAuthManager:
    """Build library-owned cloud auth from Home Assistant config-entry data.

    Only account + password are needed: aqara-ble bakes the app-global
    appid/appkey and generates the per-install phone_id/client_id.
    """
    return CloudAuthManager(
        account=config[CONF_ACCOUNT],
        password=config[CONF_PASSWORD],
        region=config.get(CONF_REGION, DEFAULT_REGION),
    )


def is_invalid_auth_error(err: BaseException) -> bool:
    """Return whether an exception chain contains Aqara invalid-auth code 810."""
    current: BaseException | None = err
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, CloudServiceError) and current.is_code(810):
            return True
        current = current.__cause__ or current.__context__
    return False


async def async_validate_cloud_auth(
    hass: HomeAssistant, config: Mapping[str, Any]
) -> None:
    """Validate credentials without blocking Home Assistant's event loop."""
    auth = build_cloud_auth(config)
    await hass.async_add_executor_job(auth.build_signer)


async def async_resolve_device_id(
    hass: HomeAssistant, config: Mapping[str, Any], *, mac: str | None = None
) -> str:
    """Resolve the lock's device id from the account (off the event loop).

    Lets the config flow avoid asking the user for a device id: it lists the
    account's devices and, when there is more than one, matches ``mac``.
    """
    auth = build_cloud_auth(config)
    return await hass.async_add_executor_job(partial(auth.resolve_device_id, mac=mac))


class AqaraU200BleClientAdapter:
    """Adapt HA-managed Bluetooth connections to ``aqara-ble``."""

    def __init__(
        self,
        bluetooth_manager: AqaraU200BluetoothManager,
        auth: CloudAuthManager,
        device_id: str,
        region: str,
    ) -> None:
        """Initialize a stateless adapter for one config entry."""
        self._bluetooth_manager = bluetooth_manager
        self._auth = auth
        self._device_id = device_id
        self._region = region

    @property
    def control_enabled(self) -> bool:
        """Confirmed lock and unlock operations are enabled."""
        return True

    async def async_lock(self) -> bool | None:
        """Run one confirmed lock operation without actuation retries."""
        return await self._async_operate("lock")

    async def async_unlock(self) -> bool | None:
        """Run one confirmed unlock operation without actuation retries."""
        return await self._async_operate("unlock")

    async def async_read_state(self, listen_after: float) -> bool | None:
        """Non-actuating: open a session and read the real ff62 bolt position.

        Sends only the read-only keepalive and listens ``listen_after`` seconds
        for a spontaneous ff62 report (a change made from anywhere). Returns the
        observed position, or None if nothing was pushed in the window.
        """
        return await self._async_operate("listen", listen_after=listen_after)

    async def _async_operate(
        self, operation: str, *, listen_after: float = _STATE_LISTEN_SECONDS
    ) -> bool | None:
        """Connect, execute once, read the real state, and release the client.

        Returns the bolt position read from the ff62 report channel during the
        post-command listen window (True locked / False unlocked / None if the
        lock pushed nothing in time).
        """
        ble_device = self._bluetooth_manager.async_get_ble_device()
        if ble_device is None:
            raise AqaraU200BluetoothUnavailableError(
                "Aqara U200 is not reachable through Home Assistant Bluetooth"
            )

        bleak_client: BleakClientWithServiceCache | None = None
        operation_started = False
        observed_locked: bool | None = None
        try:
            bleak_client = await establish_connection(
                BleakClientWithServiceCache,
                ble_device,
                _CONNECTION_NAME,
                ble_device_callback=lambda: (
                    self._bluetooth_manager.async_get_ble_device() or ble_device
                ),
            )
            protocol_client = ProtocolU200Client.from_gatt(
                auth=self._auth,
                gatt_client=bleak_client,
                device_id=self._device_id,
                region=self._region,
            )
            operation_started = True
            op = {
                "lock": LockOperation.LOCK,
                "unlock": LockOperation.UNLOCK,
            }.get(operation, LockOperation.KEEPALIVE)
            result = await protocol_client.operate(op, listen_after=listen_after)
            observed_locked = result.observed_locked
        except asyncio.CancelledError:
            raise
        except Exception as err:
            if is_invalid_auth_error(err) or (
                isinstance(err, U200ClientError) and err.phase is FlowPhase.LOGIN
            ):
                raise AqaraU200AuthenticationError(
                    "Aqara rejected the configured credentials"
                ) from err
            if not operation_started and isinstance(
                err, (BleakConnectionError, BleakError, TimeoutError)
            ):
                raise AqaraU200BluetoothUnavailableError(
                    "Could not connect to Aqara U200 through Home Assistant Bluetooth"
                ) from err
            if (
                isinstance(
                    err,
                    (CloudServiceError, OperationInProgressError, U200ClientError),
                )
                or operation_started
            ):
                raise AqaraU200OperationError(
                    f"Aqara U200 {operation} operation failed"
                ) from err
            raise AqaraU200OperationError(
                f"Aqara U200 {operation} operation failed"
            ) from err
        finally:
            if bleak_client is not None:
                try:
                    async with asyncio.timeout(_DISCONNECT_TIMEOUT):
                        await bleak_client.disconnect()
                except asyncio.CancelledError:
                    raise
                except Exception as err:  # noqa: BLE001 - best-effort disconnect
                    _LOGGER.debug(
                        "Aqara U200 BLE disconnect failed (%s)", type(err).__name__
                    )

        return observed_locked
