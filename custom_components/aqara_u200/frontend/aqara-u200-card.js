class AqaraU200Card extends HTMLElement {
  setConfig(config) {
    if (!config || typeof config !== "object") {
      throw new Error("Invalid Aqara U200 card configuration");
    }
    this._config = config;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    return 3;
  }

  getGridOptions() {
    return { columns: 6, rows: 3, min_columns: 4, min_rows: 2 };
  }

  _render() {
    if (!this._config || !this._hass) return;

    const entityId = this._config.entity;
    const stateObj = entityId ? this._hass.states[entityId] : undefined;
    const title = this._config.name || stateObj?.attributes?.friendly_name || "Aqara U200";
    const state = stateObj?.state || "not_configured";
    const controlReady = Boolean(stateObj && entityId?.startsWith("lock."));

    this.innerHTML = `
      <ha-card header="${this._escape(title)}">
        <div class="aqara-u200-card__content">
          <div class="aqara-u200-card__state">
            <ha-icon icon="mdi:door-closed-lock"></ha-icon>
            <span>${this._escape(state)}</span>
          </div>
          <div class="aqara-u200-card__actions">
            <button data-action="lock" ${controlReady ? "" : "disabled"}>Lock</button>
            <button data-action="unlock" ${controlReady ? "" : "disabled"}>Unlock</button>
          </div>
          ${
            controlReady
              ? ""
              : '<div class="aqara-u200-card__notice">Control will be enabled when the HA lock entity is available.</div>'
          }
        </div>
        <style>
          .aqara-u200-card__content { padding: 0 16px 16px; }
          .aqara-u200-card__state { display: flex; align-items: center; gap: 10px; margin-bottom: 16px; }
          .aqara-u200-card__actions { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
          .aqara-u200-card__actions button { min-height: 40px; border: 0; border-radius: 10px; cursor: pointer; }
          .aqara-u200-card__actions button:disabled { cursor: not-allowed; opacity: .5; }
          .aqara-u200-card__notice { margin-top: 12px; color: var(--secondary-text-color); font-size: 0.9rem; }
        </style>
      </ha-card>
    `;

    this.querySelectorAll("button[data-action]").forEach((button) => {
      button.addEventListener("click", () => this._callLockService(button.dataset.action));
    });
  }

  _callLockService(action) {
    const entityId = this._config?.entity;
    if (!entityId || !this._hass?.states?.[entityId]) return;
    this._hass.callService("lock", action, { entity_id: entityId });
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
  description: "Bundled card for the Aqara U200 BLE integration",
  preview: true,
});
