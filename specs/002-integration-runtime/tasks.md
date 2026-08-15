# Tasks: Integration Runtime

Tests are gates: a behavior-changing task is not complete until its unit tests pass; a phase is not complete until phase integration/regression tests pass.

## Phase 1 - Runtime contracts

- [ ] T001 Add integration-owned exception hierarchy.
- [ ] T002 Add `AqaraU200Client` protocol.
- [ ] T003 Add `PendingAqaraU200Client` with `control_enabled=False` and no BLE/cloud side effects.
- [ ] T004 Add unit tests for pending backend behavior.

## Phase 2 - Bluetooth runtime

- [ ] T005 Add `AqaraU200BluetoothManager` using HA shared Bluetooth lookup.
- [ ] T006 Register configured-address discovery callback and unavailable tracker; ensure unload cleanup.
- [ ] T007 Add immutable Bluetooth/runtime state snapshots.
- [ ] T008 Add push-based `AqaraU200Coordinator` without polling.
- [ ] T009 Add per-entry `asyncio.Lock` to serialize HA actions.
- [ ] T010 Add unit tests for reachability transitions, proxy-transparent lookup contract, operation state and serialization.

## Phase 3 - Native entity + config entry lifecycle

- [ ] T011 Expand typed `ConfigEntry.runtime_data` with Bluetooth manager, client and coordinator.
- [ ] T012 Forward the lock platform during setup and unload it during teardown.
- [ ] T013 Add native `AqaraU200Lock` entity with stable identifiers/device info.
- [ ] T014 Keep entity unavailable when BLE is unreachable OR `control_enabled=False`.
- [ ] T015 Update diagnostics with sanitized runtime state and redacted identifiers.
- [ ] T016 Add config-entry/entity integration tests.
- [ ] T017 Add CI/test configuration and run complete regression suite.

## Phase 4 - Real protocol adapter (BLOCKED)

- [ ] T018 Wait for async-safe `aqara-u200-ble` release/revision.
- [ ] T019 Pin exact released dependency.
- [ ] T020 Implement `AqaraU200BleClientAdapter`; BLE remains on HA event loop, only library-owned blocking cloud calls are offloaded by the library.
- [ ] T021 Map library concurrency/cloud/auth/BLE errors without leaking secrets.
- [ ] T022 Enable confirmed lock/unlock only.
- [ ] T023 Validate against physical U200 over Bluetooth Proxy.

## Not To Do

- Do not implement real actuation before T018-T021.
- Do not add direct Git/revision dependency as a production requirement merely to unblock development.
- Do not add own BLE scanning.
- Do not persist session keys.
- Do not expose unconfirmed/catalogued operations.
- Do not add transparent retries after a command may have been sent.
- Do not put credentials or crypto material in states, diagnostics or logs.
