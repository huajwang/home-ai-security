import { hostCss, ago, friendly } from "./product-style.js";

class ProductDoorsCard extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this._built = false;
  }

  connectedCallback() {
    this._timer = setInterval(() => {
      if (this._hass && this._built) this._paint();
    }, 30000);
  }

  disconnectedCallback() {
    clearInterval(this._timer);
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
          grid-template-columns: 1fr auto auto;
          gap: 12px;
          align-items: baseline;
          padding: 12px 0;
          border-top: 1px solid var(--divider-color);
          font-size: 15px;
        }
        .row:first-of-type { border-top: 0; }
        .age { color: var(--secondary-text-color); font-size: 13px; }
        .open { color: var(--product-open, #8f5314); }
        .closed { color: var(--product-disarmed, #246848); }
      </style>
      <ha-card>
        <h2>Doors</h2>
        <div class="rows"></div>
      </ha-card>
    `;
    this._rows = this.shadowRoot.querySelector(".rows");
  }

  _paint() {
    const ids = this._config.entities || [];
    const key = ids.join("\n");
    if (key !== this._key) {
      this._key = key;
      this._render(ids);
    }
    for (const id of ids) this._paintRow(id);
  }

  _render(ids) {
    this._rows.replaceChildren();
    if (!ids.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No door sensors yet.";
      this._rows.append(empty);
      return;
    }
    for (const id of ids) {
      const row = document.createElement("div");
      row.className = "row";
      row.dataset.entity = id;
      row.innerHTML = `<span class="name"></span><span class="state"></span><span class="age"></span>`;
      this._rows.append(row);
    }
  }

  _paintRow(id) {
    const row = this._rows.querySelector(`[data-entity="${cssEscape(id)}"]`);
    if (!row) return;
    const state = this._hass.states[id];
    row.querySelector(".name").textContent = friendly(state, "Door");
    const label = row.querySelector(".state");
    if (!state || state.state === "unavailable") {
      label.textContent = "Unavailable";
      label.className = "state";
    } else if (state.state === "on") {
      label.textContent = "Open";
      label.className = "state open";
    } else {
      label.textContent = "Closed";
      label.className = "state closed";
    }
    row.querySelector(".age").textContent = state ? ago(state.last_changed) : "";
  }
}

function cssEscape(value) {
  return window.CSS && CSS.escape ? CSS.escape(value) : value.replace(/"/g, '\\"');
}

customElements.define("product-doors-card", ProductDoorsCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "product-doors-card",
  name: "Doors",
  description: "Contact sensors, with how long they have been open or closed.",
});
