/**
 * Local Z-Wave controller for the Schlage deadbolt.
 * Listens on 127.0.0.1 only. The hub is the HTTPS front door.
 */
import crypto from "node:crypto";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { Driver, InclusionStrategy } from "zwave-js";

const device = process.env.ZWAVE_DEVICE || "/dev/ttyACM0";
const cacheDir = process.env.ZWAVE_CACHE || new URL("../hub/data/zwave/", import.meta.url).pathname;
const port = Number(process.env.ZWAVE_PORT || "3091");

const DOOR_LOCK = 98;
const SECURED = 255;
const UNSECURED = 0;

let pinWait = null;
let including = false;
let excluding = false;
let started = false;

const SECURITY_KEY_NAMES = [
  "S0_Legacy",
  "S2_Unauthenticated",
  "S2_Authenticated",
  "S2_AccessControl",
];

fs.mkdirSync(cacheDir, { recursive: true });

function loadSecurityKeys(dir) {
  const file = path.join(dir, "security-keys.json");
  let saved = {};
  if (fs.existsSync(file)) {
    saved = JSON.parse(fs.readFileSync(file, "utf8"));
  }
  const keys = {};
  let created = false;
  for (const name of SECURITY_KEY_NAMES) {
    const hex = saved[name];
    if (typeof hex === "string" && /^[0-9a-fA-F]{32}$/.test(hex)) {
      keys[name] = Buffer.from(hex, "hex");
    } else {
      keys[name] = crypto.randomBytes(16);
      created = true;
    }
  }
  if (created) {
    const out = {};
    for (const name of SECURITY_KEY_NAMES) out[name] = keys[name].toString("hex");
    fs.writeFileSync(file, JSON.stringify(out), { mode: 0o600 });
    fs.chmodSync(file, 0o600);
  }
  return keys;
}

const driver = new Driver(device, {
  storage: { cacheDir },
  securityKeys: loadSecurityKeys(cacheDir),
  logConfig: { enabled: false },
});

function lockNode() {
  const preferred = Number(process.env.ZWAVE_LOCK_NODE || "0");
  const nodes = [...driver.controller.nodes.values()].filter((node) => node.id !== 1);
  if (preferred) {
    return nodes.find((node) => node.id === preferred) || null;
  }
  return (
    nodes.find((node) => node.ready && node.supportsCC(DOOR_LOCK)) ||
    nodes.find((node) => node.supportsCC(DOOR_LOCK)) ||
    null
  );
}

function modeOf(node) {
  const value = node?.getValue?.({ commandClass: DOOR_LOCK, property: "currentMode" });
  if (value === SECURED || value === "Secured") return "locked";
  if (value === UNSECURED || value === "Unsecured") return "unlocked";
  return "unknown";
}

function status() {
  const node = driver.ready ? lockNode() : null;
  return {
    ready: started,
    state: node ? modeOf(node) : "unknown",
    node_id: node ? node.id : null,
    pin_required: pinWait !== null,
    including,
    excluding,
    inclusion_state: started ? driver.controller.inclusionState : null,
  };
}

function send(response, code, body) {
  const payload = JSON.stringify(body);
  response.writeHead(code, { "Content-Type": "application/json" });
  response.end(payload);
}

async function readBody(request) {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  if (chunks.length === 0) return {};
  return JSON.parse(Buffer.concat(chunks).toString() || "{}");
}

async function setLock(action) {
  const node = lockNode();
  if (!node) {
    return { success: false, state: "unknown", message: "No Z-Wave lock is paired" };
  }
  const desired = action === "lock" ? "locked" : "unlocked";
  const current = modeOf(node);
  if (current === desired) {
    return {
      success: false,
      state: current,
      message: desired === "locked" ? "already locked" : "already unlocked",
    };
  }
  const mode = desired === "locked" ? SECURED : UNSECURED;
  await node.commandClasses["Door Lock"].set(mode);
  return { success: true, state: desired, message: desired };
}

async function beginInclusion() {
  if (!started) {
    return { ok: false, message: "Z-Wave controller is still starting" };
  }
  if (including) {
    return { ok: true, message: "Already waiting for the lock" };
  }
  including = true;
  const fullDsk = String(process.env.ZWAVE_DSK || "").trim();
  const inclusion = {
    strategy: InclusionStrategy.Security_S2,
    userCallbacks: {
      grantSecurityClasses: async (requested) => {
        if (requested && Array.isArray(requested.securityClasses)) {
          return {
            securityClasses: requested.securityClasses,
            clientSideAuth: Boolean(requested.clientSideAuth),
          };
        }
        return requested;
      },
      validateDSKAndEnterPIN: (dsk) => {
        const digits = (value) => String(value ?? "").replace(/\D/g, "");
        const pin = digits(process.env.ZWAVE_S2_PIN);
        const known = digits(process.env.ZWAVE_DSK || process.env.ZWAVE_DSK_REST);
        const shown = digits(dsk);
        const matches =
          pin.length === 5 &&
          known.length >= 35 &&
          (shown === known || shown === known.slice(5) || known.endsWith(shown));
        if (matches) {
          console.log("Submitting the lock DSK PIN");
          return pin;
        }
        return new Promise((resolve) => {
          pinWait = resolve;
          console.log("Z-Wave lock needs the 5-digit DSK PIN from the sticker");
          setTimeout(() => {
            if (pinWait === resolve) {
              pinWait = null;
              resolve(false);
            }
          }, 180000);
        });
      },
      abort: () => {
        if (pinWait) pinWait(false);
        pinWait = null;
      },
    },
  };
  if (/^(\d{5}-){7}\d{5}$/.test(fullDsk)) {
    inclusion.dsk = fullDsk;
    console.log("Inclusion will use the sticker DSK");
  }
  const startedInclusion = await driver.controller.beginInclusion(inclusion);
  if (!startedInclusion) {
    including = false;
    return { ok: false, message: "Could not start pairing" };
  }
  console.log("Inclusion is waiting for the lock");
  return {
    ok: true,
    message: "Inclusion started. Press the Schlage button, enter the programming code, then press 0.",
  };
}

const server = http.createServer(async (request, response) => {
  try {
    const url = request.url || "/";
    if (request.method === "GET" && url === "/status") {
      send(response, 200, status());
      return;
    }
    if (request.method === "POST" && url === "/lock") {
      const body = await readBody(request);
      const action = body.action === "unlock" ? "unlock" : "lock";
      send(response, 200, await setLock(action));
      return;
    }
    if (request.method === "POST" && url === "/inclusion/start") {
      send(response, 200, await beginInclusion());
      return;
    }
    if (request.method === "POST" && url === "/inclusion/pin") {
      const body = await readBody(request);
      const pin = String(body.pin || "").trim();
      if (!pinWait) {
        send(response, 409, { ok: false, message: "The lock is not asking for a PIN" });
        return;
      }
      const resolve = pinWait;
      pinWait = null;
      resolve(pin);
      send(response, 200, { ok: true, message: "PIN sent to the lock" });
      return;
    }
    if (request.method === "POST" && url === "/exclusion/start") {
      if (!started) {
        send(response, 503, { ok: false, message: "Z-Wave controller is still starting" });
        return;
      }
      const startedExclusion = await driver.controller.beginExclusion();
      if (!startedExclusion) {
        send(response, 409, { ok: false, message: "Could not start exclusion" });
        return;
      }
      excluding = true;
      console.log("Exclusion is waiting for the lock");
      send(response, 200, {
        ok: true,
        message: "Exclusion started. Press the Schlage button, enter the programming code, then press 0.",
      });
      return;
    }
    send(response, 404, { message: "not found" });
  } catch (error) {
    send(response, 500, { message: error instanceof Error ? error.message : String(error) });
  }
});

driver.on("error", (error) => {
  console.error(`Z-Wave driver error: ${error instanceof Error ? error.message : error}`);
});

driver.on("driver ready", () => {
  started = true;
  driver.controller.on("node added", (node, result) => {
    including = false;
    const security =
      typeof node.getHighestSecurityClass === "function" ? node.getHighestSecurityClass() : "unknown";
    const low = result?.lowSecurity === true;
    const reason = result?.lowSecurityReason ?? "";
    console.log(`Z-Wave node ${node.id} added security=${security} low=${low} reason=${reason}`);
  });
  driver.controller.on("node removed", (node) => {
    excluding = false;
    console.log(`Z-Wave node ${node.id} removed`);
  });
  driver.controller.on("inclusion stopped", () => {
    including = false;
    console.log("Inclusion stopped");
  });
  driver.controller.on("exclusion stopped", () => {
    excluding = false;
    console.log("Exclusion stopped");
  });
  console.log(`Z-Wave controller ready on ${device}`);
});

server.listen(port, "127.0.0.1", () => {
  console.log(`Z-Wave API on 127.0.0.1:${port}`);
});
await driver.start();
