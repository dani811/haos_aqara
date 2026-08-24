# Feature Specification: Integration Runtime

**Feature Branch**: `feature/002-integration-runtime`  
**Status**: Implementation complete; distribution and hardware validation pending
**Depends on**: `feature/001-ha-integration-scaffold`  
**External blocker**: tag `v0.5.0` is released, but the `aqara-ble==0.5.0` distribution must be published to the Python package index before Home Assistant can install the manifest requirement.

## Goal

Build the Home Assistant runtime architecture for an Aqara U200 without coupling Home Assistant entities to the reverse-engineered protocol implementation. The integration discovers and tracks the configured lock through Home Assistant's shared Bluetooth stack, including Bluetooth Proxy paths, and exposes only the confirmed lock/unlock operations through the released `U200Client` facade.

## User Scenarios

### US1 - Bluetooth reachability
A configured U200 is considered reachable when Home Assistant can resolve it through a connectable Bluetooth controller. The controller may be local or remote (Bluetooth Proxy). The integration must not create its own scanner.

### US2 - Safe native lock surface
Home Assistant creates a native `lock` entity for the configured U200. It is available only when Home Assistant has a connectable Bluetooth path and the confirmed protocol adapter is enabled. State remains unknown until a verified state-read path exists; commands never set optimistic state.

### US3 - Serialized Home Assistant actions
Once a real client is enabled, rapid Home Assistant operations for the same configured lock are serialized by the integration runtime. Different config entries remain independent.

### US4 - Operational diagnostics
Diagnostics expose reachability and non-sensitive runtime state without account credentials, authentication material, session keys, raw payloads, or full Aqara identifiers.

## Functional Requirements

- **FR-001**: Resolve BLE devices exclusively through Home Assistant Bluetooth APIs with `connectable=True`.
- **FR-002**: Register Home Assistant Bluetooth callbacks by configured address and unsubscribe on config-entry unload.
- **FR-003**: Support local adapters and Bluetooth Proxy transparently; no direct scanner ownership.
- **FR-004**: Define an integration-owned `AqaraU200Client` protocol so entities/coordinator do not import protocol frames, KDF/session code, or `run_authenticated_lock_operation()`.
- **FR-005**: Adapt a fresh Home Assistant-routed Bleak connection to `U200Client.from_gatt()` with `CloudAuthManager`; do not use the library scanner or `BleakTransport`.
- **FR-006**: Maintain a push-based runtime snapshot containing reachability, last seen time, RSSI, control-enabled state, operation-in-progress state, last operation, and sanitized last error type.
- **FR-007**: Serialize Home Assistant lock operations per config entry using an `asyncio.Lock`.
- **FR-008**: The native `lock` entity MUST be unavailable while control is disabled or the lock is unreachable.
- **FR-009**: The native entity MUST use Home Assistant platform forwarding from the config entry and stable device/unique identifiers.
- **FR-010**: Diagnostics MUST NOT expose credentials, session material, raw request/response data, raw BLE payloads, or full Aqara `device_id`.
- **FR-011**: Config entry unload MUST unload platforms and unregister runtime Bluetooth callbacks.
- **FR-012**: Implementation behavior MUST be covered by automated tests before the feature phase is considered complete.
- **FR-013**: Collect required Aqara cloud credentials through config flow/reauth only; production code MUST NOT invent or read environment variables.
- **FR-014**: Map library, cloud and BLE failures to sanitized integration exceptions without exposing raw messages, payloads or crypto material.
- **FR-015**: A lock/unlock operation MUST NOT be retried after actuation may have started.

## Explicit Non-Goals / Guardrails

The following are intentionally NOT part of this feature:

- Pinning or importing an unreleased/in-progress `aqara-ble` revision.
- Executing hardware validation as part of automated tests.
- Moving BLE client work into executor threads.
- Reading production credentials from environment variables or `.env` files.
- Persisting ephemeral session keys or cryptographic material.
- Exposing `CATALOGUED`/unverified protocol operations as normal controls.
- Implementing user/PIN/RFID/settings APIs before the corresponding protocol operation is confirmed.
- Implementing automatic retries of partial authentication/control operations.
- Logging request/response payloads or secrets.

## Success Criteria

1. A configured address can transition between reachable/unreachable using Home Assistant Bluetooth callbacks.
2. The lock entity is available only with a connectable Home Assistant Bluetooth path, exposes lock/unlock only, and never invents lock state.
3. With a fake enabled client, same-entry actions are serialized.
4. Runtime state updates are pushed to subscribers without active polling or cloud traffic.
5. Unload removes subscriptions cleanly.
6. Automated unit/integration tests pass as a gate, including error sanitization and no post-actuation retry coverage.
