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
- **Operations served by the sleeping front keypad panel, without waking it.** The voice-OTA language pack streams to that panel's speaker; the **credential table** (list/add/delete) and **front-panel settings** are fronted by it too. It is battery-powered and **sleeps**, and the lock only serves those operations while it is physically awake. This "presence gate" is a **hardware** constraint (the two panels have separate power; proven in the firmware for the voice OTA, confirmed live for credential writes), not something the software can bypass — a physical keypad touch (or a fingerbot pressing it) is required. Lock/unlock, bolt state, battery and the **access-log history** need no keypad. See [Presence handling](docs/presence-handling.md).

---

## Operations matrix

| Operation | Works offline (LTMK)? | Needs the front keypad awake? | Notes |
|---|---|---|---|
| Lock / unlock | ✅ | ❌ | Back-panel motor; instant |
| Read bolt state / battery | ✅ | ❌ | Decrypted locally |
| Read door type / turn-assist / pull-spring | ✅ | ❌ | Back-panel settings |
| Read **access log** (history) | ✅ | ❌ | Lives in the always-on back panel — a keypad-free history source (`aqara-ble` `read_access_log`) |
| Read volume / alert / language / credential table | ✅ | ✅ yes | Fronted by the keypad panel; if asleep they read as *unknown* / time out |
| Write settings (volumes, timers, alarms) | ✅ | ✅ yes | Same front-panel wake requirement |
| Enrol a visitor password | ✅ | ✅ yes | `aqara-ble` `add_visitor_password`; validated live (a real PIN opened the door) |
| **Delete a credential** | ✅ | ✅ yes | `aqara-ble` `delete_user`; verified live (removed the target, table 7→6). A delete sent while the keypad slept had **no effect** |
| Change spoken language (voice OTA) | ⚠️ cloud pack download | ✅ **required** | Needs the CDN pack **and** a physical keypad press during the transfer |

Legend: ✅ yes · ❌ no · ⚠️ conditional.

> **Confirmed live 2026-09-07:** credential **writes** (add/delete) and the
> table/front-panel reads need the keypad awake — not just the voice OTA. The
> credential database is fronted by the sleeping keypad panel. See
> [Presence handling](docs/presence-handling.md) for how the integration detects
> this and asks you (or a fingerbot) to wake it.

---

## Presence — when the lock needs the keypad awake

The U200 is two panels: the **always-on back panel** (motor, state, battery,
access log) and a **front keypad panel** that runs on its own AAA batteries and
**sleeps**. A handful of operations are served by that sleeping panel and only
work while it is **awake** (woken by a physical touch, or a fingerbot pressing it,
for ~45 s): the **credential table** (list/add/delete), **front-panel settings**
(system volume, language), and the **voice-OTA language change**. Everything else
— lock/unlock, bolt state, battery, door type, access-log history — needs no
keypad and works any time.

**How the integration handles it (least-imposition ladder):**

1. **Check first.** It asks the lock whether the keypad is awake
   (`read_front_connection`). If it already is, the operation just runs — no
   prompt.
2. **Auto-wake, if you have a fingerbot.** It fires the
   `aqara_u200_keypad_press_required` event (the bundled **blueprint** presses
   your keypad switch), and if you configured a **keypad wake switch** in the
   options it turns that switch on directly. Zero interaction.
3. **Ask you.** With no fingerbot (or if the press didn't register in time), it
   raises a **persistent notification**: *"touch the keypad in the next N
   seconds"*. One touch authorises the operation.
4. **Fail clearly.** If the window elapses with the panel still asleep, the
   operation errors with the reason instead of **silently doing nothing** — so a
   credential write never looks like it worked when it didn't.

This ladder runs for the **credential operations** (add via the *Add visitor
password* service, delete via the *Delete credential* service) and the **voice-OTA
language change**. The design — detection, escalation, config — is documented in
[docs/presence-handling.md](docs/presence-handling.md).

**To make waking automatic:** fit an Aqara fingerbot (or any BLE/Zigbee button)
over the keypad, expose it as a `switch`, and either set it as the **keypad wake
switch** in the integration options or attach the bundled blueprint to it.

---

## Setup

1. Install via HACS (custom repository) or copy `custom_components/aqara_u200` into your HA config.
2. Make sure the lock is reachable by a Home Assistant Bluetooth adapter or a **Bluetooth Proxy** in range.
3. Add the integration — it discovers the lock over Bluetooth, then asks for your **Aqara account + password** (used to validate credentials and resolve the device id; only account + password are needed — the app id/keys and per-install ids are handled by the library).

### Options (per lock)
- **Offline mode** — opt-in, **off by default**. When on, the LTMK is fetched once at startup and control runs cloud-free (see the table above).
- **Real-time BLE state** — hold one Bluetooth connection open so the lock's own push reports (open/close, key/keypad/manual) arrive instantly, no polling. Costs a little lock battery.
- **Background poll (hours)** — periodically read battery + settings. `0` = off (on-demand only, via the Refresh button).
- **Keypad wake switch** — optional. A `switch` (e.g. a fingerbot on the keypad) the integration turns on to wake the sleeping front panel for a presence-gated operation. Leave empty to rely on the bundled blueprint or a manual touch.

### Services (target the lock entity)

- **Add visitor password** (`aqara_u200.add_visitor_password`) — enrol a visitor PIN.
- **Delete credential** (`aqara_u200.delete_user`) — delete a credential by its lock user id (as shown by the credentials sensor / the Aqara cloud). Both wake the keypad first (see Presence) and error if it stays asleep.
- **Enrol fingerprint/NFC** (`aqara_u200.enrol_credential`) — ⚠️ *experimental, interactive*: starts a fingerprint or NFC-card enrolment; you physically present the finger (several times) or tap the card at the awake front-panel sensor. Fires `aqara_u200_enrol_progress` events during the flow. Reversed + unit-tested, but **not yet verified end-to-end against a real lock**.

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

Runtime uses HA Bluetooth routing with a fresh `bleak-retry-connector` connection per action via `U200Client.from_gatt()`; lock state is not optimistic. Requires **`aqara-ble`** on PyPI (see `manifest.json` for the pinned version). Offline mode, the credentials sensor, credential add/delete services, and presence handling (wake-or-ask before front-panel operations) are available; a physical Bluetooth Proxy in range of the lock is recommended for reliable operation.
