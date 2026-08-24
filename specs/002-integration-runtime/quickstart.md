# Quickstart Validation: Integration Runtime

## Prerequisites

- Python 3.14.2+
- Home Assistant-compatible test environment
- `pytest-homeassistant-custom-component`

## Automated validation

```bash
python -m pytest tests -vv
```

Expected result: all tests pass before Phase 3 is marked complete.

## Scenario A - Real adapter wiring

1. Configure an Aqara U200 entry with explicit cloud credentials.
2. Verify the integration constructs `CloudAuthManager` without reading environment variables.
3. Verify each lock/unlock action resolves the device through Home Assistant, creates a fresh connector client, calls `U200Client.from_gatt()`, and disconnects.

Expected: only confirmed lock/unlock operations are exposed and `is_locked` remains unknown rather than optimistic.

## Scenario B - Bluetooth reachability

1. Emit/mimic a Home Assistant Bluetooth service-info event for the configured address.
2. Verify runtime `reachable=True`, RSSI/last-seen update, and coordinator listeners are notified.
3. Trigger the HA Bluetooth unavailable callback.

Expected: runtime becomes unreachable without any custom scanner or cloud request.

## Scenario C - Serialization with fake client

1. Inject an enabled fake client whose operation blocks on a test event.
2. Start `async_unlock()`.
3. While it is running, start `async_lock()`.
4. Verify the second fake-client call does not begin until the first completes.

Expected: HA serializes actions for this config entry; a different config entry can operate independently.

## Scenario D - Diagnostics safety

Inspect config-entry diagnostics.

Expected: diagnostics contain only sanitized runtime metadata. Full `device_id`, account credentials, tokens, session material, raw HTTP data, cryptographic material and raw BLE payloads are absent.

## Distribution and hardware validation

Before installation validation, publish `aqara-ble==0.5.0` to the Python package index; the Git tag alone is not installable from a Home Assistant manifest. Physical lock/unlock validation through Bluetooth Proxy remains a controlled manual gate and is not run by automated tests.
