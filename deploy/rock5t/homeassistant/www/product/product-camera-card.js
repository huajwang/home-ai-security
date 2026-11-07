import { actionCss, hostCss } from "./product-style.js";

class ProductCameraCard extends HTMLElement {
  setConfig(config) {
    if (!config.entity) throw new Error("Set the camera entity.");
    this._config = config;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this._built = false;
    this._live = false;
  }

  connectedCallback() {
    this._timer = setInterval(() => {
      if (this._hass && this._built) this._paint();
    }, 10000);
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
    this.shadowRoot.innerHTML = `
      <style>
        ${hostCss}
        ${actionCss}
        ha-card { padding: 0; overflow: hidden; }
        .frame {
          position: relative;
          aspect-ratio: 16 / 9;
          background: #000;
        }
        .frame.large { min-height: 320px; }
        img, .stage {
          position: absolute;
          inset: 0;
          width: 100%;
          height: 100%;
        }
        img { object-fit: cover; }
        hui-image { display: block; width: 100%; height: 100%; }
        .overlay {
          position: absolute;
          left: 12px;
          bottom: 12px;
          display: flex;
          gap: 8px;
          align-items: center;
          z-index: 1;
        }
        .title {
          color: #f2f4f6;
          font-size: 15px;
          font-weight: 500;
          text-shadow: 0 1px 2px rgba(0, 0, 0, 0.7);
        }
        .pill {
          background: rgba(16, 18, 20, 0.72);
          color: #f2f4f6;
          border-radius: 999px;
          padding: 3px 8px;
          font-size: 13px;
        }
        .pill[hidden] { display: none; }
        button.action { position: absolute; top: 12px; right: 12px; z-index: 1; background: rgba(16, 18, 20, 0.55); }
      </style>
      <ha-card>
        <div class="frame">
          <img alt="">
          <div class="stage" hidden></div>
          <div class="overlay">
            <span class="title"></span>
            <span class="pill" hidden></span>
          </div>
          <button class="action" type="button">Live</button>
        </div>
      </ha-card>
    `;
    this._frame = this.shadowRoot.querySelector(".frame");
    this._img = this.shadowRoot.querySelector("img");
    this._stage = this.shadowRoot.querySelector(".stage");
    this._title = this.shadowRoot.querySelector(".title");
    this._pill = this.shadowRoot.querySelector(".pill");
    this._button = this.shadowRoot.querySelector("button");
    this._frame.classList.toggle("large", !!this._config.large);
    this._button.addEventListener("click", () => this._toggle());
  }

  _paint() {
    const hass = this._hass;
    const state = hass.states[this._config.entity];
    this._title.textContent = this._config.name || (state && state.attributes.friendly_name) || "Camera";
    this._paintPill(hass);
    if (this._live) {
      if (this._player) this._player.hass = hass;
      return;
    }
    const picture = state && state.attributes.entity_picture;
    const now = Date.now();
    if (picture && now - (this._shotAt || 0) > 10000) {
      this._shotAt = now;
      const join = picture.includes("?") ? "&" : "?";
      this._img.src = `${picture}${join}_ts=${now}`;
    }
  }

  _paintPill(hass) {
    const fallback = this._config.entity.replace(/^camera\./, "binary_sensor.") + "_person_occupancy";
    const occupancy = hass.states[this._config.occupancy || fallback];
    if (!occupancy) {
      this._pill.hidden = true;
      return;
    }
    this._pill.hidden = false;
    this._pill.textContent = occupancy.state === "on" ? "Person" : "Clear";
  }

  _toggle() {
    if (this._live) {
      this._stop();
      return;
    }
    this._start();
  }

  _start() {
    const entity = this._config.entity;
    if (customElements.get("hui-image")) {
      const player = document.createElement("hui-image");
      player.hass = this._hass;
      player.cameraImage = entity;
      player.cameraView = "live";
      player.aspectRatio = "16:9";
      this._stage.replaceChildren(player);
      this._stage.hidden = false;
      this._img.hidden = true;
      this._player = player;
      this._live = true;
      this._button.textContent = "Stop";
      return;
    }
    const event = new Event("hass-more-info", { bubbles: true, composed: true });
    event.detail = { entityId: entity };
    this.dispatchEvent(event);
  }

  _stop() {
    this._live = false;
    this._player = null;
    this._stage.replaceChildren();
    this._stage.hidden = true;
    this._img.hidden = false;
    this._button.textContent = "Live";
    this._shotAt = 0;
    this._paint();
  }
}

customElements.define("product-camera-card", ProductCameraCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "product-camera-card",
  name: "Camera",
  description: "Snapshot first. Live starts when you tap it.",
});
