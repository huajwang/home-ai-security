import { actionCss, hostCss, run } from "./product-style.js";

const WORDS = {
  locked: ["Locked", "--product-disarmed"],
  unlocked: ["Unlocked", "--product-open"],
  locking: ["Locking", "--product-armed-away"],
  unlocking: ["Unlocking", "--product-open"],
  jammed: ["Jammed", "--product-triggered"],
};

class ProductLockCard extends HTMLElement {
  setConfig(config) {
    if (!config.entity) throw new Error("Set the lock entity.");
    this._config = config;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this._built = false;
    this._confirm = false;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) this._build();
    this._paint();
  }

  _build() {
    this._built = true;
    this._actionKey = "";
    this.shadowRoot.innerHTML = `
      <style>
        ${hostCss}
        ${actionCss}
        .mark { font-size: 13px; letter-spacing: 0.04em; color: var(--secondary-text-color); }
        .word { margin-top: 4px; font-size: 32px; font-weight: 500; line-height: 1.15; }
        .ask { margin: 16px 0 8px; font-size: 15px; }
        .actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }
      </style>
      <ha-card>
        <div class="mark">Front door</div>
        <div class="word"></div>
        <div class="actions"></div>
        <p class="error"></p>
      </ha-card>
    `;
    this._word = this.shadowRoot.querySelector(".word");
    this._actions = this.shadowRoot.querySelector(".actions");
    this._error = this.shadowRoot.querySelector(".error");
  }

  _paint() {
    const stateObj = this._hass.states[this._config.entity];
    const state = stateObj ? stateObj.state : "unavailable";
    if (state !== "locked") this._confirm = false;
    const [label, token] = WORDS[state] || ["Unavailable", "--secondary-text-color"];
    this._word.textContent = label;
    this._word.style.color = `var(${token})`;
    const key = this._confirm ? "confirm" : state;
    if (key !== this._actionKey) {
      this._actionKey = key;
      this._renderActions(state);
    }
  }

  _renderActions(state) {
    this._actions.replaceChildren();
    if (this._confirm) {
      const ask = document.createElement("p");
      ask.className = "ask";
      ask.textContent = "Unlock the front door?";
      const confirm = this._button("Confirm", () => this._unlock());
      const cancel = this._button("Cancel", () => {
        this._confirm = false;
        this._actionKey = "";
        this._paint();
      });
      this._actions.append(ask, confirm, cancel);
      return;
    }
    if (state === "locked") {
      this._actions.append(this._button("Unlock", () => {
        this._confirm = true;
        this._actionKey = "";
        this._paint();
      }));
      return;
    }
    this._actions.append(this._button("Lock", () => this._lock()));
  }

  _button(label, onClick) {
    const button = document.createElement("button");
    button.className = "action";
    button.type = "button";
    button.textContent = label;
    button.addEventListener("click", onClick);
    return button;
  }

  _buttons() {
    return [...this._actions.querySelectorAll("button")];
  }

  _lock() {
    run(this._hass, this._error, this._buttons(), () =>
      this._hass.callService("script", "lock_front_door"),
    );
  }

  _unlock() {
    run(this._hass, this._error, this._buttons(), async () => {
      await this._hass.callService("lock", "unlock", { entity_id: this._config.entity });
      this._confirm = false;
      this._actionKey = "";
    });
  }
}

customElements.define("product-lock-card", ProductLockCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "product-lock-card",
  name: "Lock",
  description: "Front deadbolt. Unlock asks before it sends the command.",
});
