# Implementation Plan: Integration Runtime

## Technical Context

- Home Assistant custom integration, Python 3.14+.
- BLE connectivity is owned by Home Assistant's Bluetooth manager.
- `bluetooth.async_ble_device_from_address(..., connectable=True)` is the authoritative reachability lookup.
- Bluetooth discovery/unavailability callbacks drive runtime state; no integration-owned scanner and no active polling are required in this slice.
- `DataUpdateCoordinator` is used as a push coordinator; updates are emitted with `async_set_updated_data`.
- A native `LockEntity` consumes only the integration runtime/client abstraction.
- The adapter targets the exact released `aqara-ble` 0.5.0 API. Installation remains externally blocked until that distribution is available from the Python package index.

## Architecture

```text
ConfigEntry
   |
   +-- AqaraU200BluetoothManager ----> HA Bluetooth Manager ----> local adapter / BT Proxy
   |
   +-- AqaraU200Client protocol
   |       `-- AqaraU200BleClientAdapter
   |              `-- fresh bleak-retry-connector client
   |                    `-- U200Client.from_gatt(CloudAuthManager)
   |
   `-- AqaraU200Coordinator
            |
            `-- LockEntity
```

## Key Decisions

1. **Adapter boundary**: Home Assistant never imports KDF/session/frame primitives.
2. **Push coordinator**: BLE advertisements/unavailable events update the coordinator; no protocol state polling is invented before reverse engineering confirms a safe state-read path.
3. **Confirmed surface only**: expose lock/unlock; keep `is_locked=None` until state reads are verified.
4. **HA serialization**: one `asyncio.Lock` per config-entry coordinator. The protocol library will separately reject accidental same-device concurrency.
5. **No retries here**: runtime does not retry partially completed operations.
6. **Sanitized observability**: only error type/runtime metadata are stored in the coordinator.

## Phase Gates

### Phase 1 - Runtime contracts
- Client protocol and typed integration exceptions.
- Tests for adapter-boundary and sanitized-error behavior.

### Phase 2 - Bluetooth runtime
- HA Bluetooth resolution/callback manager.
- Push coordinator and runtime snapshot.
- Tests for reachable/unreachable transitions and cleanup registration.

### Phase 3 - Native lock surface
- Platform forwarding and `LockEntity`.
- Entity availability requires both the released adapter and a connectable Bluetooth path.
- Fake enabled client demonstrates serialized actions.
- Integration tests pass.

### Phase 4 - Real adapter
- Pin `aqara-ble==0.5.0` in the integration manifest.
- Resolve the connectable BLEDevice through Home Assistant and establish a fresh connection with `bleak-retry-connector`.
- Wrap the connected GATT client with `U200Client.from_gatt()` and inject a config-entry-owned `CloudAuthManager`.
- Map failures to sanitized integration exceptions and start reauth on code 810.
- Do not retry after the protocol operation begins; the library additionally guards its exact point of no return.
- Remaining external gates: publish the 0.5.0 Python distribution and validate on a physical U200 through Bluetooth Proxy.

## Alternatives Rejected

- Own Bleak scanner: bypasses HA Bluetooth/Proxy routing.
- Direct calls from `LockEntity` into `run_authenticated_lock_operation`: couples HA to unstable protocol internals.
- Enable controls now and raise at runtime: misleading UX and risks accidental hardware calls.
- Polling lock state through unknown commands: protocol behavior is not yet confirmed.
- Global operation mutex: unnecessarily serializes different locks.
