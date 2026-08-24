# Tasks: Integration Runtime

Tests are gates: a behavior-changing task is not complete until its unit tests pass; a phase is not complete until phase integration/regression tests pass.

## Phase 1 - Runtime contracts

- [x] T001 Add integration-owned exception hierarchy.
- [x] T002 Add `AqaraU200Client` protocol.
- [x] T003 Keep entities isolated behind the integration-owned client protocol.
- [x] T004 Add unit tests for client-boundary behavior and sanitized failures.

## Phase 2 - Bluetooth runtime

- [x] T005 Add `AqaraU200BluetoothManager` using HA shared Bluetooth lookup.
- [x] T006 Register configured-address discovery callback and unavailable tracker; ensure unload cleanup.
- [x] T007 Add immutable Bluetooth/runtime state snapshots.
- [x] T008 Add push-based `AqaraU200Coordinator` without polling.
- [x] T009 Add per-entry `asyncio.Lock` to serialize HA actions.
- [x] T010 Add unit tests for reachability transitions, proxy-transparent lookup contract, operation state and serialization.

## Phase 3 - Native entity + config entry lifecycle

- [x] T011 Expand typed `ConfigEntry.runtime_data` with Bluetooth manager, client and coordinator.
- [x] T012 Forward the lock platform during setup and unload it during teardown.
- [x] T013 Add native `AqaraU200Lock` entity with stable identifiers/device info.
- [x] T014 Keep entity unavailable when BLE is unreachable OR `control_enabled=False`.
- [x] T015 Update diagnostics with sanitized runtime state and redacted identifiers.
- [x] T016 Add config-entry/entity integration tests.
- [x] T017 Add CI/test configuration and run complete regression suite.

**Phase 1-3 validation gate**: GitHub Actions passed on Python 3.14.7 with Home Assistant 2026.8.1; `14 passed` on the complete runtime suite.

## Phase 4 - Real protocol adapter

- [x] T018 Use the async-safe `aqara-ble` v0.5.0 release/tag.
- [x] T019 Pin `aqara-ble==0.5.0` in `manifest.json`.
- [x] T020 Implement `AqaraU200BleClientAdapter`; BLE remains on HA event loop, only library-owned blocking cloud calls are offloaded by the library.
- [x] T021 Map library concurrency/cloud/auth/BLE errors without leaking secrets.
- [x] T022 Enable confirmed lock/unlock only, without optimistic state.
- [ ] T023 Validate against physical U200 over Bluetooth Proxy.
- [x] T024 Add explicit config-flow credential collection and reauth; do not use production environment variables.
- [ ] T025 Publish the `aqara-ble==0.5.0` distribution to the Python package index so Home Assistant can install the manifest requirement.

## Not To Do

- Do not run destructive or unattended hardware actuation as an automated gate.
- Do not add direct Git/revision dependency as a production requirement merely to unblock development.
- Do not add own BLE scanning.
- Do not persist session keys.
- Do not expose unconfirmed/catalogued operations.
- Do not add transparent retries after a command may have been sent.
- Do not put credentials or crypto material in states, diagnostics or logs.
