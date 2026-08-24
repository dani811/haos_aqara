# haos_aqara

Home Assistant custom integration for autonomous Aqara U200 management over Bluetooth, backed by the `aqara-ble` protocol library.

## Goals

- Native Home Assistant `lock` entity for confirmed lock operations.
- Transparent use of Home Assistant Bluetooth adapters and Bluetooth Proxy.
- Config-flow based setup and Bluetooth discovery.
- Diagnostics with secret redaction.
- A bundled Lovelace card for lock status and management.
- Progressive exposure of user/PIN/RFID/settings management only after the corresponding BLE operation is verified end-to-end.

## Architecture

```text
Lovelace card
     |
     v
Home Assistant entities/actions
     |
     v
custom_components/aqara_u200
     |
     +--> Home Assistant Bluetooth API / Bluetooth Proxy
     |
     +--> aqara-ble
              |
              +--> BLE auth + AES-CCM control channel
              +--> Aqara cloud login/KDF/session verification
```

The frontend never talks BLE directly. The custom card only consumes Home Assistant state and invokes Home Assistant actions.

## Security model

The lock command is sent locally over BLE, but the current authentication pipeline still uses Aqara Cloud to obtain fresh session material. Session keys are ephemeral and are not treated as reusable credentials.

Passwords and raw secrets must never be exposed as entity attributes, card configuration, logs, or diagnostics.

## Development policy

The protocol library contains both verified and reverse-engineered/catalogued operations. Only operations marked `CONFIRMED` may be exposed as normal UI controls. Unverified operations must remain behind an explicit experimental boundary until validated against a real lock and covered by tests.

## Planned layout

```text
custom_components/aqara_u200/
  __init__.py
  manifest.json
  const.py
  config_flow.py
  coordinator.py
  lock.py
  diagnostics.py
  frontend.py
  translations/
  frontend/
    aqara-u200-card.js

tests/
```

## Status

The integration runtime uses Home Assistant Bluetooth routing, a fresh `bleak-retry-connector` connection per action, and `aqara-ble` 0.5.0 through `U200Client.from_gatt()`. Only confirmed lock/unlock operations are exposed; lock state is not optimistic. Installation remains blocked until the `aqara-ble==0.5.0` distribution is published to the Python package index, and physical Bluetooth Proxy validation is still required.
