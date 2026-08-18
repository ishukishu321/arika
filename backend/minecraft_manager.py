"""
Minecraft capability manager.
==============================
Arika = brain (LLM, high-level decisions).
minecraft_bot/bot.js (Node + mineflayer) = reflexes (movement, PvP,
target selection, navigation — no LLM round trip per tick).

This module is the Python-side bridge between the two:

  * Mode gating — Minecraft context/tools are INACTIVE by default. Nothing
    in here runs, and nothing gets injected into the prompt, until
    `set_mode(True)` is called (via the `minecraft_mode` Gemini tool /
    command_router action). `set_mode(False)` tears the bot process +
    polling down again. Minecraft memories stay retrievable regardless
    (see backend/memory_manager/minecraft_memory.py).

  * Process management — spawns/stops the Node bot (minecraft_bot/bot.js)
    as a child process, talking to it over a small local HTTP API
    (see minecraft_bot/bot.js for the server side).

  * Status polling — every ~12s (10-15s window from spec) pulls a COMPACT
    status dump from the bot and writes only the durable bits into
    minecraft_memory.world_state. Full dumps are never sent to the LLM.

  * Event-driven — the bot pushes discrete events (PLAYER_DAMAGED,
    TARGET_FOUND, LOW_HEALTH, DEATH, ...) into its own queue; this module
    drains that queue and records each event into minecraft_memory as it
    happens, instead of waiting for the next poll tick.

  * Action API — thin wrappers (follow_player, attack_target, move_to,
    look_at, eat_food, equip, defend_player, stop) that POST to the bot's
    /action endpoint. Arika calls these; she never gets raw keyboard/mouse
    access to the game.
"""

import json
import os
import subprocess
import threading
import time
import shutil

try:
    import requests
except ImportError:  # requests is in requirements.txt, but fail soft
    requests = None

from backend.memory_manager import minecraft_memory
from backend import settings_manager

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
BOT_DIR = os.path.join(PROJECT_ROOT, "minecraft_bot")
BOT_ENTRY = os.path.join(BOT_DIR, "bot.js")

BOT_HOST = "127.0.0.1"
DEFAULT_BOT_PORT = 39399
BOT_PORT = int(os.environ.get("ARIKA_MC_BOT_PORT") or os.environ.get("PORT") or str(DEFAULT_BOT_PORT))
BOT_BASE_URL = f"http://{BOT_HOST}:{BOT_PORT}"

POLL_INTERVAL_SEC = 15  # environment-awareness tick, every 15s while active
HTTP_TIMEOUT_SEC = 5

_mode_lock = threading.Lock()
_mode_active = False

_bot_process = None
_bot_lock = threading.Lock()

_poll_thread = None
_poll_stop_event = threading.Event()

_last_status = {}
_last_event_id = 0

# Optional hook set by app.py at startup (kept out of this module to avoid a
# circular import — gemini.py already imports minecraft_manager). Called
# every poll tick with (compact_status_dict, new_events_list); decides for
# itself whether anything is worth a proactive comment.
_awareness_callback = None
_awareness_last_event_id = 0


def register_awareness_callback(fn):
    """app.py calls this once at startup to wire in the proactive
    environment-awareness check (see backend/minecraft_awareness.py)."""
    global _awareness_callback
    _awareness_callback = fn

# Actions Arika is allowed to call. Each maps to bot.js's /action endpoint.
# Kept as an explicit whitelist (same pattern as command_router's
# AUTOMATION_ACTIONS) so a stray tool name can never reach the bot.
ACTION_NAMES = {
    "follow_player",
    "stop",
    "attack_target",
    "move_to",
    "look_at",
    "eat_food",
    "equip",
    "defend_player",
}


# ---------------------------------------------------------------------
# Mode activation
# ---------------------------------------------------------------------

def is_active() -> bool:
    with _mode_lock:
        return _mode_active


def set_mode(active: bool, connect: dict = None) -> dict:
    """Turn Minecraft context on/off.

    active=True:
      - starts the Node bot process if not already running
      - optionally connects it to a server (host/port/username/version in
        `connect`, falling back to saved settings)
      - starts the background status-poll + event-drain thread
    active=False:
      - stops polling (bot process is left running so the character
        doesn't just vanish mid-world; call disconnect()/stop_bot()
        separately if you want it to fully log off)
    """
    global _mode_active
    active = bool(active)

    with _mode_lock:
        _mode_active = active

    if active:
        ok, msg = _ensure_bot_process()
        if not ok:
            with _mode_lock:
                _mode_active = False
            return {"status": "error", "message": msg, "minecraft_mode": False}

        world_connected = False
        connect_error = None

        if requests is not None:
            settings = settings_manager.load_settings()
            merged_connect = {
                "host": (connect or {}).get("host") or settings.get("minecraft_host"),
                "port": (connect or {}).get("port") or settings.get("minecraft_port"),
                "username": (connect or {}).get("username") or settings.get("minecraft_username"),
                "auth": (connect or {}).get("auth") or settings.get("minecraft_auth"),
            }
            try:
                requests.post(f"{BOT_BASE_URL}/connect", json=merged_connect, timeout=HTTP_TIMEOUT_SEC)
            except Exception as e:
                connect_error = f"Couldn't reach the bot process: {e}"
                print(f"[Minecraft] connect request failed: {e}")

            if connect_error is None:
                # /connect replies instantly ("connecting: true") but the
                # actual mineflayer spawn/kick/error happens async, a beat
                # later. Poll /status + /events for a few seconds so we
                # report what REALLY happened in-game, not just "the HTTP
                # request was accepted" — otherwise Arika ends up telling
                # the user "connected!" even when the join silently failed
                # (wrong port, refused, kicked, etc).
                last_event_id_before = _last_event_id
                for _ in range(16):  # ~8s total (16 * 0.5s)
                    time.sleep(0.5)
                    try:
                        r = requests.get(f"{BOT_BASE_URL}/status", timeout=1.5)
                        if r.status_code == 200 and r.json().get("connected"):
                            world_connected = True
                            break
                    except Exception:
                        pass
                    try:
                        ev = requests.get(
                            f"{BOT_BASE_URL}/events",
                            params={"since": last_event_id_before},
                            timeout=1.5,
                        )
                        if ev.status_code == 200:
                            for e in ev.json().get("events", []):
                                if e.get("type") in ("KICKED", "ERROR"):
                                    connect_error = f"{e.get('type')}: {e.get('detail')}"
                                    break
                    except Exception:
                        pass
                    if connect_error:
                        break

                if not world_connected and not connect_error:
                    connect_error = (
                        "Timed out waiting for the bot to join — check the "
                        "Minecraft port (TLauncher 'Open to LAN' gives a new "
                        "one every time) and that the world is still open."
                    )

        _start_polling()
        minecraft_memory.add_record("Minecraft mode activated.", "note")
    else:
        world_connected = False
        connect_error = None
        _stop_polling()
        minecraft_memory.add_record("Minecraft mode deactivated.", "note")

    return {
        "status": "ok" if (not active or world_connected) else "error",
        "minecraft_mode": is_active(),
        "world_connected": world_connected,
        "message": connect_error,
    }


# ---------------------------------------------------------------------
# Bot process management
# ---------------------------------------------------------------------

def _node_available() -> bool:
    return shutil.which("node") is not None


def _ensure_bot_process():
    global _bot_process
    with _bot_lock:
        if _bot_process is not None and _bot_process.poll() is None:
            return True, "already running"

        if not _node_available():
            return False, (
                "Node.js not found on PATH. Run setup.bat again (it now installs "
                "Node.js + the minecraft_bot dependencies), or install Node.js "
                "manually from https://nodejs.org and re-run `npm install` inside "
                "the minecraft_bot folder."
            )

        if not os.path.exists(BOT_ENTRY):
            return False, f"minecraft_bot/bot.js not found at {BOT_ENTRY}"

        node_modules = os.path.join(BOT_DIR, "node_modules")
        if not os.path.isdir(node_modules):
            return False, (
                "minecraft_bot dependencies aren't installed yet. Run: "
                "cd minecraft_bot && npm install (setup.bat does this "
                "automatically too)."
            )

        try:
            _bot_process = subprocess.Popen(
                ["node", BOT_ENTRY],
                cwd=BOT_DIR,
                env={**os.environ, "ARIKA_MC_BOT_PORT": str(BOT_PORT), "PORT": str(BOT_PORT)},
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except Exception as e:
            return False, f"Failed to launch Node bot process: {e}"

        # CRITICAL: nothing was ever reading _bot_process.stdout before this.
        # bot.js logs every single event via console.log (pushEvent()) — once
        # the OS pipe buffer fills up (~64KB), Node's stdout.write() blocks
        # SYNCHRONOUSLY, freezing the entire (single-threaded) Node event
        # loop. That explains both the earlier "/connect Read timed out"
        # (HTTP server can't respond while frozen) and mid-game disconnects
        # (mineflayer misses Minecraft's keepalive packets while frozen, and
        # the server kicks it for timing out — even with the world still
        # open). Draining continuously in a daemon thread prevents this, and
        # as a bonus surfaces bot.js's own logs for debugging.
        def _drain_stdout(proc):
            try:
                for line in iter(proc.stdout.readline, ""):
                    if line:
                        print(f"[Bot.js] {line.rstrip()}")
            except Exception:
                pass

        threading.Thread(target=_drain_stdout, args=(_bot_process,), daemon=True).start()

        # give the HTTP server a moment to bind before anyone calls it
        started_ok = False
        for _ in range(20):
            if _bot_process.poll() is not None:
                # Process already exited — almost always EADDRINUSE (an
                # orphaned node.exe from a previous session still squatting
                # on the port) or a startup crash. The drain thread above
                # already printed whatever it said (look for "[Bot.js]"
                # lines just above in this terminal).
                _bot_process = None
                return False, (
                    "Node bot process exited immediately instead of staying "
                    "up — likely port "
                    f"{BOT_PORT} is already in use by a leftover node.exe from a "
                    "previous session (check Task Manager and end it), or a "
                    "startup crash. Check the '[Bot.js]' lines just printed "
                    "above for the exact reason."
                )
            if _http_ok():
                started_ok = True
                break
            time.sleep(0.25)

        if not started_ok:
            return False, (
                f"Node bot process started but never responded on "
                f"http://{BOT_HOST}:{BOT_PORT} within 5s — it may be stuck. Check "
                "the terminal running bot.js for errors, or kill any stray "
                "node.exe processes and try again."
            )

        return True, "started"


def stop_bot():
    """Fully stop the Node bot process (disconnects from the server too)."""
    global _bot_process
    _stop_polling()
    with _bot_lock:
        if _bot_process is not None and _bot_process.poll() is None:
            try:
                if requests is not None:
                    requests.post(f"{BOT_BASE_URL}/disconnect", timeout=HTTP_TIMEOUT_SEC)
            except Exception:
                pass
            _bot_process.terminate()
            try:
                _bot_process.wait(timeout=5)
            except Exception:
                _bot_process.kill()
        _bot_process = None


def _http_ok() -> bool:
    if requests is None:
        return False
    try:
        r = requests.get(f"{BOT_BASE_URL}/status", timeout=1.5)
        return r.status_code == 200
    except Exception:
        return False


# ---------------------------------------------------------------------
# Status polling + event draining (background thread)
# ---------------------------------------------------------------------

def _poll_loop():
    global _last_status, _last_event_id
    while not _poll_stop_event.is_set():
        try:
            _drain_events()
            _poll_status()
            _run_awareness_check()
        except Exception as e:
            print(f"[Minecraft] poll loop error: {e}")
        _poll_stop_event.wait(POLL_INTERVAL_SEC)


def _run_awareness_check():
    """Every poll tick (~15s), if a callback is registered (see
    register_awareness_callback), hand it the latest compact status plus any
    NEW events since the last awareness check. Uses its own event cursor
    (_awareness_last_event_id) independent of _drain_events' cursor above —
    both read the same /events feed but each keeps its own position, so
    draining for memory doesn't consume events the awareness check needs."""
    global _awareness_last_event_id
    if _awareness_callback is None or requests is None:
        return
    if not is_active():
        return
    status = get_compact_status()
    if not status or not status.get("connected"):
        return
    events = []
    try:
        r = requests.get(
            f"{BOT_BASE_URL}/events",
            params={"since": _awareness_last_event_id},
            timeout=HTTP_TIMEOUT_SEC,
        )
        if r.status_code == 200:
            events = r.json().get("events", [])
            if events:
                _awareness_last_event_id = max(
                    _awareness_last_event_id, max(e.get("id", 0) for e in events)
                )
    except Exception:
        events = []

    try:
        _awareness_callback(status, events)
    except Exception as e:
        print(f"[Minecraft] awareness callback error: {e}")


def _poll_status():
    global _last_status
    if requests is None:
        return
    try:
        r = requests.get(f"{BOT_BASE_URL}/status", timeout=HTTP_TIMEOUT_SEC)
        if r.status_code != 200:
            return
        status = r.json()
    except Exception:
        return

    _last_status = status

    # Only the durable bits go into long-lived world_state — position,
    # dimension, current objective/action, discovered base. The noisy
    # per-tick stuff (exact health/food ticking up/down) stays out of
    # persistent memory and is only used live via get_compact_status().
    minecraft_memory.update_world_state({
        "last_position": status.get("position"),
        "dimension": status.get("dimension"),
        "current_action": status.get("current_action"),
        "last_seen": time.strftime("%Y-%m-%d %H:%M:%S"),
    })


def _drain_events():
    """Pull any new discrete events (PLAYER_DAMAGED, TARGET_FOUND, ...)
    since the last drain and log each one immediately, instead of waiting
    for the next poll tick — these matter enough to record right away."""
    global _last_event_id
    if requests is None:
        return
    try:
        r = requests.get(f"{BOT_BASE_URL}/events", params={"since": _last_event_id}, timeout=HTTP_TIMEOUT_SEC)
        if r.status_code != 200:
            return
        payload = r.json()
    except Exception:
        return

    for ev in payload.get("events", []):
        _last_event_id = max(_last_event_id, ev.get("id", _last_event_id))
        minecraft_memory.add_record(f"{ev.get('type', 'EVENT')}: {ev.get('detail', '')}", "event")


def _start_polling():
    global _poll_thread
    if _poll_thread is not None and _poll_thread.is_alive():
        return
    _poll_stop_event.clear()
    _poll_thread = threading.Thread(target=_poll_loop, daemon=True)
    _poll_thread.start()


def _stop_polling():
    _poll_stop_event.set()


# ---------------------------------------------------------------------
# Compact status (for injecting into the prompt WHILE mode is active)
# ---------------------------------------------------------------------

def get_compact_status() -> dict:
    """Latest compact status dump (health/food/position/target/inventory/
    nearby/current_action) — the small JSON from the spec, not a full game
    dump. Cached from the last poll; call refresh_status() to force one."""
    return _last_status or {}


def refresh_status() -> dict:
    _poll_status()
    return get_compact_status()


# ---------------------------------------------------------------------
# Action API — Arika's only way to touch the game
# ---------------------------------------------------------------------

def run_action(name: str, args: dict = None) -> dict:
    if name not in ACTION_NAMES:
        return {"status": "error", "message": f"Unknown Minecraft action '{name}'."}
    if not is_active():
        return {"status": "error", "message": "Minecraft mode isn't active. Call minecraft_mode(active=true) first."}
    if requests is None:
        return {"status": "error", "message": "The 'requests' package isn't installed (pip install -r requirements.txt)."}

    try:
        r = requests.post(
            f"{BOT_BASE_URL}/action",
            json={"name": name, "args": args or {}},
            timeout=HTTP_TIMEOUT_SEC,
        )
        result = r.json() if r.content else {}
    except Exception as e:
        return {"status": "error", "message": f"Bot didn't respond: {e}"}

    minecraft_memory.add_record(f"action {name}({json.dumps(args or {})}) -> {result.get('status', 'unknown')}", "action")
    return result
