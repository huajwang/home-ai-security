import { actionCss, hostCss, friendly, run } from "./product-style.js";

const WORDS = {
  disarmed: ["Disarmed", "--product-disarmed"],
  armed_home: ["Armed home", "--product-armed-home"],
  armed_night: ["Armed night", "--product-armed-home"],
  armed_away: ["Armed away", "--product-armed-away"],
  armed_vacation: ["Armed vacation", "--product-armed-away"],
  arming: ["Arming", "--product-armed-away"],
  pending: ["Pending", "--product-armed-home"],
  triggered: ["Alarm", "--product-triggered"],
};

class ProductStatusCard extends HTMLElement {
  setConfig(config) {
    if (!config.alarm) throw new Error("Set the alarm entity.");
    this._config = config;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this._built = false;
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
        .detail { margin: 8px 0 0; font-size: 15px; line-height: 1.45; }
        .actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }
        ha-card.triggered { border-left: 4px solid var(--product-triggered, #b33b34); }
      </style>
      <ha-card>
        <div class="mark"></div>
        <div class="word"></div>
        <p class="detail"></p>
        <div class="actions"></div>
        <p class="error"></p>
      </ha-card>
    `;
    this._mark = this.shadowRoot.querySelector(".mark");
    this._word = this.shadowRoot.querySelector(".word");
    this._detail = this.shadowRoot.querySelector(".detail");
    this._actions = this.shadowRoot.querySelector(".actions");
    this._error = this.shadowRoot.querySelector(".error");
    this._card = this.shadowRoot.querySelector("ha-card");
  }

  _paint() {
    const hass = this._hass;
    const alarm = hass.states[this._config.alarm];
    const state = alarm ? alarm.state : "unavailable";
    const [label, token] = WORDS[state] || ["Unavailable", "--secondary-text-color"];
    this._mark.textContent = (hass.config && hass.config.location_name) || "Home";
    this._word.textContent = label;
    this._word.style.color = `var(${token})`;
    this._detail.textContent = this._detailLine();
    this._card.classList.toggle("triggered", state === "triggered");
    const key = state === "disarmed" ? "arm" : state === "unavailable" ? "none" : "disarm";
    if (key !== this._actionKey) {
      this._actionKey = key;
      this._renderActions(key);
    }
  }

  _detailLine() {
    const hass = this._hass;
    const lock = hass.states[this._config.lock];
    const lockState = lock ? lock.state : "unavailable";
    const lockLine = {
      locked: "Front door locked.",
      unlocked: "Front door unlocked.",
      locking: "Front door locking.",
      unlocking: "Front door unlocking.",
      jammed: "Front door jammed.",
    }[lockState] || "Front door unavailable.";

    const doors = this._config.doors || [];
    if (!doors.length) return lockLine;
    const known = doors.map((id) => hass.states[id]).filter(Boolean);
    if (!known.length || known.every((state) => state.state === "unavailable")) {
      return `${lockLine} Door sensors unavailable.`;
    }
    const open = known.filter((state) => state.state === "on");
    const doorLine = open.length
      ? `${open.map((state) => `${friendly(state, "Door")} open`).join(". ")}.`
      : "All doors closed.";
    return `${lockLine} ${doorLine}`;
  }

  _renderActions(key) {
    this._actions.replaceChildren();
    if (key === "arm") {
      this._actions.append(
        this._button("Arm home", () => this._alarm("alarm_arm_home")),
        this._button("Arm away", () => this._alarm("alarm_arm_away")),
      );
    } else if (key === "disarm") {
      this._actions.append(this._button("Disarm", () => this._alarm("alarm_disarm")));
    }
  }

  _button(label, onClick) {
    const button = document.createElement("button");
    button.className = "action";
    button.type = "button";
    button.textContent = label;
    button.addEventListener("click", onClick);
    return button;
  }

  _alarm(service) {
    const buttons = [...this._actions.querySelectorAll("button")];
    run(this._hass, this._error, buttons, () =>
      this._hass.callService("alarm_control_panel", service, {
        entity_id: this._config.alarm,
      }),
    );
  }
}

customElements.define("product-status-card", ProductStatusCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "product-status-card",
  name: "Status",
  description: "Alarm, front door, and open contacts.",
});
