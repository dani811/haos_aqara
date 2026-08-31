/**
 * Aqara U200 illustrated card.
 *
 * A stylized isometric illustration of the U200 (keypad panel + separate
 * round cylinder/deadbolt unit, matching the real product's two physical
 * pieces) with badges around it showing the lock's confirmed settings, each
 * connected to the drawing by a thin line. Tapping a badge opens Home
 * Assistant's own more-info dialog for that entity — free, built-in inline
 * editing the moment any of these becomes a select/number entity, no custom
 * editor UI to build/maintain here.
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

const BADGE_DEFS = [
  { key: "battery", domain: "sensor", icon: "mdi:battery", suffix: "%", side: "left" },
  { key: "rssi", domain: "sensor", icon: "mdi:bluetooth", suffix: " dBm", side: "left" },
  { key: "door_type", domain: "sensor", icon: "mdi:door", side: "left" },
  { key: "language", domain: "sensor", icon: "mdi:translate", side: "left" },
  { key: "system_volume", domain: "sensor", icon: "mdi:volume-high", side: "right" },
  { key: "alert_volume", domain: "sensor", icon: "mdi:bell-ring", side: "right" },
  { key: "alarm_volume", domain: "sensor", icon: "mdi:alarm-light", side: "right" },
  { key: "assist_turn", domain: "binary_sensor", icon: "mdi:rotate-3d-variant", side: "right" },
  { key: "pull_spring", domain: "binary_sensor", icon: "mdi:gesture-tap", side: "right" },
];

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
    this._render();
  }

  getCardSize() {
    return 6;
  }

  getGridOptions() {
    return { columns: 8, rows: 6, min_columns: 6, min_rows: 5 };
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
              ? ""
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
    // Each side is a flex column (see _css()) — no absolute positioning, no
    // fixed-pixel gutters. A card narrower than the badges' natural width
    // (confirmed live: some dashboards render this as a ~330px popup) just
    // wraps/shrinks normally instead of squeezing the illustration to
    // near-zero, which is what a fixed-padding gutter did.
    return `
      <button class="aqara-card__badge ${known ? "" : "is-unknown"}"
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

  _buildIllustrationSvg(locked) {
    // `locked === null` (never read yet) renders in the unlocked rotation as
    // a neutral default — it is a drawing, not a state claim; the real state
    // is only ever what `lock.<slug>`'s own text says.
    const cylinderClass = locked ? "is-locked" : "is-unlocked";
    return `
      <svg class="aqara-card__illustration" viewBox="8 4 200 172" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Aqara U200 illustration">
        <defs>
          <linearGradient id="aqara-panel-face" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="color-mix(in srgb, var(--primary-text-color) 10%, var(--card-background-color))"/>
            <stop offset="100%" stop-color="color-mix(in srgb, var(--primary-text-color) 24%, var(--card-background-color))"/>
          </linearGradient>
          <radialGradient id="aqara-cylinder-face" cx="35%" cy="30%" r="75%">
            <stop offset="0%" stop-color="var(--primary-color)" stop-opacity="0.55"/>
            <stop offset="100%" stop-color="color-mix(in srgb, var(--primary-text-color) 14%, var(--card-background-color))"/>
          </radialGradient>
        </defs>

        <!--
          Fills use color-mix() against --primary-text-color instead of
          --secondary-background-color: confirmed live 2026-08-31 that on at
          least one real HA theme --secondary-background-color resolves to a
          near-white, half-transparent value (rgba(245,245,245,0.5)) that is
          nearly invisible against a light card — the beta.3 "fix" wasn't
          enough. --primary-text-color is always a solid, opaque color by
          design, so mixing a small percentage of it into the card background
          guarantees real, theme-independent contrast on both light and dark.
        -->
        <!--
          Shapes approximate the real U200's two physical pieces (see the
          product photo the user pointed out beta.4's abstract "circle +
          rounded rect" didn't resemble): a tall pill-shaped lock body with a
          round thumbturn housing near its top, and a separate keypad
          accessory whose bottom row is [fingerprint] [0] [checkmark], not a
          single wide button. Still a simplified icon, not a rendered photo.
        -->
        <!-- Keypad accessory (left piece) -->
        <g transform="translate(14,14)">
          <rect x="0" y="0" width="74" height="152" rx="16" fill="url(#aqara-panel-face)"
                stroke="color-mix(in srgb, var(--primary-text-color) 35%, transparent)" stroke-width="1.5"/>
          ${["1", "2", "3", "4", "5", "6", "7", "8", "9"]
            .map((label, i) => {
              const col = i % 3;
              const row = Math.floor(i / 3);
              return `<circle cx="${18 + col * 19}" cy="${24 + row * 26}" r="8"
                          fill="color-mix(in srgb, var(--primary-text-color) 16%, var(--card-background-color))"
                          stroke="color-mix(in srgb, var(--primary-text-color) 35%, transparent)" stroke-width="0.75"/>`;
            })
            .join("")}
          <!-- Bottom row: fingerprint/NFC sensor · 0 · confirm (checkmark) -->
          <rect x="10" y="120" width="16" height="16" rx="4"
                fill="color-mix(in srgb, var(--primary-text-color) 16%, var(--card-background-color))"
                stroke="color-mix(in srgb, var(--primary-text-color) 35%, transparent)" stroke-width="0.75"/>
          <circle cx="37" cy="128" r="8"
                  fill="color-mix(in srgb, var(--primary-text-color) 16%, var(--card-background-color))"
                  stroke="color-mix(in srgb, var(--primary-text-color) 35%, transparent)" stroke-width="0.75"/>
          <circle cx="56" cy="128" r="8" fill="var(--primary-color)"/>
          <path d="M 52.5 128 l 2.5 2.5 l 5 -5" fill="none" stroke="var(--text-primary-color, #fff)"
                stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
        </g>

        <!-- Lock body / cylinder unit (right piece) — tall pill shape -->
        <g transform="translate(130,10)">
          <rect x="0" y="0" width="72" height="160" rx="36" fill="url(#aqara-cylinder-face)"
                stroke="color-mix(in srgb, var(--primary-text-color) 35%, transparent)" stroke-width="1.5"/>
          <circle cx="36" cy="52" r="34" fill="none" stroke="color-mix(in srgb, var(--primary-text-color) 35%, transparent)" stroke-width="1" opacity="0.6"/>
          <g class="aqara-card__thumbturn ${cylinderClass}" style="transform-origin: 36px 52px;">
            <rect x="32" y="22" width="8" height="34" rx="4" fill="var(--primary-color)"/>
            <circle cx="36" cy="52" r="7" fill="var(--primary-color)"/>
          </g>
        </g>
      </svg>
    `;
  }

  _css() {
    return `
      .aqara-card { padding: 0 16px 16px; }
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
         matching how a real thumbturn reads at a glance. */
      .aqara-card__thumbturn { transition: transform 0.6s cubic-bezier(0.4, 0, 0.2, 1); }
      .aqara-card__thumbturn.is-locked { transform: rotate(-45deg); }
      .aqara-card__thumbturn.is-unlocked { transform: rotate(45deg); }
      .aqara-card__badge {
        display: flex; align-items: center; gap: 6px; width: 100%; min-width: 0;
        background: var(--card-background-color); border: 1px solid var(--divider-color);
        border-radius: 999px; padding: 4px 10px 4px 6px; font-size: 0.78rem;
        color: var(--primary-text-color); cursor: pointer;
      }
      .aqara-card__badge ha-icon { --mdc-icon-size: 16px; color: var(--secondary-text-color); flex: none; }
      .aqara-card__badge.is-unknown { opacity: 0.5; }
      .aqara-card__badge-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
      .aqara-card__actions { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 12px; }
      .aqara-card__actions button {
        min-height: 40px; border: 0; border-radius: 10px; cursor: pointer;
        background: var(--primary-color); color: var(--text-primary-color, #fff);
        display: flex; align-items: center; justify-content: center; gap: 6px;
      }
      .aqara-card__actions button:disabled { cursor: not-allowed; opacity: .5; }
      .aqara-card__notice { margin-top: 12px; color: var(--secondary-text-color); font-size: 0.9rem; }
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

customElements.define("aqara-u200-card", AqaraU200Card);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "aqara-u200-card",
  name: "Aqara U200",
  description: "Illustrated card for the Aqara U200 BLE integration — lock/unlock, and every confirmed setting as a badge around the drawing.",
  preview: true,
});
