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
const UNSECURED_MODES = new Set([0, 1, 0x10, 0x11, 0x20, 0x21]);

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

function interpretMode(value) {
  if (value === SECURED || value === "Secured") return "locked";
  if (UNSECURED_MODES.has(value)) return "unlocked";
  if (typeof value === "string" && value.toLowerCase().includes("unsecured")) return "unlocked";
  return "unknown";
}

function cachedMode(node) {
  return interpretMode(node?.getValue?.({ commandClass: DOOR_LOCK, property: "currentMode" }));
}

function reachability(node) {
  const status = node?.status;
  if (status === 4 || status === "Alive" || status === 2 || status === "Awake") return "alive";
  if (status === 1 || status === "Asleep") return "asleep";
  if (status === 3 || status === "Dead") return "dead";
  return "unknown";
}

let refreshTask = null;
let lastRefreshAt = 0;

async function freshMode(node) {
  const mode = await node.commandClasses["Door Lock"].get();
  const state = interpretMode(mode);
  return state === "unknown" ? cachedMode(node) : state;
}

function scheduleRefresh(node) {
  if (!node || refreshTask || reachability(node) === "dead") return;
  if (Date.now() - lastRefreshAt < 45000) return;
  lastRefreshAt = Date.now();
  refreshTask = freshMode(node)
    .catch((error) => {
      console.log(`Lock status refresh failed: ${error instanceof Error ? error.message : error}`);
    })
    .finally(() => {
      refreshTask = null;
    });
}

function statusBody(state, reachable) {
  const node = driver.ready ? lockNode() : null;
  return {
    ready: started,
    state: state ?? (node ? cachedMode(node) : "unknown"),
    reachable: reachable ?? (node ? reachability(node) : "unknown"),
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
  const radio = reachability(node);
  if (radio === "alive" || radio === "awake") {
    try {
      const current = await freshMode(node);
      if (current === desired) {
        return {
          success: false,
          state: current,
          reachable: reachability(node),
          message: desired === "locked" ? "already locked" : "already unlocked",
        };
      }
    } catch (error) {
      console.log(`Lock refresh failed: ${error instanceof Error ? error.message : error}`);
    }
  }
  const mode = desired === "locked" ? SECURED : 0;
  try {
    await node.commandClasses["Door Lock"].set(mode);
  } catch (error) {
    console.log(`Lock command failed: ${error instanceof Error ? error.message : error}`);
    return {
      success: false,
      state: cachedMode(node),
      reachable: reachability(node),
      message: "The lock did not answer",
    };
  }
  let confirmed = null;
  try {
    confirmed = await freshMode(node);
  } catch (error) {
    console.log(`Lock confirm failed: ${error instanceof Error ? error.message : error}`);
  }
  const state = confirmed || desired;
  return {
    success: state === desired,
    state,
    reachable: reachability(node),
    message: state === desired ? desired : `Lock reported ${state}`,
  };
}

const RF_REGION = {
  0: "Europe",
  1: "USA",
  2: "Australia/New Zealand",
  9: "USA (Long Range)",
  254: "Unknown",
};

function radioBody() {
  const controller = started ? driver.controller : null;
  const region = controller ? controller.rfRegion : null;
  const nodes = controller
    ? [...controller.nodes.values()].map((node) => ({
        id: node.id,
        ready: Boolean(node.ready),
        reachable: reachability(node),
        interview: node.interviewStage ?? null,
        last_seen: node.lastSeen ? new Date(node.lastSeen).toISOString() : null,
      }))
    : [];
  return {
    ready: started,
    sdk: controller ? controller.sdkVersion : null,
    rf_region: RF_REGION[region] || region,
    nodes,
  };
}

const followedLocks = new Set();

function followLock(node) {
  if (!node || followedLocks.has(node.id)) return;
  followedLocks.add(node.id);
  node.on("value updated", (_node, args) => {
    const commandClass = args?.commandClass;
    if (commandClass !== DOOR_LOCK && commandClass !== "Door Lock") return;
    if (args.property !== "currentMode") return;
    const state = interpretMode(args.newValue);
    if (state !== "locked" && state !== "unlocked") return;
    if (state === interpretMode(args.prevValue)) return;
    pushLockState(state);
  });
}

function pushLockState(state) {
  const port = Number(process.env.HUB_HTTP_PORT || "8080");
  const body = JSON.stringify({ state });
  const request = http.request(
    {
      hostname: "127.0.0.1",
      port,
      path: "/v1/lock/report",
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Content-Length": Buffer.byteLength(body),
      },
    },
    (response) => {
      response.resume();
    },
  );
  request.on("error", (error) => {
    console.log(`Lock push failed: ${error instanceof Error ? error.message : error}`);
  });
  request.end(body);
}

async function dropSilentNodes() {
  const keep = new Set([1]);
  const lock = lockNode();
  if (lock) keep.add(lock.id);
  for (const node of [...driver.controller.nodes.values()]) {
    if (keep.has(node.id) || node.ready) continue;
    try {
      await driver.controller.removeFailedNode(node.id);
      console.log(`Removed silent Z-Wave node ${node.id}`);
    } catch (error) {
      console.log(`Left Z-Wave node ${node.id} in place: ${error instanceof Error ? error.message : error}`);
    }
  }
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
    if (request.method === "GET" && url === "/radio") {
      send(response, 200, radioBody());
      return;
    }
    if (request.method === "GET" && url === "/status") {
      const node = driver.ready ? lockNode() : null;
      if (node) scheduleRefresh(node);
      send(
        response,
        200,
        statusBody(node ? cachedMode(node) : "unknown", node ? reachability(node) : "unknown"),
      );
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
  const region = driver.controller.rfRegion;
  console.log(
    `Z-Wave controller ready on ${device} sdk=${driver.controller.sdkVersion} region=${RF_REGION[region] || region}`,
  );
  const lock = lockNode();
  if (lock) followLock(lock);
  void dropSilentNodes();
});

server.listen(port, "127.0.0.1", () => {
  console.log(`Z-Wave API on 127.0.0.1:${port}`);
});
await driver.start();
