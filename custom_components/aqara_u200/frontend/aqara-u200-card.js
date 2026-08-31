/**
 * Aqara U200 illustrated card.
 *
 * A stylized illustration of the U200 (keypad accessory + separate
 * pill-shaped lock body/cylinder, matching the real product's two physical
 * pieces) with badges around it showing the lock's confirmed settings.
 * Tapping a badge opens Home Assistant's own more-info dialog for that
 * entity — free, built-in inline editing the moment any of these becomes a
 * select/number entity, no custom per-setting editor to build/maintain here.
 *
 * The card itself DOES ship a minimal GUI config editor (`AqaraU200CardEditor`
 * below, via `static getConfigElement()`) so picking the lock entity doesn't
 * require hand-written YAML — see that class for what it covers.
 *
 * Every badge here is bound to an entity that already exists and is already
 * read over BLE with confirmed bytes (see docs/devices/u200/operations.md in
 * the aqara-ble repo) — nothing speculative, no new protocol assumptions.
 *
 * Sibling entities (battery, volumes, door type, ...) are found from the
 * configured lock entity's device, matched by each entity's stable
 * `translation_key` in the HA entity registry (`hass.entities`) — not by
 * guessing an entity_id slug, which HA derives from the *translated display
 * name* and so doesn't always match the internal key (see `_siblingEntityId`).
 * An explicit `<key>_entity` override in the card config always wins.
 */

// Severity thresholds are deliberately conservative (only flag genuinely low
// battery / genuinely weak signal) — this is a glance-level warning, not a
// diagnostic tool. `null` means "no severity", which renders as the normal
// badge color; only "warn"/"error" get tinted.
function _batterySeverity(stateObj) {
  const value = Number(stateObj.state);
  if (Number.isNaN(value)) return null;
  if (value <= 15) return "error";
  if (value <= 30) return "warn";
  return null;
}

function _rssiSeverity(stateObj) {
  const value = Number(stateObj.state);
  if (Number.isNaN(value)) return null;
  if (value <= -85) return "error";
  if (value <= -70) return "warn";
  return null;
}

const BADGE_DEFS = [
  { key: "battery", domain: "sensor", icon: "mdi:battery", suffix: "%", side: "left", severity: _batterySeverity },
  { key: "rssi", domain: "sensor", icon: "mdi:bluetooth", suffix: " dBm", side: "left", severity: _rssiSeverity },
  { key: "door_type", domain: "sensor", icon: "mdi:door", side: "left" },
  { key: "language", domain: "sensor", icon: "mdi:translate", side: "left" },
  { key: "system_volume", domain: "sensor", icon: "mdi:volume-high", side: "right" },
  // Editable settings (select entities): tapping the badge opens HA's own
  // more-info dialog, which renders a dropdown for a select entity for free
  // — see the file header comment for why this card has no custom editor.
  { key: "alert_volume", domain: "select", icon: "mdi:bell-ring", side: "right" },
  { key: "alarm_volume", domain: "select", icon: "mdi:alarm-light", side: "right" },
  { key: "assist_turn", domain: "binary_sensor", icon: "mdi:rotate-3d-variant", side: "right" },
  { key: "pull_spring", domain: "binary_sensor", icon: "mdi:gesture-tap", side: "right" },
];

// One entry per ff62 event `kind` this card knows how to describe. "unknown"
// is deliberately included — see coordinator.py's _on_realtime_event: an
// unrecognized opcode (which is what a wrong-code/keypad-failure push would
// currently decode as, since the protocol hasn't been taught that opcode
// yet) still fires with this kind and its raw_hex, so the toast can already
// say "something happened" today and will get a precise label the moment a
// live capture teaches decode_event() what the opcode means — no further
// plumbing needed on this side.
const EVENT_TOAST_DEFS = {
  locked: { icon: "mdi:lock-check", label: "Locked" },
  unlocked: { icon: "mdi:lock-open-variant", label: "Unlocked" },
  unknown: { icon: "mdi:alert-circle-outline", label: "Event detected" },
};
const EVENT_TOAST_DURATION_MS = 6000;

class AqaraU200Card extends HTMLElement {
  setConfig(config) {
    if (!config || typeof config !== "object" || !config.entity) {
      throw new Error("Invalid Aqara U200 card configuration: 'entity' (the lock) is required");
    }
    this._config = config;
    this._lastLocked = undefined;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._subscribeToEvents();
    this._render();
  }

  // Dreame's own map card uses exactly this pattern — a small floating toast
  // over the card's own content, not a full dialog or a separate entity —
  // for "something happened" moments (errors, faults). Same idea here: an
  // ff62 event doesn't need its own dedicated notification entity, just a
  // transient badge over the illustration whenever aqara_u200_event fires
  // for this card's device.
  connectedCallback() {
    this._subscribeToEvents();
  }

  disconnectedCallback() {
    if (this._unsubscribeEvents) {
      this._unsubscribeEvents();
      this._unsubscribeEvents = undefined;
    }
    if (this._toastTimer) {
      clearTimeout(this._toastTimer);
      this._toastTimer = undefined;
    }
  }

  _subscribeToEvents() {
    // Idempotent: hass is reassigned on every state update, but the
    // subscription itself only needs to happen once per connected instance.
    if (this._unsubscribeEvents || this._subscribingEvents || !this._hass?.connection) return;
    this._subscribingEvents = true;
    this._hass.connection
      .subscribeEvents((event) => this._handleBusEvent(event), "aqara_u200_event")
      .then((unsubscribe) => {
        this._unsubscribeEvents = unsubscribe;
      })
      .catch(() => {
        // Best-effort: no toast feature if the connection can't subscribe
        // (e.g. a restricted/limited-access frontend session). The rest of
        // the card works fine without it.
      })
      .finally(() => {
        this._subscribingEvents = false;
      });
  }

  // The lock entity's own registry entry has no config_entry_id field at
  // all (confirmed live 2026-08-31: it carries device_id, translation_key,
  // etc., but not the config entry) — that lives one hop further, on the
  // device registry entry, as `primary_config_entry`. Matching directly
  // against `entry.config_entry_id` (both sides undefined) silently always
  // "matched" in an early test; this is the real path.
  _thisDeviceEntryId() {
    const entry = this._hass?.entities?.[this._config.entity];
    const device = entry ? this._hass?.devices?.[entry.device_id] : undefined;
    return device?.primary_config_entry;
  }

  _handleBusEvent(event) {
    if (!this._config) return;
    const entryId = this._thisDeviceEntryId();
    if (!entryId || event.data.entry_id !== entryId) return; // not this device
    const def = EVENT_TOAST_DEFS[event.data.kind];
    if (!def) return;
    this._toast = {
      icon: def.icon,
      label: def.label,
      source: event.data.source,
      title: event.data.kind === "unknown" ? `raw: ${event.data.raw_hex}` : "",
    };
    if (this._toastTimer) clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => {
      this._toast = undefined;
      this._toastTimer = undefined;
      this._render();
    }, EVENT_TOAST_DURATION_MS);
    this._render();
  }

  getCardSize() {
    return 6;
  }

  getGridOptions() {
    return { columns: 8, rows: 6, min_columns: 6, min_rows: 5 };
  }

  // GUI card editor (Settings → Dashboards → Edit → pick this card, or the
  // "Show code editor" toggle's opposite) — before this, the only way to set
  // the required `entity` was to hand-write YAML. Returning a custom element
  // here is the whole contract; HA mounts it, feeds it `hass`/`config`, and
  // listens for `config-changed` events (see AqaraU200CardEditor below).
  static getConfigElement() {
    return document.createElement("aqara-u200-card-editor");
  }

  // Pre-fills a sane default (the first lock entity found) when a user adds
  // this card from the picker, instead of handing them a blank/broken config.
  static getStubConfig(hass) {
    const lockEntityId = Object.keys(hass.states).find((id) => id.startsWith("lock."));
    return { entity: lockEntityId || "" };
  }

  // --- entity resolution -----------------------------------------------

  _slug() {
    const entityId = this._config.entity;
    const dot = entityId.indexOf(".");
    return dot === -1 ? entityId : entityId.slice(dot + 1);
  }

  // Sibling entities share this device (same config entry) but HA generates
  // their entity_id from the entity's *translated display name*, not the
  // internal Python `key` (e.g. `rssi`'s name is "Signal strength", so its
  // entity_id is `..._signal_strength`, not `..._rssi`) — guessing the slug
  // from `key` alone is unreliable. `hass.entities` (the entity-registry
  // view the frontend already has) carries each entity's stable
  // `translation_key`, which DOES match `key` exactly (it is the literal
  // string passed to `_attr_translation_key` in the integration) — matching
  // on that plus a shared `device_id` is reliable across renames/locales.
  // Falls back to the naive slug guess only if `hass.entities` isn't
  // populated yet (a first render right after login) or an explicit config
  // override is not given.
  _siblingEntityId(def) {
    const override = this._config[`${def.key}_entity`];
    if (override) return override;

    const registry = this._hass.entities;
    const lockEntry = registry?.[this._config.entity];
    const deviceId = lockEntry?.device_id;
    if (registry && deviceId) {
      for (const [entityId, entry] of Object.entries(registry)) {
        if (entry.device_id === deviceId && entry.translation_key === def.key) {
          return entityId;
        }
      }
    }
    return `${def.domain}.${this._slug()}_${def.key}`;
  }

  _state(entityId) {
    return entityId ? this._hass.states[entityId] : undefined;
  }

  // --- rendering ---------------------------------------------------------

  _render() {
    if (!this._config || !this._hass) return;

    const entityId = this._config.entity;
    const lockState = this._state(entityId);
    const title = this._config.name || lockState?.attributes?.friendly_name || "Aqara U200";
    const rawState = lockState?.state;
    const locked = rawState === "locked" ? true : rawState === "unlocked" ? false : null;
    const controlReady = Boolean(lockState);

    const leftBadges = BADGE_DEFS.filter((d) => d.side === "left").map((def) => this._buildBadge(def));
    const rightBadges = BADGE_DEFS.filter((d) => d.side === "right").map((def) => this._buildBadge(def));

    this.innerHTML = `
      <ha-card header="${this._escape(title)}">
        <div class="aqara-card">
          ${this._buildToast()}
          <div class="aqara-card__layout">
            <div class="aqara-card__badges aqara-card__badges--left">${leftBadges.join("")}</div>
            <div class="aqara-card__illustration-wrap">${this._buildIllustrationSvg(locked)}</div>
            <div class="aqara-card__badges aqara-card__badges--right">${rightBadges.join("")}</div>
          </div>
          <div class="aqara-card__actions">
            <button data-action="lock" ${controlReady ? "" : "disabled"}>
              <ha-icon icon="mdi:lock"></ha-icon> Lock
            </button>
            <button data-action="unlock" ${controlReady ? "" : "disabled"}>
              <ha-icon icon="mdi:lock-open-variant"></ha-icon> Unlock
            </button>
          </div>
          ${
            controlReady
              ? `<div class="aqara-card__activity">${this._escape(this._activityLabel(lockState))}</div>`
              : '<div class="aqara-card__notice">Control will be enabled when the HA lock entity is available.</div>'
          }
        </div>
        <style>${this._css()}</style>
      </ha-card>
    `;

    this.querySelectorAll("button[data-action]").forEach((button) => {
      button.addEventListener("click", () => this._callLockService(button.dataset.action));
    });
    this.querySelectorAll("[data-more-info-entity]").forEach((el) => {
      el.addEventListener("click", () => this._openMoreInfo(el.dataset.moreInfoEntity));
    });

    this._lastLocked = locked;
  }

  _buildBadge(def) {
    const entityId = this._siblingEntityId(def);
    const stateObj = this._state(entityId);
    const known = Boolean(stateObj) && stateObj.state !== "unavailable" && stateObj.state !== "unknown";
    const label = this._badgeLabel(def, stateObj);
    // Severity tint (low battery / weak signal) only applies once we actually
    // have a real reading — never guess a color for an unread "–" badge.
    const severity = known && def.severity ? def.severity(stateObj) : null;
    const severityClass = severity ? ` is-${severity}` : "";
    // Each side is a flex column (see _css()) — no absolute positioning, no
    // fixed-pixel gutters. A card narrower than the badges' natural width
    // (confirmed live: some dashboards render this as a ~330px popup) just
    // wraps/shrinks normally instead of squeezing the illustration to
    // near-zero, which is what a fixed-padding gutter did.
    return `
      <button class="aqara-card__badge ${known ? "" : "is-unknown"}${severityClass}"
              data-more-info-entity="${this._escape(entityId)}"
              title="${this._escape(entityId)}">
        <ha-icon icon="${def.icon}"></ha-icon>
        <span class="aqara-card__badge-label">${this._escape(label)}</span>
      </button>
    `;
  }

  _badgeLabel(def, stateObj) {
    if (!stateObj || stateObj.state === "unavailable" || stateObj.state === "unknown") {
      return "–"; // en dash — "not read yet", never a guessed value
    }
    if (def.domain === "binary_sensor") {
      return stateObj.state === "on" ? "On" : "Off";
    }
    const suffix = def.suffix || "";
    return `${stateObj.state}${suffix}`;
  }

  // Dreame-style transient toast for a live ff62 event (see coordinator.py's
  // _on_realtime_event and EVENT_TOAST_DEFS above). Empty string when there's
  // nothing to show — kept inline in _render()'s template rather than a
  // separate conditional block, matching how _activityLabel/notice do it.
  _buildToast() {
    if (!this._toast) return "";
    const { icon, label, source, title } = this._toast;
    const text = source ? `${label} (${source})` : label;
    return `
      <div class="aqara-card__toast" title="${this._escape(title || "")}">
        <ha-icon icon="${icon}"></ha-icon>
        <span>${this._escape(text)}</span>
      </div>
    `;
  }

  // Lightweight "recent activity" line — just the lock's own last_changed,
  // already free on every state object, no new entity/event-subscription
  // machinery needed. Recomputed on every render (i.e. every hass update),
  // not on its own timer — good enough for a glance, not a stopwatch.
  _activityLabel(lockState) {
    if (!lockState?.last_changed) return "";
    const seconds = (Date.now() - new Date(lockState.last_changed).getTime()) / 1000;
    const action =
      lockState.state === "locked" ? "Locked" : lockState.state === "unlocked" ? "Unlocked" : "Changed";
    return `${action} ${this._formatRelative(seconds)}`;
  }

  _formatRelative(seconds) {
    const language = this._hass?.locale?.language || this._hass?.language || "en";
    const abs = Math.abs(seconds);
    let value;
    let unit;
    if (abs < 60) {
      value = seconds;
      unit = "second";
    } else if (abs < 3600) {
      value = seconds / 60;
      unit = "minute";
    } else if (abs < 86400) {
      value = seconds / 3600;
      unit = "hour";
    } else {
      value = seconds / 86400;
      unit = "day";
    }
    try {
      return new Intl.RelativeTimeFormat(language, { numeric: "auto" }).format(-Math.round(value), unit);
    } catch {
      return `${Math.max(0, Math.round(value))} ${unit}(s) ago`;
    }
  }

  _buildIllustrationSvg(locked) {
    // `locked === null` (never read yet) renders in the unlocked rotation as
    // a neutral default — it is a drawing, not a state claim; the real state
    // is only ever what `lock.<slug>`'s own text says.
    const cylinderClass = locked ? "is-locked" : "is-unlocked";
    // The real U200 cylinder turns two full revolutions, not a subtle nudge —
    // only play that spin on an actual known->known transition (never on
    // first render, and never when `locked` merely stays the same across an
    // unrelated hass update, e.g. a battery tick). `this._lastLocked` is
    // still the PRE-render value here — `_render()` updates it only after
    // building this markup — so comparing against it directly tells apart a
    // real flip from a same-state re-render.
    const isRealTransition =
      this._lastLocked !== undefined &&
      this._lastLocked !== null &&
      locked !== null &&
      locked !== this._lastLocked;
    const spinClass = isRealTransition ? (locked ? " is-spinning-to-locked" : " is-spinning-to-unlocked") : "";
    return `
      <svg class="aqara-card__illustration" viewBox="0 0 196 188" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Aqara U200 illustration">
        <defs>
          <radialGradient id="aqara-cylinder-face" cx="35%" cy="30%" r="75%">
            <stop offset="0%" stop-color="var(--primary-color)" stop-opacity="0.5"/>
            <stop offset="100%" stop-color="color-mix(in srgb, var(--primary-text-color) 14%, var(--card-background-color))"/>
          </radialGradient>
        </defs>

        <!--
          Redrawn 2026-08-31 from an official Aqara U200 product photo the
          user shared (supersedes the earlier abstract 3x3-grid guess, which
          was wrong). Both pieces use the SAME capsule primitive — a fully
          rounded pill, rx = half width — matching the real hardware: the
          keypad is a slim capsule, the lock body a wide one whose rounded
          top reads as the turn knob's circular face. Keypad layout is 2
          columns x 5 rows (1-9, 0), a lock/confirm function row below it,
          and the fingerprint sensor sits alone at the base — it is NOT part
          of the button grid. No digit or "(NFC)" labels are drawn (they'd
          be unreadable at this size); this stays a simplified icon, not a
          rendered photo.
        -->

        <!-- Keypad (left piece) -->
        <g transform="translate(8,8)">
          <rect x="0" y="0" width="70" height="172" rx="35"
                fill="color-mix(in srgb, var(--primary-text-color) 10%, var(--card-background-color))"
                stroke="color-mix(in srgb, var(--primary-text-color) 35%, transparent)" stroke-width="1.5"/>
          ${[0, 1, 2, 3, 4]
            .flatMap((row) =>
              [0, 1].map(
                (col) => `<circle cx="${21 + col * 28}" cy="${28 + row * 22}" r="7"
                          fill="color-mix(in srgb, var(--primary-text-color) 16%, var(--card-background-color))"/>`
              )
            )
            .join("")}
          <!-- Function row: lock (outline) · confirm (accent + checkmark) -->
          <circle cx="21" cy="140" r="7" fill="none"
                  stroke="color-mix(in srgb, var(--primary-text-color) 45%, transparent)" stroke-width="1.5"/>
          <circle cx="49" cy="140" r="7" fill="var(--primary-color)"/>
          <path d="M 46 140 l 2 2 l 4.5 -4.5" fill="none" stroke="var(--text-primary-color, #fff)"
                stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>
          <!-- Fingerprint sensor — standalone at the base, not a grid key -->
          <circle cx="35" cy="160" r="9" fill="none"
                  stroke="color-mix(in srgb, var(--primary-text-color) 45%, transparent)" stroke-width="1.5"/>
        </g>

        <!-- Lock body (right piece) — wide capsule; its rounded top is the turn knob face -->
        <g transform="translate(96,8)">
          <rect x="0" y="0" width="92" height="172" rx="46" fill="url(#aqara-cylinder-face)"
                stroke="color-mix(in srgb, var(--primary-text-color) 35%, transparent)" stroke-width="1.5"/>
          <circle cx="46" cy="46" r="38" fill="none" stroke="color-mix(in srgb, var(--primary-text-color) 35%, transparent)" stroke-width="1" opacity="0.6"/>
          <!-- Grip: two rounded bars with a center channel, like the real thumbturn.
               The small dot above the bars breaks their 180°-symmetry — without
               it, spinning the bars two full turns would look identical to
               spinning them a quarter-turn, since a mirrored bar pair reads the
               same every 180°. The dot is what actually lets the eye register
               "this went around twice". -->
          <g class="aqara-card__thumbturn ${cylinderClass}${spinClass}" style="transform-origin: 46px 46px;">
            <rect x="36" y="26" width="7" height="40" rx="3.5" fill="var(--primary-color)"/>
            <rect x="49" y="26" width="7" height="40" rx="3.5" fill="var(--primary-color)"/>
            <circle cx="46" cy="20" r="3" fill="var(--primary-color)"/>
          </g>
          <circle class="aqara-card__led ${cylinderClass}" cx="46" cy="155" r="3"/>
        </g>
      </svg>
    `;
  }

  _css() {
    return `
      .aqara-card { padding: 0 16px 16px; position: relative; }
      /* Floating toast for a live event — same pattern as the Dreame Vacuum
         card's own .toast (top-center, absolute, over the card content),
         translated to this card's theme tokens instead of Dreame's
         --surface-bg/--border-color. Auto-dismissed by _handleBusEvent's
         timer, not by CSS — this is just the resting visual state. */
      .aqara-card__toast {
        position: absolute; top: 4px; left: 50%; transform: translateX(-50%);
        display: flex; align-items: center; gap: 6px; z-index: 1;
        background: var(--card-background-color); border: 1px solid var(--divider-color);
        border-radius: 999px; padding: 6px 14px; font-size: 0.82rem;
        color: var(--primary-text-color); box-shadow: var(--ha-card-box-shadow, 0 2px 6px rgba(0,0,0,.2));
        max-width: 90%; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
      }
      .aqara-card__toast ha-icon { --mdc-icon-size: 16px; color: var(--primary-color); flex: none; }
      /* Three real grid columns (badges | illustration | badges) — no fixed-
         pixel gutters, no absolute positioning. Confirmed live 2026-08-31:
         a fixed 140px gutter squeezed the illustration to near-zero width
         on a narrow (~330px) card/dialog; minmax()'d fr columns instead
         give the illustration a guaranteed fair share at ANY card width. */
      .aqara-card__layout {
        display: grid; grid-template-columns: minmax(52px, 1fr) minmax(120px, 2.6fr) minmax(52px, 1fr);
        align-items: center; gap: 8px; min-height: 200px;
      }
      .aqara-card__badges { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
      .aqara-card__badges--left { align-items: flex-start; }
      .aqara-card__badges--right { align-items: flex-end; }
      .aqara-card__illustration-wrap { min-width: 0; }
      .aqara-card__illustration { width: 100%; height: auto; display: block; }
      /* Locking turns left (negative/CCW), unlocking turns right (positive/CW)
         from a shared vertical rest point — not just two arbitrary angles —
         so the direction of turn itself carries the open/close meaning,
         matching how a real thumbturn reads at a glance. The resting angles
         (±45deg) are just an artistic "it's turned" cue, unchanged from
         before; is-spinning-to-* (below) plays the real U200's actual two
         full revolutions on top of that same resting pose, only on a genuine
         state flip (see _buildIllustrationSvg's isRealTransition). A plain
         CSS transition can't do this reliably here — this card replaces its
         whole innerHTML on every render, so there is no "previous style" on
         the DOM element for a transition to interpolate from; a @keyframes
         animation is self-contained and always plays its own from->to path
         regardless of DOM history. */
      .aqara-card__thumbturn.is-locked { transform: rotate(-45deg); }
      .aqara-card__thumbturn.is-unlocked { transform: rotate(45deg); }
      .aqara-card__thumbturn.is-spinning-to-locked {
        animation: aqara-spin-to-locked 1.6s cubic-bezier(0.4, 0, 0.2, 1) forwards;
      }
      .aqara-card__thumbturn.is-spinning-to-unlocked {
        animation: aqara-spin-to-unlocked 1.6s cubic-bezier(0.4, 0, 0.2, 1) forwards;
      }
      /* -765deg / 765deg = ±45deg (the normal resting pose) plus two extra
         full turns (720deg) — the literal degree value is what the browser
         animates through, so a bigger number here really does spin further,
         even though it lands on the same visual angle as ±45deg. */
      @keyframes aqara-spin-to-locked {
        from { transform: rotate(45deg); }
        to { transform: rotate(-765deg); }
      }
      @keyframes aqara-spin-to-unlocked {
        from { transform: rotate(-45deg); }
        to { transform: rotate(765deg); }
      }
      @media (prefers-reduced-motion: reduce) {
        .aqara-card__thumbturn.is-spinning-to-locked,
        .aqara-card__thumbturn.is-spinning-to-unlocked {
          animation: none;
        }
      }
      /* Small status dot near the base of the lock body — a cheap extra
         state cue (amber = locked, accent = unlocked) that costs one circle,
         not a whole new shape. */
      .aqara-card__led { transition: fill 0.3s ease; }
      .aqara-card__led.is-locked { fill: var(--warning-color, #ffa600); }
      .aqara-card__led.is-unlocked { fill: var(--primary-color); }
      .aqara-card__badge {
        display: flex; align-items: center; gap: 6px; width: 100%; min-width: 0;
        background: var(--card-background-color); border: 1px solid var(--divider-color);
        border-radius: 999px; padding: 4px 10px 4px 6px; font-size: 0.78rem;
        color: var(--primary-text-color); cursor: pointer;
        transition: transform 0.15s ease, background-color 0.15s ease;
      }
      /* Tap feedback — a quick, purely-CSS press animation. No JS timer/class
         bookkeeping needed: :active covers the whole "finger down" duration,
         which for a tap is exactly the moment that needs to feel responsive. */
      .aqara-card__badge:active { transform: scale(0.93); }
      .aqara-card__badge ha-icon { --mdc-icon-size: 16px; color: var(--secondary-text-color); flex: none; }
      .aqara-card__badge.is-unknown { opacity: 0.5; }
      /* Severity tint — only ever applied to a badge with a real reading
         (see _buildBadge), so this never colors an unread "–" badge. Uses
         HA's own --warning-color/--error-color theme tokens, not hardcoded
         hex, so it follows the user's theme like everything else here. */
      .aqara-card__badge.is-warn ha-icon { color: var(--warning-color, #ffa600); }
      .aqara-card__badge.is-error ha-icon { color: var(--error-color, #db4437); }
      .aqara-card__badge-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
      .aqara-card__actions { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 12px; }
      .aqara-card__actions button {
        min-height: 40px; border: 0; border-radius: 10px; cursor: pointer;
        background: var(--primary-color); color: var(--text-primary-color, #fff);
        display: flex; align-items: center; justify-content: center; gap: 6px;
      }
      .aqara-card__actions button:disabled { cursor: not-allowed; opacity: .5; }
      .aqara-card__notice { margin-top: 12px; color: var(--secondary-text-color); font-size: 0.9rem; }
      .aqara-card__activity {
        margin-top: 10px; text-align: center; color: var(--secondary-text-color); font-size: 0.8rem;
      }
    `;
  }

  // --- actions -------------------------------------------------------------

  _callLockService(action) {
    const entityId = this._config?.entity;
    if (!entityId || !this._hass?.states?.[entityId]) return;
    this._hass.callService("lock", action, { entity_id: entityId });
  }

  _openMoreInfo(entityId) {
    if (!entityId) return;
    this.dispatchEvent(
      new CustomEvent("hass-more-info", {
        detail: { entityId },
        bubbles: true,
        composed: true,
      })
    );
  }

  _escape(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }
}

// --- GUI config editor ------------------------------------------------
//
// A minimal visual editor: pick the lock entity (required) and an optional
// display name. Per-badge entity overrides (`<key>_entity`) stay YAML-only
// for now — they're an escape hatch for a mismatched entity registry, not
// something most users need — but the one field everyone needs (which lock)
// no longer requires opening the raw YAML editor at all.
class AqaraU200CardEditor extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _render() {
    // HA's editor lifecycle doesn't guarantee setConfig() runs before hass is
    // first assigned — confirmed live 2026-08-31: assigning .hass on a freshly
    // created editor (before .setConfig()) threw here because _config was
    // still undefined. Guard on both, not just hass.
    if (!this._hass || !this._config) return;

    if (!this._built) {
      this.innerHTML = `
        <div class="aqara-editor">
          <ha-entity-picker id="entity" label="Lock entity (required)" allow-custom-entity></ha-entity-picker>
          <ha-textfield id="name" label="Card name (optional)"></ha-textfield>
        </div>
        <style>
          .aqara-editor { display: flex; flex-direction: column; gap: 16px; padding: 8px 0; }
        </style>
      `;
      this._entityPicker = this.querySelector("#entity");
      this._nameField = this.querySelector("#name");
      this._entityPicker.includeDomains = ["lock"];
      this._entityPicker.addEventListener("value-changed", (ev) => {
        ev.stopPropagation();
        this._emitConfig({ entity: ev.detail.value });
      });
      this._nameField.addEventListener("input", (ev) => {
        this._emitConfig({ name: ev.target.value || undefined });
      });
      this._built = true;
    }

    this._entityPicker.hass = this._hass;
    this._entityPicker.value = this._config.entity || "";
    this._nameField.value = this._config.name || "";
  }

  _emitConfig(patch) {
    const next = { ...this._config, ...patch };
    if (next.name === undefined) delete next.name;
    this._config = next;
    this.dispatchEvent(
      new CustomEvent("config-changed", {
        detail: { config: next },
        bubbles: true,
        composed: true,
      })
    );
  }
}

customElements.define("aqara-u200-card-editor", AqaraU200CardEditor);
customElements.define("aqara-u200-card", AqaraU200Card);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "aqara-u200-card",
  name: "Aqara U200",
  description: "Illustrated card for the Aqara U200 BLE integration — lock/unlock, and every confirmed setting as a badge around the drawing.",
  preview: true,
});
