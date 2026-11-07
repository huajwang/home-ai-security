const style = document.createElement("style");
style.textContent = `
@font-face {
  font-family: "IBM Plex Sans";
  font-style: normal;
  font-weight: 400;
  font-display: swap;
  src: url("/local/fonts/ibm-plex-sans-latin-400-normal.woff2") format("woff2");
}
@font-face {
  font-family: "IBM Plex Sans";
  font-style: normal;
  font-weight: 500;
  font-display: swap;
  src: url("/local/fonts/ibm-plex-sans-latin-500-normal.woff2") format("woff2");
}
`;
document.head.appendChild(style);

const HIDDEN_PANELS = new Set(["map", "energy", "developer-tools"]);
let themeApplied = false;
let themeAttempts = 0;

function applyTheme(hass) {
  if (themeApplied || !hass || !hass.user || !hass.callService) return;
  const current = hass.themes && hass.themes.theme;
  const wall = hass.user.name === "wall";
  if (!wall && current === "Home") {
    themeApplied = true;
    return;
  }
  if (wall && current === "Home" && hass.themes.darkMode === false) {
    themeApplied = true;
    return;
  }
  if (!wall && current && current !== "default" && current !== "Backend-selected") return;
  themeApplied = true;
  const data = wall ? { name: "Home", mode: "light" } : { name: "Home" };
  hass.callService("frontend", "set_theme", data).catch(() => {
    themeAttempts += 1;
    themeApplied = themeAttempts >= 3;
  });
}

function hidePanels(node, hide) {
  if (!node) return;
  const kind = node.nodeType;
  if (kind !== 1 && kind !== 11) return;
  if (kind === 1) {
    const panel = node.getAttribute && node.getAttribute("data-panel");
    if (hide && panel && HIDDEN_PANELS.has(panel)) node.style.display = "none";
  }
  for (const child of node.children || []) hidePanels(child, hide);
  if (node.shadowRoot) hidePanels(node.shadowRoot, hide);
}

function tick() {
  const root = document.querySelector("home-assistant");
  const hass = root && root.hass;
  if (!hass || !hass.user) return;
  applyTheme(hass);
  hidePanels(root, !hass.user.is_admin);
}

customElements.whenDefined("home-assistant").then(() => {
  const timer = setInterval(tick, 1000);
  setTimeout(() => clearInterval(timer), 20000);
});
