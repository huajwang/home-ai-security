export const hostCss = `
  :host { display: block; }
  ha-card {
    display: block;
    padding: 20px 22px 18px;
    font-family: "IBM Plex Sans", sans-serif;
    color: var(--primary-text-color);
  }
  .error {
    min-height: 0;
    margin: 10px 0 0;
    font-size: 13px;
    color: var(--product-triggered, #b33b34);
  }
`;

export const actionCss = `
  button.action {
    appearance: none;
    background: transparent;
    color: var(--product-action, #8a6a32);
    border: 1px solid var(--product-action, #8a6a32);
    border-radius: 999px;
    padding: 8px 16px;
    font: 500 15px/1 "IBM Plex Sans", sans-serif;
    cursor: pointer;
  }
  button.action:disabled { opacity: 0.45; cursor: default; }
  button.action:focus-visible {
    outline: 2px solid var(--product-action, #8a6a32);
    outline-offset: 2px;
  }
`;

export function ago(iso) {
  if (!iso) return "";
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} hr`;
  return `${Math.round(hours / 24)} days`;
}

export function friendly(state, fallback) {
  return (state && state.attributes && state.attributes.friendly_name) || fallback || "";
}

export async function run(hass, errorNode, buttons, fn) {
  if (errorNode) errorNode.textContent = "";
  for (const button of buttons) button.disabled = true;
  try {
    await fn();
  } catch (_err) {
    if (errorNode) errorNode.textContent = "That did not go through.";
  } finally {
    for (const button of buttons) button.disabled = false;
  }
}
