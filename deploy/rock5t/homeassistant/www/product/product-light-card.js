import { actionCss, hostCss, friendly, run } from "./product-style.js";

class ProductLightCard extends HTMLElement {
  setConfig(config) {
    if (!config.entity) throw new Error("Set the light or light group.");
    this._config = config;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this._built = false;
    this._dragging = new Set();
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) this._build();
    this._paint();
  }

  _build() {
    this._built = true;
    this._key = null;
    this.shadowRoot.innerHTML = `
      <style>
        ${hostCss}
        ${actionCss}
        h2 {
          margin: 0 0 4px;
          font-size: 13px;
          font-weight: 500;
          letter-spacing: 0.04em;
          color: var(--secondary-text-color);
        }
        .empty { margin: 8px 0 0; font-size: 15px; color: var(--secondary-text-color); }
        .row {
          display: grid;
          grid-template-columns: 1fr auto;
          gap: 4px 12px;
          align-items: center;
          padding: 12px 0;
          border-top: 1px solid var(--divider-color);
        }
        .row:first-of-type { border-top: 0; }
        .name { font-size: 15px; }
        input[type="range"] {
          grid-column: 1 / -1;
          width: 100%;
          accent-color: var(--product-action, #8a6a32);
        }
      </style>
      <ha-card>
        <h2>Lights</h2>
        <div class="rows"></div>
        <p class="error"></p>
      </ha-card>
    `;
    this._rows = this.shadowRoot.querySelector(".rows");
    this._error = this.shadowRoot.querySelector(".error");
  }

  _members() {
    const state = this._hass.states[this._config.entity];
    if (!state) return null;
    const listed = state.attributes && state.attributes.entity_id;
    if (Array.isArray(listed)) return listed;
    return [this._config.entity];
  }

  _paint() {
    const members = this._members();
    const key = members ? members.join("\n") : "";
    if (key !== this._key) {
      this._key = key;
      this._renderRows(members);
    }
    if (!members) return;
    for (const id of members) this._paintRow(id);
  }

  _renderRows(members) {
    this._rows.replaceChildren();
    if (!members || !members.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No lights yet.";
      this._rows.append(empty);
      return;
    }
    for (const id of members) {
      const row = document.createElement("div");
      row.className = "row";
      row.dataset.entity = id;
      const name = document.createElement("div");
      name.className = "name";
      const button = document.createElement("button");
      button.className = "action";
      button.type = "button";
      button.addEventListener("click", () => this._toggle(id, button));
      const slider = document.createElement("input");
      slider.type = "range";
      slider.min = "0";
      slider.max = "100";
      slider.setAttribute("aria-label", "Brightness");
      slider.addEventListener("pointerdown", () => this._dragging.add(id));
      slider.addEventListener("pointerup", () => this._dragging.delete(id));
      slider.addEventListener("pointercancel", () => this._dragging.delete(id));
      slider.addEventListener("change", () => {
        this._dragging.delete(id);
        this._brightness(id, Number(slider.value), slider);
      });
      row.append(name, button, slider);
      this._rows.append(row);
    }
  }

  _paintRow(id) {
    const row = this._rows.querySelector(`[data-entity="${cssEscape(id)}"]`);
    if (!row) return;
    const state = this._hass.states[id];
    row.querySelector(".name").textContent = friendly(state, "Light");
    const button = row.querySelector("button");
    const on = state && state.state === "on";
    button.textContent = on ? "On" : "Off";
    const slider = row.querySelector("input");
    if (this._dragging.has(id)) return;
    const brightness = state && state.attributes && state.attributes.brightness;
    slider.value = String(on && typeof brightness === "number" ? Math.round((brightness / 255) * 100) : 0);
  }

  _toggle(id, button) {
    const state = this._hass.states[id];
    const service = state && state.state === "on" ? "turn_off" : "turn_on";
    run(this._hass, this._error, [button], () =>
      this._hass.callService("light", service, { entity_id: id }),
    );
  }

  _brightness(id, percent, slider) {
    const service = percent === 0 ? "turn_off" : "turn_on";
    const data = percent === 0 ? { entity_id: id } : { entity_id: id, brightness_pct: percent };
    run(this._hass, this._error, [slider], () => this._hass.callService("light", service, data));
  }
}

function cssEscape(value) {
  return window.CSS && CSS.escape ? CSS.escape(value) : value.replace(/"/g, '\\"');
}

customElements.define("product-light-card", ProductLightCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "product-light-card",
  name: "Lights",
  description: "Dimmers for one light or a light group.",
});
