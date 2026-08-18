/**
 * Arika's Minecraft reflex bot.
 * ==============================
 * This is the "reflexes" half of the brain/reflexes split:
 *   - LLM (Python side, backend/minecraft_manager.py) sends high-level
 *     decisions by calling the small action API below.
 *   - This process handles movement, target selection, basic PvP,
 *     navigation and automatic attack/defend WITHOUT waiting on the LLM
 *     for every tick (mineflayer-pathfinder + mineflayer-pvp do the
 *     actual pathing/combat in ~100-500ms).
 *
 * HTTP API (local only, 127.0.0.1):
 *   POST /connect   { host, port, username, version, auth }
 *   POST /disconnect
 *   GET  /status                      -> compact status JSON (see spec)
 *   GET  /events?since=<id>           -> discrete events since id
 *   POST /action    { name, args }    -> follow_player/stop/attack_target/
 *                                         move_to/look_at/eat_food/equip/
 *                                         defend_player
 *
 * Auth note: TLauncher accounts are typically "offline"/cracked-style
 * auth. Default here is auth: "offline" so it works against a TLauncher
 * server/LAN world out of the box; pass auth: "microsoft" for a
 * legitimate Mojang/Microsoft account server instead.
 */

const express = require("express");
const mineflayer = require("mineflayer");
const { pathfinder, Movements, goals } = require("mineflayer-pathfinder");
const { plugin: pvpPlugin } = require("mineflayer-pvp");
let autoEatPlugin = null;
try {
  // Optional — different published versions export this differently;
  // fail soft so a version mismatch never crashes bot startup.
  const autoEat = require("mineflayer-auto-eat");
  autoEatPlugin = autoEat.plugin || autoEat.default || autoEat;
} catch (e) {
  console.warn("[Bot] mineflayer-auto-eat not available, eat_food will use a manual fallback:", e.message);
}

const DEFAULT_PORT = 39399;
const PORT = Number(process.env.ARIKA_MC_BOT_PORT || process.env.PORT || DEFAULT_PORT);

const HOSTILE_MOBS = new Set([
  "zombie", "skeleton", "creeper", "spider", "cave_spider", "enderman",
  "witch", "husk", "stray", "drowned", "phantom", "pillager", "vindicator",
  "evoker", "ravager", "zombie_villager", "silverfish", "blaze",
  "magma_cube", "slime", "wither_skeleton", "hoglin", "zoglin", "piglin_brute",
]);

const LOW_HEALTH_THRESHOLD = 8; // hearts * 2 (mineflayer health is 0-20)
const PLAYER_TOO_FAR_DISTANCE = 24;
const AGGRO_RADIUS = 12;
const REFLEX_TICK_MS = 400; // "100-500ms" reflex loop from the spec

let bot = null;
let movements = null;
let followTarget = null; // username string, or null
let currentTargetEntity = null; // mob entity currently being fought
let currentActionLabel = "idle";
let lastKnownHealth = 20;
let lastPosKey = null;

let events = [];
let nextEventId = 1;

function pushEvent(type, detail) {
  const ev = { id: nextEventId++, type, detail, ts: Date.now() };
  events.push(ev);
  if (events.length > 500) events = events.slice(-300); // cap memory use
  console.log(`[Bot] EVENT ${type}: ${detail}`);
}

// ---------------------------------------------------------------------
// Bot lifecycle
// ---------------------------------------------------------------------

function createBot({ host, port, username, version, auth }) {
  if (bot) {
    try { bot.quit(); } catch (e) {}
    bot = null;
  }

  bot = mineflayer.createBot({
    host: host || "localhost",
    port: port ? Number(port) : 25565,
    username: username || "Arika",
    version: version || false, // false = auto-detect
    auth: auth || "offline", // TLauncher-friendly default
  });

  bot.loadPlugin(pathfinder);
  bot.loadPlugin(pvpPlugin);
  if (autoEatPlugin) bot.loadPlugin(autoEatPlugin);

  bot.once("spawn", () => {
    movements = new Movements(bot);
    bot.pathfinder.setMovements(movements);
    pushEvent("NEW_AREA", `Spawned at ${fmtPos(bot.entity.position)} in ${bot.game?.dimension || "overworld"}`);
    lastPosKey = chunkKey(bot.entity.position);
  });

  bot.on("health", () => {
    if (bot.health <= 0) return; // death handled separately
    if (bot.health < lastKnownHealth) {
      pushEvent("PLAYER_DAMAGED", `Bot took damage, health now ${bot.health}/20`);
    }
    if (bot.health <= LOW_HEALTH_THRESHOLD) {
      pushEvent("LOW_HEALTH", `Bot health low: ${bot.health}/20`);
    }
    lastKnownHealth = bot.health;
  });

  bot.on("death", () => {
    pushEvent("DEATH", `Bot died near ${fmtPos(bot.entity ? bot.entity.position : null)}`);
    currentTargetEntity = null;
    currentActionLabel = "dead";
  });

  bot.on("kicked", (reason) => pushEvent("KICKED", String(reason)));
  bot.on("error", (err) => pushEvent("ERROR", String(err && err.message ? err.message : err)));

  if (bot.pvp) {
    bot.pvp.on("stoppedAttacking", () => {
      if (currentTargetEntity && !currentTargetEntity.isValid) {
        pushEvent("TARGET_KILLED", `Killed ${currentTargetEntity.displayName || currentTargetEntity.name || "target"}`);
      }
      currentTargetEntity = null;
      currentActionLabel = followTarget ? "following_player" : "idle";
    });
  }

  startReflexLoop();
  return bot;
}

function disconnectBot() {
  stopReflexLoop();
  if (bot) {
    try { bot.quit(); } catch (e) {}
  }
  bot = null;
  followTarget = null;
  currentTargetEntity = null;
  currentActionLabel = "idle";
}

// ---------------------------------------------------------------------
// Reflex loop — runs locally, no LLM call. Handles:
//   - following the player
//   - auto-detecting nearby hostile mobs -> TARGET_FOUND event
//   - auto-defending if a hostile mob gets close while defend mode is on
//   - PLAYER_TOO_FAR detection
// ---------------------------------------------------------------------

let reflexInterval = null;
let defendModeOn = false;

function startReflexLoop() {
  stopReflexLoop();
  reflexInterval = setInterval(() => {
    if (!bot || !bot.entity) return;
    try {
      reflexTick();
    } catch (e) {
      console.warn("[Bot] reflex tick error:", e.message);
    }
  }, REFLEX_TICK_MS);
}

function stopReflexLoop() {
  if (reflexInterval) clearInterval(reflexInterval);
  reflexInterval = null;
}

function nearestHostile() {
  if (!bot) return null;
  const entities = Object.values(bot.entities);
  let nearest = null;
  let nearestDist = Infinity;
  for (const e of entities) {
    if (!e || e === bot.entity) continue;
    const name = (e.name || "").toLowerCase();
    if (!HOSTILE_MOBS.has(name)) continue;
    const dist = e.position.distanceTo(bot.entity.position);
    if (dist < nearestDist) {
      nearestDist = dist;
      nearest = e;
    }
  }
  return nearest ? { entity: nearest, distance: nearestDist } : null;
}

function chunkKey(pos) {
  if (!pos) return null;
  return `${Math.floor(pos.x / 16)},${Math.floor(pos.z / 16)}`;
}

function fmtPos(pos) {
  if (!pos) return "unknown";
  return `(${Math.round(pos.x)}, ${Math.round(pos.y)}, ${Math.round(pos.z)})`;
}

let lastHostileSeen = null;

function reflexTick() {
  // NEW_AREA detection (chunk change)
  const key = chunkKey(bot.entity.position);
  if (key && key !== lastPosKey) {
    lastPosKey = key;
    pushEvent("NEW_AREA", `Entered new area near ${fmtPos(bot.entity.position)}`);
  }

  // Nearby hostile detection
  const hostile = nearestHostile();
  if (hostile && hostile.distance <= AGGRO_RADIUS) {
    const label = hostile.entity.displayName || hostile.entity.name;
    if (!lastHostileSeen || lastHostileSeen.entity !== hostile.entity) {
      pushEvent("TARGET_FOUND", `${label} spotted ${Math.round(hostile.distance)} blocks away`);
    }
    lastHostileSeen = hostile;

    // Auto-defend: only actually engage if defend mode is explicitly on
    // (set via the defend_player/attack_target actions) — the reflex
    // loop detects and reports, but doesn't start fights on its own
    // unless Arika told it to defend.
    if (defendModeOn && bot.pvp && !currentTargetEntity && hostile.distance <= 5) {
      currentTargetEntity = hostile.entity;
      currentActionLabel = "defending";
      bot.pvp.attack(hostile.entity);
      pushEvent("AUTO_DEFEND", `Auto-engaging ${label} (defend mode on)`);
    }
  } else {
    lastHostileSeen = null;
  }

  // PLAYER_TOO_FAR
  if (followTarget) {
    const player = bot.players[followTarget];
    if (player && player.entity) {
      const dist = player.entity.position.distanceTo(bot.entity.position);
      if (dist > PLAYER_TOO_FAR_DISTANCE) {
        pushEvent("PLAYER_TOO_FAR", `${Math.round(dist)} blocks from ${followTarget}`);
      }
    }
  }
}

// ---------------------------------------------------------------------
// Action API implementations
// ---------------------------------------------------------------------

function requireBot() {
  if (!bot || !bot.entity) throw new Error("Bot isn't connected to a world yet. Call /connect first.");
}

const actions = {
  follow_player(args) {
    requireBot();
    const username = args.username || Object.keys(bot.players).find((n) => n !== bot.username);
    if (!username) throw new Error("No player to follow (nobody else in the players list).");
    followTarget = username;
    currentActionLabel = "following_player";
    const target = bot.players[username] && bot.players[username].entity;
    if (target) {
      bot.pathfinder.setGoal(new goals.GoalFollow(target, 3), true);
    } else {
      // Player entity not loaded yet (out of render distance) — the
      // reflex loop will pick this up as PLAYER_TOO_FAR / retry once
      // they come into range; follow intent is still recorded.
      pushEvent("PLAYER_TOO_FAR", `${username} not currently visible to follow yet`);
    }
    return { status: "ok", following: username };
  },

  stop() {
    requireBot();
    followTarget = null;
    if (bot.pvp) bot.pvp.stop();
    bot.pathfinder.setGoal(null);
    currentTargetEntity = null;
    defendModeOn = false;
    currentActionLabel = "idle";
    return { status: "ok" };
  },

  attack_target(args) {
    requireBot();
    if (!bot.pvp) throw new Error("PvP plugin not loaded.");
    let target = null;
    if (args.entity_id) {
      target = bot.entities[args.entity_id];
    } else if (args.name) {
      const wanted = String(args.name).toLowerCase();
      const found = nearestHostile();
      if (found && (found.entity.name || "").toLowerCase() === wanted) target = found.entity;
    } else {
      const found = nearestHostile();
      target = found ? found.entity : null;
    }
    if (!target) throw new Error("No matching target nearby.");
    currentTargetEntity = target;
    currentActionLabel = "attacking";
    bot.pvp.attack(target);
    return { status: "ok", target: target.displayName || target.name };
  },

  move_to(args) {
    requireBot();
    const { x, y, z, range } = args;
    if ([x, y, z].some((v) => typeof v !== "number")) {
      throw new Error("move_to needs numeric x, y, z.");
    }
    currentActionLabel = "moving";
    bot.pathfinder.setGoal(new goals.GoalNear(x, y, z, range || 1));
    return { status: "ok", moving_to: { x, y, z } };
  },

  look_at(args) {
    requireBot();
    let target = null;
    if (args.entity_id) target = bot.entities[args.entity_id];
    else if (args.username) target = bot.players[args.username]?.entity;
    else {
      const found = nearestHostile();
      target = found ? found.entity : null;
    }
    if (!target) throw new Error("No matching entity to look at.");
    bot.lookAt(target.position.offset(0, target.height || 1.6, 0));
    return { status: "ok", looking_at: target.displayName || target.name || target.username };
  },

  async eat_food() {
    requireBot();
    if (bot.autoEat) {
      try {
        await bot.autoEat.eat();
        return { status: "ok" };
      } catch (e) {
        // fall through to manual fallback
      }
    }
    const food = bot.inventory.items().find((i) => i.name && /bread|apple|beef|porkchop|chicken|carrot|potato|stew|cooked|fish|salmon|cod/.test(i.name));
    if (!food) throw new Error("No food in inventory.");
    await bot.equip(food, "hand");
    await bot.consume();
    return { status: "ok", ate: food.name };
  },

  async equip(args) {
    requireBot();
    if (!args.item) throw new Error("equip needs an item name.");
    const item = bot.inventory.items().find((i) => i.name === args.item);
    if (!item) throw new Error(`'${args.item}' not found in inventory.`);
    const destination = args.destination || "hand";
    await bot.equip(item, destination);
    return { status: "ok", equipped: item.name, destination };
  },

  defend_player() {
    requireBot();
    defendModeOn = true;
    currentActionLabel = "defending";
    const found = nearestHostile();
    if (found && bot.pvp) {
      currentTargetEntity = found.entity;
      bot.pvp.attack(found.entity);
      return { status: "ok", engaging: found.entity.displayName || found.entity.name };
    }
    return { status: "ok", message: "Defend mode on. Will auto-engage the next hostile that gets close." };
  },
};

// ---------------------------------------------------------------------
// HTTP API
// ---------------------------------------------------------------------

const app = express();
app.use(express.json());

app.post("/connect", (req, res) => {
  try {
    createBot(req.body || {});
    res.json({ status: "ok", connecting: true });
  } catch (e) {
    res.status(500).json({ status: "error", message: e.message });
  }
});

app.post("/disconnect", (_req, res) => {
  disconnectBot();
  res.json({ status: "ok" });
});

app.get("/status", (_req, res) => {
  if (!bot || !bot.entity) {
    return res.json({ connected: false });
  }
  const pos = bot.entity.position;
  const player = followTarget ? bot.players[followTarget] : Object.values(bot.players).find((p) => p.username !== bot.username);
  const distanceToPlayer = player && player.entity ? Math.round(player.entity.position.distanceTo(pos)) : null;

  const nearby = Object.values(bot.entities)
    .filter((e) => e !== bot.entity && e.position && e.position.distanceTo(pos) < 16)
    .slice(0, 12)
    .map((e) => e.name || e.username || e.displayName)
    .filter(Boolean);

  const inventory = {};
  for (const item of bot.inventory.items()) {
    inventory[item.name] = (inventory[item.name] || 0) + item.count;
  }

  res.json({
    connected: true,
    health: bot.health,
    food: bot.food,
    position: [Math.round(pos.x), Math.round(pos.y), Math.round(pos.z)],
    dimension: bot.game ? bot.game.dimension : "overworld",
    distance_to_player: distanceToPlayer,
    target: currentTargetEntity ? (currentTargetEntity.displayName || currentTargetEntity.name) : null,
    target_distance: currentTargetEntity ? Math.round(currentTargetEntity.position.distanceTo(pos)) : null,
    inventory,
    nearby,
    current_action: currentActionLabel,
  });
});

app.get("/events", (req, res) => {
  const since = Number(req.query.since || 0);
  res.json({ events: events.filter((e) => e.id > since) });
});

app.post("/action", async (req, res) => {
  const { name, args } = req.body || {};
  const fn = actions[name];
  if (!fn) {
    return res.status(400).json({ status: "error", message: `Unknown action '${name}'.` });
  }
  try {
    const result = await fn(args || {});
    res.json(result);
  } catch (e) {
    res.status(400).json({ status: "error", message: e.message });
  }
});

app.listen(PORT, "127.0.0.1", () => {
  console.log(`[Bot] Arika Minecraft bridge listening on http://127.0.0.1:${PORT}`);
});

process.on("SIGINT", () => { disconnectBot(); process.exit(0); });
process.on("SIGTERM", () => { disconnectBot(); process.exit(0); });
