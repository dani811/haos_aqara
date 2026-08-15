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

## Scenario A - Pending backend fails closed

1. Configure an Aqara U200 entry.
2. Load the integration without a real `aqara-u200-ble` adapter.
3. Verify a native lock entity is created.
4. Verify the entity is unavailable and no control operation is sent.

Expected: configuration/runtime can load safely; actuation remains disabled.

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

## Hardware validation

Deferred until Phase 4. Do not use this slice to execute real lock/unlock commands.
