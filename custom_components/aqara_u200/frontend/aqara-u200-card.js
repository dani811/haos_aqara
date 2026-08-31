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

    const badges = BADGE_DEFS.map((def) => this._buildBadge(def));

    this.innerHTML = `
      <ha-card header="${this._escape(title)}">
        <div class="aqara-card">
          <div class="aqara-card__illustration-wrap">
            ${this._buildIllustrationSvg(locked)}
            ${badges.map((b) => b.html).join("")}
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
    // Badges stack down the left/right margin, evenly spaced; a short FIXED-
    // length stub (not tied to the SVG's own 0..300 coordinate space, which
    // scales independently of these CSS pixels) points from each badge
    // toward the illustration — precise geometric anchoring would need a
    // post-layout measurement pass (ResizeObserver), left for a later
    // iteration once this is seen rendered in a real dashboard.
    const sameSide = BADGE_DEFS.filter((d) => d.side === def.side);
    const slot = sameSide.indexOf(def);
    const top = 14 + slot * 34;
    const html = `
      <div class="aqara-card__line aqara-card__line--${def.side}" style="top:${top + 12}px;"></div>
      <button class="aqara-card__badge aqara-card__badge--${def.side} ${known ? "" : "is-unknown"}"
              style="top:${top}px;"
              data-more-info-entity="${this._escape(entityId)}"
              title="${this._escape(entityId)}">
        <ha-icon icon="${def.icon}"></ha-icon>
        <span class="aqara-card__badge-label">${this._escape(label)}</span>
      </button>
    `;
    return { html };
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
      <svg class="aqara-card__illustration" viewBox="0 0 300 180" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Aqara U200 illustration">
        <defs>
          <linearGradient id="aqara-panel-face" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="var(--card-background-color, #2b2b2b)"/>
            <stop offset="100%" stop-color="var(--divider-color, #1a1a1a)"/>
          </linearGradient>
          <radialGradient id="aqara-cylinder-face" cx="35%" cy="30%" r="75%">
            <stop offset="0%" stop-color="var(--primary-color)" stop-opacity="0.35"/>
            <stop offset="100%" stop-color="var(--divider-color, #1a1a1a)" stop-opacity="0.9"/>
          </radialGradient>
        </defs>

        <!-- Keypad panel (left piece) -->
        <g transform="translate(20,30)">
          <rect x="0" y="0" width="80" height="120" rx="14" fill="url(#aqara-panel-face)"
                stroke="var(--divider-color)" stroke-width="1.5"/>
          ${[0, 1, 2].flatMap((row) =>
            [0, 1, 2].map(
              (col) =>
                `<circle cx="${20 + col * 20}" cy="${22 + row * 22}" r="7.5"
                          fill="var(--secondary-background-color, #3a3a3a)"
                          stroke="var(--divider-color)" stroke-width="0.75"/>`
            )
          ).join("")}
          <rect x="16" y="94" width="48" height="14" rx="7"
                fill="var(--secondary-background-color, #3a3a3a)"
                stroke="var(--divider-color)" stroke-width="0.75"/>
        </g>

        <!-- Cylinder / deadbolt unit (right piece) -->
        <g transform="translate(150,20)">
          <circle cx="65" cy="70" r="58" fill="url(#aqara-cylinder-face)" stroke="var(--divider-color)" stroke-width="1.5"/>
          <circle cx="65" cy="70" r="40" fill="none" stroke="var(--divider-color)" stroke-width="1" opacity="0.6"/>
          <g class="aqara-card__thumbturn ${cylinderClass}" style="transform-origin: 65px 70px;">
            <rect x="61" y="34" width="8" height="40" rx="4" fill="var(--primary-color)"/>
            <circle cx="65" cy="70" r="7" fill="var(--primary-color)"/>
          </g>
        </g>
      </svg>
    `;
  }

  _css() {
    return `
      .aqara-card { padding: 0 16px 16px; }
      .aqara-card__illustration-wrap {
        position: relative; min-height: 240px; margin: 0 auto; max-width: 560px;
        padding: 0 140px; box-sizing: border-box;
      }
      .aqara-card__illustration { width: 100%; height: auto; display: block; }
      .aqara-card__thumbturn { transition: transform 0.6s cubic-bezier(0.4, 0, 0.2, 1); }
      .aqara-card__thumbturn.is-locked { transform: rotate(0deg); }
      .aqara-card__thumbturn.is-unlocked { transform: rotate(42deg); }
      /* Badges stack in the left/right padding gutters reserved above; the
         stub line is a short fixed-width tick pointing toward the drawing —
         see _buildBadge()'s comment for why it isn't geometrically anchored. */
      .aqara-card__line {
        position: absolute; height: 1px; width: 18px; background: var(--divider-color); pointer-events: none;
      }
      .aqara-card__line--left { left: 122px; }
      .aqara-card__line--right { right: 122px; }
      .aqara-card__badge {
        position: absolute; display: flex; align-items: center; gap: 6px;
        background: var(--card-background-color); border: 1px solid var(--divider-color);
        border-radius: 999px; padding: 4px 10px 4px 6px; font-size: 0.78rem;
        color: var(--primary-text-color); cursor: pointer; max-width: 128px;
      }
      .aqara-card__badge--left { left: 0; }
      .aqara-card__badge--right { right: 0; }
      .aqara-card__badge ha-icon { --mdc-icon-size: 16px; color: var(--secondary-text-color); flex: none; }
      .aqara-card__badge.is-unknown { opacity: 0.5; }
      .aqara-card__badge-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
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
