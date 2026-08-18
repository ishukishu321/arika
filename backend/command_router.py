import os

from backend.memory_manager.profile import save_profile
from backend.memory_manager.long_term_mem_manager import search_memories
from backend import user_context
from backend import admin_manager
from backend import task_manager
from backend import agent_planner
from backend import automation
from backend import phone_automation
from backend import calendar_manager
from backend import plugin_manager
from backend import email_manager
from backend import browser_manager
from backend import minecraft_manager
from backend.memory_manager import minecraft_memory

# Where screenshots get saved. Same "static" pattern as chat uploads/audio
# so the web frontend could later render them if you want.
SCREENSHOT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "frontend", "static", "uploads", "screenshots",
)
PHONE_SCREENSHOT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "frontend", "static", "uploads", "phone_screenshots",
)
WEBCAM_PHOTO_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "frontend", "static", "uploads", "webcam_photos",
)
PHONE_CAMERA_PHOTO_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "frontend", "static", "uploads", "phone_camera_photos",
)

# action_name -> (automation function, how to read `target` out of `data`)
AUTOMATION_ACTIONS = {
    "open_app": lambda data: automation.open_app(data.get("name")),
    "open_website": lambda data: automation.open_website(data.get("url")),
    "play_media": lambda data: automation.play_media(
        data.get("query"), data.get("service", "youtube")
    ),
    "create_folder": lambda data: automation.create_folder(data.get("path")),
    "create_file": lambda data: automation.create_file(
        data.get("path"), data.get("content", "")
    ),
    "take_screenshot": lambda data: automation.take_screenshot(SCREENSHOT_DIR),

    # --- new batch ---
    "close_app": lambda data: automation.close_app(data.get("name")),
    "volume_control": lambda data: automation.volume_control(data.get("direction")),
    "media_control": lambda data: automation.media_control(data.get("action")),
    "play_on_youtube": lambda data: automation.play_on_youtube(data.get("query")),
    "set_brightness": lambda data: automation.set_brightness(data.get("level", 50)),
    "get_clipboard": lambda data: automation.get_clipboard(),
    "set_clipboard": lambda data: automation.set_clipboard(data.get("text")),
    "lock_screen": lambda data: automation.lock_screen(),
    "system_power": lambda data: automation.system_power(
        data.get("action"), confirm=bool(data.get("confirm", False))
    ),
    "system_info": lambda data: automation.system_info(),
    "open_folder": lambda data: automation.open_folder(data.get("path")),
    "list_open_windows": lambda data: automation.list_open_windows(),
    "delete_path": lambda data: automation.delete_path(
        data.get("path"), confirm=bool(data.get("confirm", False))
    ),
    "send_whatsapp_message": lambda data: automation.send_whatsapp_message(
        data.get("phone"), data.get("message")
    ),
    "open_web_search": lambda data: automation.open_web_search(data.get("query")),
    "send_email": lambda data: automation.send_email(
        data.get("to"), data.get("subject"), data.get("body")
    ),
    "webcam_photo": lambda data: automation.webcam_photo(WEBCAM_PHOTO_DIR),
    "mic_mute": lambda data: automation.mic_mute(data.get("state")),
    "set_reminder": lambda data: automation.set_reminder(
        data.get("text"), data.get("seconds_from_now")
    ),
    "run_script": lambda data: automation.run_script(
        data.get("name"), confirm=bool(data.get("confirm", False))
    ),

    # --- phone (via ADB) ---
    "phone_status": lambda data: phone_automation.phone_status(),
    "phone_open_app": lambda data: phone_automation.phone_open_app(data.get("name")),
    "phone_open_website": lambda data: phone_automation.phone_open_website(data.get("url")),
    "phone_call": lambda data: phone_automation.phone_call(data.get("phone")),
    "phone_lock": lambda data: phone_automation.phone_lock(),
    "phone_volume": lambda data: phone_automation.phone_volume(data.get("direction")),
    "phone_screenshot": lambda data: phone_automation.phone_screenshot(PHONE_SCREENSHOT_DIR),
    "phone_connect": lambda data: phone_automation.auto_connect(),
    "phone_battery_status": lambda data: phone_automation.phone_battery_status(),
    "phone_wifi": lambda data: phone_automation.phone_wifi(data.get("state")),
    "phone_bluetooth": lambda data: phone_automation.phone_bluetooth(data.get("state")),
    "phone_send_sms": lambda data: phone_automation.phone_send_sms(
        data.get("phone"), data.get("message")
    ),
    "phone_camera_photo": lambda data: phone_automation.phone_camera_photo(PHONE_CAMERA_PHOTO_DIR),
    "phone_screen_mirror": lambda data: phone_automation.phone_screen_mirror(),

    # --- calendar & reminders (persistent) ---
    "add_reminder": lambda data: calendar_manager.add_reminder(
        data.get("text"), data.get("seconds_from_now"), data.get("when"),
        notify=bool(data.get("notify", True)),
    ),
    "add_event": lambda data: calendar_manager.add_event(
        data.get("title"), data.get("when"), notify=bool(data.get("notify", False))
    ),
    "list_reminders": lambda data: calendar_manager.list_upcoming(data.get("limit", 20)),
    "delete_reminder": lambda data: calendar_manager.delete_reminder(data.get("id")),

    # --- plugin system ---
    "list_plugins": lambda data: plugin_manager.list_plugins(),
    "run_plugin": lambda data: plugin_manager.run_plugin(data.get("plugin"), data.get("params", {})),

    # --- email reading/summarizing ---
    "read_email": lambda data: email_manager.fetch_recent(
        data.get("count", 5), data.get("folder", "INBOX"), bool(data.get("unread_only", False))
    ),
    "summarize_email": lambda data: email_manager.summarize_recent(
        data.get("count", 5), data.get("folder", "INBOX"), bool(data.get("unread_only", False))
    ),

    # --- browser control (real Selenium session, not just webbrowser.open) ---
    "browser_open": lambda data: browser_manager.browser_open(data.get("url")),
    "browser_click": lambda data: browser_manager.browser_click(data.get("text"), data.get("selector")),
    "browser_type": lambda data: browser_manager.browser_type(
        data.get("text"), data.get("selector"), bool(data.get("submit", False))
    ),
    "browser_scroll": lambda data: browser_manager.browser_scroll(
        data.get("direction", "down"), data.get("amount", 600)
    ),
    "browser_get_text": lambda data: browser_manager.browser_get_text(
        data.get("selector"), data.get("max_chars", 2000)
    ),
    "browser_close": lambda data: browser_manager.browser_close(),

    # --- mouse + keyboard control ---
    "mouse_move": lambda data: automation.mouse_move(data.get("x"), data.get("y"), data.get("duration", 0.2)),
    "mouse_click": lambda data: automation.mouse_click(
        data.get("x"), data.get("y"), data.get("button", "left"), bool(data.get("double", False))
    ),
    "mouse_scroll": lambda data: automation.mouse_scroll(data.get("amount", -300)),
    "mouse_position": lambda data: automation.mouse_position(),
    "keyboard_type": lambda data: automation.keyboard_type(data.get("text"), data.get("interval", 0.02)),
    "keyboard_press": lambda data: automation.keyboard_press(data.get("key")),
    "keyboard_hotkey": lambda data: automation.keyboard_hotkey(data.get("keys", [])),

    # --- screen & camera understanding (vision) ---
    "see_screen": lambda data: automation.see_screen(data.get("question", ""), SCREENSHOT_DIR),
    "see_camera": lambda data: automation.see_camera(data.get("question", ""), WEBCAM_PHOTO_DIR),
}

# Actions that touch the system in a destructive/irreversible-feeling way —
# these MUST arrive with data.confirm == True, enforced again here as a
# second safety net (automation.py itself already checks too).
_REQUIRES_CONFIRM = {"system_power", "delete_path", "run_script", "run_plugin"}

# What to store as the task's "target" label, per action (just for a
# readable task list — doesn't affect execution).
_TARGET_KEY = {
    "open_app": "name",
    "open_website": "url",
    "play_media": "query",
    "create_folder": "path",
    "create_file": "path",
    "take_screenshot": None,
    "close_app": "name",
    "volume_control": "direction",
    "media_control": "action",
    "play_on_youtube": "query",
    "set_brightness": "level",
    "get_clipboard": None,
    "set_clipboard": "text",
    "lock_screen": None,
    "system_power": "action",
    "system_info": None,
    "open_folder": "path",
    "list_open_windows": None,
    "delete_path": "path",
    "send_whatsapp_message": "phone",
    "phone_status": None,
    "phone_open_app": "name",
    "phone_open_website": "url",
    "phone_call": "phone",
    "phone_lock": None,
    "phone_volume": "direction",
    "phone_screenshot": None,
    "phone_connect": None,
    "open_web_search": "query",
    "send_email": "to",
    "webcam_photo": None,
    "mic_mute": "state",
    "set_reminder": "text",
    "run_script": "name",
    "phone_battery_status": None,
    "phone_wifi": "state",
    "phone_bluetooth": "state",
    "phone_send_sms": "phone",
    "phone_camera_photo": None,
    "phone_screen_mirror": None,

    "add_reminder": "text",
    "add_event": "title",
    "list_reminders": None,
    "delete_reminder": "id",

    "list_plugins": None,
    "run_plugin": "plugin",

    "read_email": None,
    "summarize_email": None,

    "browser_open": "url",
    "browser_click": "text",
    "browser_type": "text",
    "browser_scroll": "direction",
    "browser_get_text": "selector",
    "browser_close": None,

    "mouse_move": None,
    "mouse_click": None,
    "mouse_scroll": "amount",
    "mouse_position": None,
    "keyboard_type": "text",
    "keyboard_press": "key",
    "keyboard_hotkey": "keys",

    "see_screen": "question",
    "see_camera": "question",
}


def _normalize_review_tags(data):
    """Accept different review_mem formats and return a flat tag dict."""
    if not isinstance(data, dict):
        return {}

    if "tags" in data:
        tags = data["tags"]
        if isinstance(tags, dict):
            return tags
        if isinstance(tags, list):
            return {str(tag): {} for tag in tags if tag}
        return {}

    normalized = {}
    for key, value in data.items():
        if isinstance(value, dict) and value:
            normalized.update(value)
        else:
            normalized[str(key)] = {}
    return normalized


def execute(command):

    action = command.get("action")
    data = command.get("data", {})

    if action == "save_profile":
        save_profile(data)

    elif action in AUTOMATION_ACTIONS:
        # Safety: automation touches YOUR PC and (via phone_automation) your
        # phone. Only the Admin account (name stored in
        # backend/memory/admin.txt) may trigger it — every other registered
        # login AND guest sessions are blocked, even if logged in.
        if not admin_manager.is_admin():
            print(f"[Command Router] Blocked automation '{action}' — not Admin")
            return {
                "status": "error",
                "message": "Automation actions are Admin-only.",
            }

        if action in _REQUIRES_CONFIRM and not bool(data.get("confirm", False)):
            return {
                "status": "error",
                "message": f"'{action}' needs explicit confirmation before it runs — ask the Admin to confirm first.",
            }

        target_key = _TARGET_KEY.get(action)
        target = data.get(target_key) if target_key else None

        task_id = task_manager.create_task(action, target)
        task_manager.mark_in_progress(task_id)

        try:
            result = AUTOMATION_ACTIONS[action](data)
            task_manager.mark_done(task_id, result=result)
            return {"status": "ok", "task_id": task_id, "result": result}
        except Exception as e:
            print(f"[Command Router] Automation '{action}' failed: {e}")
            task_manager.mark_failed(task_id, error=str(e))
            return {"status": "error", "task_id": task_id, "message": str(e)}

    elif action == "task_status":
        return task_manager.summary()

    elif action == "create_plan":
        if not admin_manager.is_admin():
            return {"status": "error", "message": "Planning is Admin-only."}
        goal = data.get("goal", "")
        steps = data.get("steps") or []
        if not isinstance(steps, list) or not steps:
            return {"status": "error", "message": "create_plan needs a non-empty 'steps' list."}
        plan = agent_planner.create_plan(goal, [str(s) for s in steps])
        return {"status": "ok", "plan": agent_planner.summary(), "plan_id": plan["id"]}

    elif action == "plan_status":
        return agent_planner.summary()

    elif action == "update_plan_step":
        if not admin_manager.is_admin():
            return {"status": "error", "message": "Planning is Admin-only."}
        step_index = data.get("step_index")
        status = data.get("status")
        note = data.get("note")
        if step_index is None or status not in ("done", "failed", "needs_input", "skipped"):
            return {"status": "error", "message": "update_plan_step needs a valid step_index and status."}
        if status == "failed":
            agent_planner.mark_step(int(step_index), status, error=note)
        else:
            agent_planner.mark_step(int(step_index), status, result=note)
        next_index = agent_planner.advance_cursor()
        return {"status": "ok", "plan": agent_planner.summary(), "next_step": next_index}

    elif action == "cancel_plan":
        agent_planner.cancel_plan()
        return {"status": "ok", "message": "Plan cancelled."}

    elif action == "review_mem":
        tags = _normalize_review_tags(data)
        
        try:
            user_id = user_context.get_user_id()
            is_guest = user_context.is_guest()
            result = search_memories(tags, user_id=user_id, is_guest=is_guest)
            return result
        except Exception as e:
            print(f"[Command Router] Error searching memories: {e}")
            return {"status": "error", "message": str(e)}

    elif action == "minecraft_mode":
        # Toggle only — never gated behind Admin-only automation, since
        # it doesn't touch the PC, only whether gameplay context loads.
        active = bool(data.get("active", False))
        connect = None
        if active and (data.get("host") or data.get("username") or data.get("port")):
            connect = {
                "host": data.get("host"),
                "port": data.get("port"),
                "username": data.get("username"),
            }
        return minecraft_manager.set_mode(active, connect=connect)

    elif action == "recall_minecraft_memory":
        query = data.get("query", "")
        recalled = minecraft_memory.recall(query)
        if not recalled:
            return {"status": "empty", "message": "No Minecraft memory found for that."}
        return {"status": "ok", "context": recalled}

    elif action in minecraft_manager.ACTION_NAMES:
        if not admin_manager.is_admin():
            return {"status": "error", "message": "Minecraft controls are Admin-only."}
        return minecraft_manager.run_action(action, data)

    else:
        print(f"[Command Router] Unknown action: {action}")