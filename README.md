# haos_aqara — Aqara U200 (Bluetooth) for Home Assistant

Home Assistant custom integration for the **Aqara U200** smart lock over **Bluetooth Low Energy**, backed by the [`aqara-ble`](https://pypi.org/project/aqara-ble/) protocol library (a clean-room, reverse-engineered reimplementation of the app's BLE stack).

It controls the lock **locally over BLE** through Home Assistant's Bluetooth (a native adapter or an ESPHome/Shelly **Bluetooth Proxy**) — the frontend never talks BLE directly.

---

## Cloud vs. Local — read this first

The U200 is a **Bluetooth** lock (no Wi-Fi). All control happens over BLE. The only question is where the **session keys** come from, and that is what "offline mode" changes.

| | What it uses the Aqara cloud for | When |
|---|---|---|
| **Account setup** | Validate your Aqara account + resolve the lock's device id | Once, at config-flow time |
| **Default (cloud-assisted) mode** | Fetch fresh BLE **session material** from the cloud on **every** operation | Each lock/read/write |
| **Offline mode (opt-in)** | Fetch the device **LTMK** (long-term master key) **once at startup**, then derive every session **locally** | Cloud touched once per HA start, then never for control |
| **Language change (voice OTA)** | Cloud voice-pack list + CDN download of the audio pack | Only when you change the spoken language |

### So, concretely
- **You always need the Aqara account at setup** — to find the lock and (for offline mode) to fetch the LTMK. There is no way around a first cloud contact: the LTMK is a per-device secret held by *your* cloud account, not something the integration can invent.
- **With offline mode ON, control is 100% local** after startup: unlock/lock, state, battery, settings and credential reads/writes derive their AES-CCM session from the LTMK **with no per-operation cloud call**. The master key is kept **in memory only** (never written to disk); after a restart it is fetched once more. If that one fetch fails, the integration **falls back to the cloud path** — enabling offline can never break control.
- **The internet can be down** for everyday control once the LTMK is in memory. It is only needed again at the next restart (to re-fetch the key) or to change the **spoken language** (which downloads an audio pack).

### What is *not* possible without the cloud / hardware
- **Faking the LTMK.** It is a random per-device key established at the factory/app bind and validated by the lock; a wrong key is rejected. It must be the real one, from your account.
- **A fully cloud-free first setup.** Identifying the lock and getting the LTMK both require one authenticated cloud read.
- **Changing the spoken language without the physical keypad.** The voice pack is streamed live to the lock's **front keypad panel**, which is battery-powered and sleeps; the lock only accepts the OTA while that panel is physically awake. This "presence gate" is a **hardware** constraint (proven in the lock firmware), not something the software can bypass — a physical keypad touch (or a fingerbot pressing it) is required for that one operation. Everything else needs no keypad.

---

## Operations matrix

| Operation | Works offline (LTMK)? | Needs the front keypad awake? | Notes |
|---|---|---|---|
| Lock / unlock | ✅ | ❌ | Back-panel motor; instant |
| Read bolt state / battery | ✅ | ❌ | Decrypted locally |
| Read door type / turn-assist / pull-spring | ✅ | ❌ | Back-panel settings |
| Read volume / alert / language / credential table | ✅ | ⚠️ yes | These live in the front panel; if asleep they read as *unknown* |
| Write settings (volumes, timers, alarms) | ✅ | ⚠️ yes | Same front-panel wake caveat |
| Enrol a visitor password | ✅ | ⚠️ yes | `aqara-ble` `add_visitor_password`; validated live (a real PIN opened the door) |
| Change spoken language (voice OTA) | ⚠️ cloud pack download | ✅ **required** | Needs the CDN pack **and** a physical keypad press during the transfer |

Legend: ✅ yes · ❌ no · ⚠️ conditional.

---

## Setup

1. Install via HACS (custom repository) or copy `custom_components/aqara_u200` into your HA config.
2. Make sure the lock is reachable by a Home Assistant Bluetooth adapter or a **Bluetooth Proxy** in range.
3. Add the integration — it discovers the lock over Bluetooth, then asks for your **Aqara account + password** (used to validate credentials and resolve the device id; only account + password are needed — the app id/keys and per-install ids are handled by the library).

### Options (per lock)
- **Offline mode** — opt-in, **off by default**. When on, the LTMK is fetched once at startup and control runs cloud-free (see the table above).
- **Real-time BLE state** — hold one Bluetooth connection open so the lock's own push reports (open/close, key/keypad/manual) arrive instantly, no polling. Costs a little lock battery.
- **Background poll (hours)** — periodically read battery + settings. `0` = off (on-demand only, via the Refresh button).

---

## Entities

- **Lock** — confirmed lock/unlock (state is not optimistic).
- **Sensors** — battery, signal strength, door type, pull-spring retraction, system volume, language, **credentials** (count + per-type breakdown; the lock never exposes PIN plaintext).
- **Binary sensors** — connectivity, turn-assist, pull-spring.
- **Selects** — alert volume, alarm volume, language.
- **Numbers** — open-door alarm delay, keypad-lockout duration, the two auto-lock delays.
- **Buttons** — Refresh over Bluetooth, enable auto-lock-on-close, enable security re-lock.

---

## Security model

- Control is sent **locally over BLE**. Session keys are ephemeral AES-CCM material derived per operation (from the cloud, or locally from the LTMK in offline mode).
- The **LTMK is never persisted** by the integration — it lives in memory for the session only.
- **Passwords and raw secrets are never exposed** as entity attributes, card config, logs, or diagnostics; diagnostics are redacted.

## Development policy

`aqara-ble` carries both verified and catalogued/reverse-engineered operations. Only operations **confirmed end-to-end against a real lock** are exposed as normal UI controls; unverified ones stay behind an explicit experimental boundary until validated and covered by tests.

## Architecture

```text
Lovelace card
     │  (consumes HA state + invokes HA actions only — never BLE)
     ▼
Home Assistant entities / actions
     ▼
custom_components/aqara_u200  (coordinator + client adapter)
     ├─▶ Home Assistant Bluetooth API / Bluetooth Proxy   ── BLE ──▶ lock
     └─▶ aqara-ble
            ├─ BLE auth handshake + AES-CCM control channel
            ├─ offline session (LTMK → local HKDF)  ── or ──  cloud session (KDF/verify)
            └─ cloud: account login · device resolve · LTMK fetch · voice-pack OTA
```

## Status

Runtime uses HA Bluetooth routing with a fresh `bleak-retry-connector` connection per action via `U200Client.from_gatt()`; lock state is not optimistic. Requires **`aqara-ble`** on PyPI (see `manifest.json` for the pinned version). Offline mode and the credentials sensor are available; a physical Bluetooth Proxy in range of the lock is recommended for reliable operation.
