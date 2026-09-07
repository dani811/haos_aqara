# Presence handling — how to ask the user (or a fingerbot) to wake the keypad

The U200 is a **two-piece** lock. Some operations need the **front keypad panel
awake**; most don't. This doc studies *when* presence is required, *how the
integration detects it*, and *how it should impose on the user* to get it — from
"never bother them" up to "fail with a clear, actionable message" — plus what to
build to generalise the mechanism the language-OTA flow already uses.

## 1. Why presence exists (hardware, not policy)

- **Back panel (lock):** the motor + main MCU + the app-facing BLE. **Always on.**
- **Front panel (keypad):** its own AAA batteries, the keypad + fingerprint/NFC
  **sensors** + the **speaker**, and its own BLE link to the lock. It **sleeps**
  to save its cells and wakes on a touch (or a fingerbot press) for ~45 s.

So "presence" = *the front panel is awake right now*. It is reported by the lock
(`GET_FRONT_CONNECTION`, opcode `0xdd`) — the back panel tells you whether it can
currently reach the front one. It **cannot be faked** in software (the back panel
reports what it actually sees), only **queried** and **caused** (a real press).

## 2. What needs presence — verified live

Confirmed against a real lock (2026-09-07). The credential database and the
front-panel settings are **fronted by the sleeping keypad**, so reading *or*
writing them needs it awake; the motor and the back-panel state do not.

| Operation | Needs keypad awake | Evidence |
|---|---|---|
| Lock / unlock | ❌ no | Motor on the always-on back panel |
| Bolt state, battery, door type, pull-spring, turn-assist | ❌ no | Decoded live with the keypad asleep |
| **Read the credential table** (`read_user_table`) | ✅ yes | `0x1f` read returns empty / times out while asleep; fills on a press |
| **Add a credential** (`add_visitor_password`) | ✅ yes | Enrol landed only with the panel awake |
| **Delete a credential** (`delete_user`) | ✅ yes | A delete sent while asleep had **no effect**; the same frame with the keypad awake removed the entry (local table 7→6) on the first try |
| Read/write front-panel settings (system volume, language, alert/alarm) | ⚠️ mostly | Idioma/alerta/alarma often read from the back panel; **system volume** and reliable writes track presence — treat as presence-gated |
| **Change spoken language** (voice OTA) | ✅ **required** | Firmware-enforced: the ~2 MB audio pack streams to the front speaker; capped at 16 blocks + `0x1118` abort without a press |

> The access-log read (`read_access_log`, `0x13`) is the exception among "data"
> reads: the log lives in the **always-on back panel**, so it needs **no**
> presence — useful as a keypad-free history source.

## 3. Detecting presence — `read_front_connection()`

`aqara-ble` ≥ 1.14 exposes `U200Client.read_front_connection()` → `bool | None`
(`0xdd`; `0x01`=present, `0x00`=absent, `None`=unreadable). This is the pivot that
lets the integration **avoid bothering the user when the keypad is already awake**
and **confirm the wake actually happened** before running the gated op — instead of
firing blindly and hoping. Live-confirmed: value flips `False → True` within a
press window and holds ~45 s.

Requires bumping the integration's `aqara-ble` pin to ≥ 1.15.2 (also brings
`delete_user` and `read_access_log`).

## 4. The escalation ladder — how much to "abuse" the user

The design principle: **impose the least**. Only escalate when the cheaper level
did not already produce presence. Each level is checked against
`read_front_connection()` before moving to the next.

| Level | Mechanism | User burden | When |
|---|---|---|---|
| **0 — Check** | `read_front_connection()` | none | Always first. If already awake → run the op silently, done. |
| **1 — Auto-wake** | Fire `aqara_u200_keypad_press_required`; the fingerbot blueprint presses the keypad | none (if a fingerbot is fitted) | Keypad asleep and a wake entity is configured. |
| **2 — Ask a human** | `persistent_notification` "touch the keypad in the next N s" | one physical touch | No fingerbot, or the auto-press didn't register in the window. |
| **3 — Give up clearly** | `HomeActionError` / a **Repairs** issue with the reason + fix | reads as a real error, not a silent no-op | Window elapsed with the panel still absent. |

The key improvement over today: **level 3 must exist**. A credential write that
silently no-ops when the keypad is asleep (as delete did) is the worst outcome —
the user thinks it worked. Detecting absence up front turns that into an honest
"couldn't do it, here's why".

## 5. Proposed generalisation — `_ensure_presence()`

Today only `async_change_language` fires `EVENT_KEYPAD_PRESS_REQUIRED` + notifies.
The credential ops (`add_visitor_password`, and a future `delete_user`) merely say
"the front panel must be awake" in their docstring and fire nothing. Generalise:

```python
async def _ensure_presence(self, reason: str, *, window: float) -> None:
    """Make the keypad awake, or raise. Least-imposition ladder."""
    if await self.client.async_read_front_connection() is True:
        return                                    # level 0: already awake

    # level 1 + 2: ask the fingerbot AND the human, then poll for the wake
    self.hass.bus.async_fire(EVENT_KEYPAD_PRESS_REQUIRED,
                             {"entry_id": self._entry.entry_id, "reason": reason,
                              "window_seconds": int(window)})
    notif = f"{DOMAIN}_keypad_{self._entry.entry_id}"
    persistent_notification.async_create(self.hass, _prompt_text(reason, window),
                                         title="Aqara U200 — pulsa el teclado",
                                         notification_id=notif)
    try:
        deadline = time.monotonic() + window
        while time.monotonic() < deadline:
            if await self.client.async_read_front_connection() is True:
                return                            # woke up — proceed
            await asyncio.sleep(3)
        raise AqaraU200PresenceRequiredError(reason)   # level 3
    finally:
        persistent_notification.async_dismiss(self.hass, notif)
```

Then each gated op calls `await self._ensure_presence("delete_user", window=...)`
before the write, inside the operation lock. The voice-OTA path keeps its longer
`LANGUAGE_PRESENCE_WINDOW_SECONDS` (90 s) because the *press must land inside the
OTA manifest window*; data ops just need the panel awake at send time, so a
shorter window (e.g. 30 s) is enough.

### Reusing the event vs. new events
Keep the single `aqara_u200_keypad_press_required` event and carry the `reason`
in its payload; the fingerbot blueprint already triggers on it and presses
regardless of reason (a press is a press). Generalise the blueprint's name/wording
from "language change" to "presence required" so it reads correctly for credential
ops too — no logic change.

## 6. Configuration to make level 1 automatic

Auto-wake only works if the integration knows which entity presses the keypad. Two
options:

- **Blueprint-only (today):** the user wires the bundled automation to their
  fingerbot switch. Zero integration config; works now. Recommended default.
- **Config-option (nicer):** add an optional **"keypad wake switch"** to the
  integration options; when set, `_ensure_presence` can `switch.turn_on` it
  directly (with the same startup delay the blueprint uses) instead of relying on
  an external automation. More discoverable, one less manual step.

Either way, the human-touch fallback (level 2) always applies.

## 7. Recommendation

1. Bump `aqara-ble` to ≥ 1.15.2 (unlocks `read_front_connection`, `delete_user`,
   `read_access_log`).
2. Add `_ensure_presence()` and call it from every presence-gated op; add the
   `AqaraU200PresenceRequiredError` → surfaced as a Repairs issue / service error.
3. Generalise the event/blueprint wording to "presence required".
4. Expose the keypad-free wins that need **no** presence work: `read_access_log`
   as a history source, and `read_front_connection` as a **binary sensor**
   ("Keypad awake") so users can see/trigger on presence themselves.
5. Keep the least-imposition order: **check → auto-wake → ask → fail clearly**.
   Never let a presence-gated write silently no-op.
