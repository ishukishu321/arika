"""
Native Gemini function-calling tool schema for Arika.

Why this file exists
=====================
Before this, every action (open_app, browser_click, system_power, ...) was
documented as plain English text inside system_instruction.txt, and the
model was expected to *remember* all ~60 of them from a single giant wall
of text and then hand-type an exact `<COMMAND>{...}</COMMAND>` JSON block.
That's unreliable by construction — it's a free-text guessing game instead
of a structured API contract, and it gets worse as the instruction grows
(the model's attention to actions buried in the middle of a 20k-character
prompt is weaker than to the first/last few).

This file defines each action as a real Gemini `FunctionDeclaration`
(name, description, JSON-schema parameters). Gemini's API keeps track of
these on every turn and returns a structured `function_call` (name + args)
when it wants to act — no more parsing hand-written JSON out of prose.

`command_router.execute()` already accepts `{"action": ..., "data": {...}}`
dicts, so nothing downstream of the model needs to change: we just convert
`response.function_calls` into that same dict shape.
"""

from google.genai import types

# ---------------------------------------------------------------------------
# Spec: action_name -> (description, {param_name: (json_schema, required)})
# ---------------------------------------------------------------------------

def _p(type_, description, enum=None, default=None):
    schema = {"type": type_, "description": description}
    if enum is not None:
        schema["enum"] = enum
    return schema


_AUTOMATION_SPEC = {
    "open_app": ("Open a desktop application by name (e.g. chrome, notepad, spotify).", {
        "name": (_p("string", "The app to open."), True),
    }),
    "open_website": ("Open a URL in the default browser.", {
        "url": (_p("string", "The website URL."), True),
    }),
    "play_media": ("Open a streaming service with a song/video pre-searched (queued, one click to actually play).", {
        "query": (_p("string", "What to search for."), True),
        "service": (_p("string", "Streaming service, defaults to youtube."), False),
    }),
    "create_folder": ("Create a folder on the Admin's PC.", {
        "path": (_p("string", "Path to create. Use '~' for the home dir, e.g. ~/Desktop/NewFolder. Never invent a full C:/Users/<name> path."), True),
    }),
    "create_file": ("Create a file (optionally with text content) on the Admin's PC.", {
        "path": (_p("string", "Path to create, e.g. ~/Desktop/notes.txt."), True),
        "content": (_p("string", "File contents (optional)."), False),
    }),
    "take_screenshot": ("Take a screenshot of the PC's screen and save it.", {}),
    "close_app": ("Close/kill a running desktop application by name.", {
        "name": (_p("string", "The app to close."), True),
    }),
    "volume_control": ("Change system volume.", {
        "direction": (_p("string", "up, down, or mute.", enum=["up", "down", "mute"]), True),
    }),
    "media_control": ("Control whatever media is currently playing (no login needed).", {
        "action": (_p("string", "play_pause, next, or previous.", enum=["play_pause", "next", "previous"]), True),
    }),
    "play_on_youtube": ("Actually auto-play a song/video on YouTube (not just open + search).", {
        "query": (_p("string", "What to play."), True),
    }),
    "set_brightness": ("Set screen brightness.", {
        "level": (_p("integer", "Brightness level, 0-100."), True),
    }),
    "get_clipboard": ("Read the current clipboard text.", {}),
    "set_clipboard": ("Write text to the clipboard.", {
        "text": (_p("string", "Text to copy."), True),
    }),
    "lock_screen": ("Lock the PC screen.", {}),
    "system_power": ("Shutdown, restart, or sleep the PC. DESTRUCTIVE: only call with confirm=true after the Admin has explicitly confirmed in plain text on a previous turn.", {
        "action": (_p("string", "shutdown, restart, or sleep.", enum=["shutdown", "restart", "sleep"]), True),
        "confirm": (_p("boolean", "Must be true, and only after the Admin explicitly confirmed."), False),
    }),
    "system_info": ("Get basic PC system info (OS, CPU, RAM, etc.).", {}),
    "open_folder": ("Open a folder in the file explorer.", {
        "path": (_p("string", "Folder path, e.g. ~/Downloads."), True),
    }),
    "list_open_windows": ("List currently open windows on the PC.", {}),
    "delete_path": ("Delete a file/folder (goes to Recycle Bin, not permanent). DESTRUCTIVE: only call with confirm=true after explicit confirmation.", {
        "path": (_p("string", "Path to delete."), True),
        "confirm": (_p("boolean", "Must be true, and only after the Admin explicitly confirmed."), False),
    }),
    "send_whatsapp_message": ("Send a WhatsApp message via the PC (opens WhatsApp Web pre-filled).", {
        "phone": (_p("string", "Phone number with country code, e.g. +91XXXXXXXXXX."), True),
        "message": (_p("string", "Message text."), True),
    }),
    "open_web_search": ("Open a web search for a query in the default browser.", {
        "query": (_p("string", "Search query."), True),
    }),
    "send_email": ("Send an email using the saved email credentials.", {
        "to": (_p("string", "Recipient address."), True),
        "subject": (_p("string", "Subject line."), True),
        "body": (_p("string", "Email body."), True),
    }),
    "webcam_photo": ("Take a photo using the PC's webcam.", {}),
    "mic_mute": ("Mute/unmute the PC microphone.", {
        "state": (_p("string", "on or off.", enum=["on", "off"]), True),
    }),
    "set_reminder": ("Set a simple in-memory reminder (lost on app restart - prefer add_reminder for anything that should survive a restart).", {
        "text": (_p("string", "Reminder text."), True),
        "seconds_from_now": (_p("integer", "Delay in seconds."), True),
    }),
    "run_script": ("Run a named script on the PC. DESTRUCTIVE: only call with confirm=true after explicit confirmation.", {
        "name": (_p("string", "Script name."), True),
        "confirm": (_p("boolean", "Must be true, and only after the Admin explicitly confirmed."), False),
    }),
    "phone_status": ("Check whether the Admin's phone is connected via ADB.", {}),
    "phone_open_app": ("Open an app on the connected phone.", {
        "name": (_p("string", "App name."), True),
    }),
    "phone_open_website": ("Open a URL in the phone's browser.", {
        "url": (_p("string", "URL to open."), True),
    }),
    "phone_call": ("Place a phone call from the connected phone. This is the only real way to place a call (this PC has no telecom hardware).", {
        "phone": (_p("string", "Phone number to call."), True),
    }),
    "phone_lock": ("Lock the connected phone's screen.", {}),
    "phone_volume": ("Change the connected phone's volume.", {
        "direction": (_p("string", "up or down.", enum=["up", "down"]), True),
    }),
    "phone_screenshot": ("Take a screenshot of the connected phone.", {}),
    "phone_connect": ("Try to (re)connect to the Admin's phone over ADB.", {}),
    "phone_battery_status": ("Check the connected phone's battery level.", {}),
    "phone_wifi": ("Toggle the connected phone's WiFi.", {
        "state": (_p("string", "on or off.", enum=["on", "off"]), True),
    }),
    "phone_bluetooth": ("Toggle the connected phone's Bluetooth.", {
        "state": (_p("string", "on or off.", enum=["on", "off"]), True),
    }),
    "phone_send_sms": ("Pre-fill an SMS on the connected phone (Admin still has to tap send - don't claim it's definitely sent).", {
        "phone": (_p("string", "Recipient number."), True),
        "message": (_p("string", "Message text."), True),
    }),
    "phone_camera_photo": ("Take a photo with the connected phone's camera (best-effort).", {}),
    "phone_screen_mirror": ("Mirror/control the connected phone's screen live in a window (needs scrcpy installed).", {}),
    "add_reminder": ("Add a PERSISTENT reminder that survives app restarts and pings the Admin. Give either seconds_from_now OR when, not both.", {
        "text": (_p("string", "Reminder text."), True),
        "seconds_from_now": (_p("integer", "Delay in seconds (omit if using 'when')."), False),
        "when": (_p("string", "Absolute time as 'YYYY-MM-DD HH:MM' (omit if using seconds_from_now)."), False),
        "notify": (_p("boolean", "Whether to actually ping the Admin at that time (default true)."), False),
    }),
    "add_event": ("Add a persistent calendar event (defaults to NOT pinging, unlike add_reminder).", {
        "title": (_p("string", "Event title."), True),
        "when": (_p("string", "Absolute time as 'YYYY-MM-DD HH:MM'."), True),
        "notify": (_p("boolean", "Whether to ping the Admin at that time (default false)."), False),
    }),
    "list_reminders": ("List upcoming reminders/events.", {
        "limit": (_p("integer", "Max number to return (default 20)."), False),
    }),
    "delete_reminder": ("Delete a reminder/event by its id (get the id from list_reminders first).", {
        "id": (_p("string", "The reminder/event id."), True),
    }),
    "list_plugins": ("List installed custom plugins.", {}),
    "run_plugin": ("Run a custom plugin by name. DESTRUCTIVE-FEELING (arbitrary code): only call with confirm=true after explicit confirmation.", {
        "plugin": (_p("string", "Plugin name."), True),
        "params": (_p("object", "Parameters to pass to the plugin (optional)."), False),
        "confirm": (_p("boolean", "Must be true, and only after the Admin explicitly confirmed."), False),
    }),
    "read_email": ("Read recent emails (read-only, raw list, no summarizing).", {
        "count": (_p("integer", "How many to fetch (default 5)."), False),
        "folder": (_p("string", "Mail folder (default INBOX)."), False),
        "unread_only": (_p("boolean", "Only unread emails (default false)."), False),
    }),
    "summarize_email": ("Read AND summarize recent emails in plain language (read-only).", {
        "count": (_p("integer", "How many to fetch (default 5)."), False),
        "folder": (_p("string", "Mail folder (default INBOX)."), False),
        "unread_only": (_p("boolean", "Only unread emails (default false)."), False),
    }),
    "browser_open": ("Open a URL in a persistent, controllable browser session (unlike open_website, this session stays open across turns for clicking/typing/reading).", {
        "url": (_p("string", "URL to open."), True),
    }),
    "browser_click": ("Click something in the controlled browser by its visible text or a CSS selector.", {
        "text": (_p("string", "Visible text to click (optional if selector given)."), False),
        "selector": (_p("string", "CSS selector to click (optional if text given)."), False),
    }),
    "browser_type": ("Type into a field in the controlled browser.", {
        "text": (_p("string", "Text to type."), True),
        "selector": (_p("string", "CSS selector of the field (optional - types into whatever's focused if omitted)."), False),
        "submit": (_p("boolean", "Press Enter after typing (default false)."), False),
    }),
    "browser_scroll": ("Scroll the controlled browser page.", {
        "direction": (_p("string", "up or down (default down).", enum=["up", "down"]), False),
        "amount": (_p("integer", "Scroll amount in pixels (default 600)."), False),
    }),
    "browser_get_text": ("Read the controlled browser page's visible text back.", {
        "selector": (_p("string", "CSS selector to read (optional - whole page if omitted)."), False),
        "max_chars": (_p("integer", "Max characters to return (default 2000)."), False),
    }),
    "browser_close": ("Close the controlled browser session.", {}),
    "mouse_move": ("Move the real mouse cursor.", {
        "x": (_p("integer", "X coordinate."), True),
        "y": (_p("integer", "Y coordinate."), True),
        "duration": (_p("number", "Movement duration in seconds (default 0.2)."), False),
    }),
    "mouse_click": ("Click the real mouse.", {
        "x": (_p("integer", "X coordinate (optional - clicks at current position if omitted)."), False),
        "y": (_p("integer", "Y coordinate (optional)."), False),
        "button": (_p("string", "left, right, or middle (default left).", enum=["left", "right", "middle"]), False),
        "double": (_p("boolean", "Double-click (default false)."), False),
    }),
    "mouse_scroll": ("Scroll the real mouse wheel (positive = up, negative = down).", {
        "amount": (_p("integer", "Scroll amount (default -300)."), False),
    }),
    "mouse_position": ("Get the current real mouse position.", {}),
    "keyboard_type": ("Type text via the real keyboard into whatever window is focused.", {
        "text": (_p("string", "Text to type."), True),
        "interval": (_p("number", "Delay between keystrokes in seconds (default 0.02)."), False),
    }),
    "keyboard_press": ("Press a single real key (e.g. enter, esc, tab, f5).", {
        "key": (_p("string", "Key to press."), True),
    }),
    "keyboard_hotkey": ("Press a real key combo (e.g. ctrl+c).", {
        "keys": (_p("array", "List of keys to press together, e.g. ['ctrl','c']."), True),
    }),
    "see_screen": ("Look at the CURRENT screen (vision) and answer a question about it. Different from take_screenshot, which just saves a file.", {
        "question": (_p("string", "What to look for/answer."), True),
    }),
    "see_camera": ("Look through the PC's webcam (vision) and answer a question about it.", {
        "question": (_p("string", "What to look for/answer."), True),
    }),
}

# Actions that touch the system in a destructive/irreversible-feeling way.
DESTRUCTIVE_ACTIONS = {"system_power", "delete_path", "run_script", "run_plugin"}

# ---------------------------------------------------------------------------
# Non-automation tools: memory + task status
# ---------------------------------------------------------------------------

_MEMORY_SPEC = {
    "save_profile": ("Save a piece of PERMANENT information about the user (name, birthday, preferred language, favourite game, long-term goals, explicit preferences). Do NOT call this for temporary plans, current mood, one-time events, or anything likely to change soon.", {
        "data": (_p("object", "Key-value pairs of permanent facts to remember, e.g. {\"favorite_game\": \"football\"}."), True),
    }),
    "review_mem": ("Search the current user's long-term memory archive by topic tags. Use at least 6 relevant lowercase, underscore-separated tags for good accuracy (e.g. user_preferences, task_history, project_notes, problem_solving, long_term_goals).", {
        "tags": (_p("object", "Map of tag_name -> {} for each search tag (use 6+ tags)."), True),
    }),
    "task_status": ("Check what automation tasks are done / pending / failed so far. The API is stateless between turns, so call this whenever the Admin asks 'what's left' or 'what did you do'.", {}),
}

# ---------------------------------------------------------------------------
# Minecraft — mode toggle (ALWAYS offered, even when Minecraft mode is off)
# and recall (ALWAYS offered, so "mera base kahan tha?" works without
# turning gameplay mode on) live in gemini_tools' always-on set below.
# The actual gameplay action API (follow_player, attack_target, ...) is
# ONLY added to the tool list while Minecraft mode is active — see
# build_tools()'s `minecraft_active` parameter — so it costs zero tokens
# on every normal chat turn.
# ---------------------------------------------------------------------------

_MINECRAFT_ALWAYS_SPEC = {
    "minecraft_mode": (
        "Turn Minecraft gameplay mode on or off. You already know you CAN play "
        "Minecraft, but detailed gameplay context/controls only load once this is "
        "on — call it with active=true when the Admin says something like 'chalo "
        "Minecraft khelte hain' / 'let's play Minecraft' / 'connect to my server', "
        "and active=false when they're done playing. "
        "IMPORTANT: leave host/port/username UNSET (do not pass them at all) unless "
        "the Admin's CURRENT message explicitly states a new value — e.g. they just "
        "typed a specific port/IP this turn. NEVER fill these from something you "
        "recall from earlier in the conversation or from a past session; a remembered "
        "port is very likely stale (TLauncher assigns a new random port every time "
        "the world is reopened) and passing it here will silently override whatever "
        "correct value the Admin already saved in Settings. When in doubt, omit them "
        "entirely and let the bot use its saved settings.", {
            "active": (_p("boolean", "true to activate Minecraft mode, false to deactivate."), True),
            "host": (_p("string", "Server address — ONLY if the Admin just typed one this message (optional)."), False),
            "port": (_p("integer", "Server port — ONLY if the Admin just typed one this message. Never infer/recall this (optional)."), False),
            "username": (_p("string", "Bot's in-game username — ONLY if the Admin just typed one this message (optional)."), False),
        },
    ),
    "recall_minecraft_memory": (
        "Recall something from Minecraft memory (base location, coordinates, "
        "past events, inventory notes, discovered places) WITHOUT turning on full "
        "gameplay mode — use this for questions like 'mera base kahan tha?' or "
        "'last time hum kis mob se lade the?' asked outside active gameplay.", {
            "query": (_p("string", "What to look for, e.g. 'base location' or 'last boss fight'."), False),
        },
    ),
}

_MINECRAFT_ACTION_SPEC = {
    "follow_player": ("Start following the Admin's in-game character around. Local pathfinding handles the actual movement — you just decide to do it.", {
        "username": (_p("string", "Player username to follow (optional — defaults to whoever else is in the world)."), False),
    }),
    "stop": ("Stop whatever the bot is currently doing (following, attacking, moving) and cancel defend mode.", {}),
    "attack_target": ("Attack a nearby hostile mob (or a specific entity). Local PvP combat handles the actual fight in real time.", {
        "name": (_p("string", "Mob type to target, e.g. 'zombie' (optional — defaults to nearest hostile)."), False),
        "entity_id": (_p("integer", "Specific entity id if you already know it (optional)."), False),
    }),
    "move_to": ("Navigate to specific coordinates. Local pathfinding handles obstacles/route.", {
        "x": (_p("number", "Target X coordinate."), True),
        "y": (_p("number", "Target Y coordinate."), True),
        "z": (_p("number", "Target Z coordinate."), True),
        "range": (_p("number", "How close counts as 'arrived', defaults to 1 block (optional)."), False),
    }),
    "look_at": ("Turn the bot's view toward a player or nearby entity (no movement).", {
        "username": (_p("string", "Player username to look at (optional)."), False),
        "entity_id": (_p("integer", "Specific entity id to look at (optional)."), False),
    }),
    "eat_food": ("Eat whatever food is available in the bot's inventory to restore hunger.", {}),
    "equip": ("Equip an item from inventory (weapon, armor, tool).", {
        "item": (_p("string", "Item name to equip, e.g. 'diamond_sword'."), True),
        "destination": (_p("string", "Where to equip it: hand, off-hand, head, torso, legs, feet. Defaults to hand.", enum=["hand", "off-hand", "head", "torso", "legs", "feet"]), False),
    }),
    "defend_player": ("Switch into defend mode: auto-engage the nearest hostile mob now, and keep auto-engaging any hostile that gets close until told to stop.", {}),
}

# ---------------------------------------------------------------------------
# Agentic planning: multi-step tasks (login to a site + do several things,
# research + summarize, any goal that needs more than one action in order).
# ---------------------------------------------------------------------------

_PLANNING_SPEC = {
    "create_plan": (
        "Call this FIRST whenever the Admin's request needs MORE THAN ONE action in "
        "order to finish (e.g. 'login to my college portal and download my fee "
        "receipt', 'log into Gmail and reply to the latest email from my teacher', "
        "'research 3 AI/ML master's programs in Japan and save a summary file'). "
        "Break the goal down into a short, plain-language to-do list, the same way "
        "Ishu would jot steps in a notebook: what to do AND how (e.g. 'Open the "
        "college portal login page using browser_open', 'Type roll number into the "
        "username field and password into the password field using browser_type', "
        "'Click the Login button using browser_click'). Do NOT call this for a single "
        "one-shot action (e.g. just 'open chrome'); call that action directly instead. "
        "After creating the plan, immediately continue by calling the first step's "
        "action(s) yourself in this same turn if you can.",
        {
            "goal": (_p("string", "One-line summary of the overall task."), True),
            "steps": (_p("array", "Ordered list of plain-language steps (strings), each describing what to do and which tool/action achieves it."), True),
        },
    ),
    "plan_status": (
        "Check the current multi-step plan's to-do list, which steps are done, "
        "in progress, failed, or still pending. Call this whenever the Admin asks "
        "'what's the status', 'what step are you on', or before continuing an "
        "in-progress plan after a break.",
        {},
    ),
    "update_plan_step": (
        "Update one step of the CURRENT plan's to-do list after you attempt it, "
        "mark it done once its action succeeded, failed if it errored or got "
        "blocked, or needs_input if you need the Admin to do something manually "
        "(e.g. solve a captcha, type a password themselves, approve a payment) "
        "before you can continue.",
        {
            "step_index": (_p("integer", "The step's index (0-based) from the plan."), True),
            "status": (_p("string", "New status for this step.", enum=["done", "failed", "needs_input", "skipped"]), True),
            "note": (_p("string", "Short note on what happened or what's needed from the Admin."), False),
        },
    ),
    "cancel_plan": (
        "Cancel/abandon the current multi-step plan entirely (Admin said stop, "
        "changed their mind, or the goal is no longer relevant).",
        {},
    ),
}


def _build_declaration(name, description, params):
    properties = {}
    required = []
    for pname, (schema, is_required) in params.items():
        properties[pname] = schema
        if is_required:
            required.append(pname)

    parameters_schema = {
        "type": "object",
        "properties": properties,
    }
    if required:
        parameters_schema["required"] = required

    kwargs = {"name": name, "description": description}
    if properties:
        kwargs["parameters_json_schema"] = parameters_schema

    return types.FunctionDeclaration(**kwargs)


def build_tools(include_automation: bool, minecraft_active: bool = False) -> list:
    """Build the list of google.genai `Tool` objects for this turn.

    include_automation=False (guests, or non-admin logged-in users) leaves
    out all PC/phone/browser/mouse/keyboard actions, since command_router
    would reject them anyway — no point offering (and burning context on)
    tools the model isn't allowed to actually use.

    minecraft_active controls only the GAMEPLAY action tools
    (follow_player, attack_target, ...). minecraft_mode (the on/off
    toggle) and recall_minecraft_memory are always offered so Arika can
    turn the capability on/off and recall past Minecraft memory even
    while gameplay mode is off.
    """
    declarations = []

    for action, (description, params) in _MEMORY_SPEC.items():
        declarations.append(_build_declaration(action, description, params))

    for action, (description, params) in _MINECRAFT_ALWAYS_SPEC.items():
        declarations.append(_build_declaration(action, description, params))

    if minecraft_active:
        for action, (description, params) in _MINECRAFT_ACTION_SPEC.items():
            declarations.append(_build_declaration(action, description, params))

    # Planning tools need automation to actually be worth anything (no point
    # building a browser-login plan for a guest who can't run browser_open),
    # so gate them the same way as the automation actions themselves.
    if include_automation:
        for action, (description, params) in _PLANNING_SPEC.items():
            declarations.append(_build_declaration(action, description, params))

    if include_automation:
        for action, (description, params) in _AUTOMATION_SPEC.items():
            declarations.append(_build_declaration(action, description, params))

    return [
        types.Tool(function_declarations=declarations),
        # Built-in tools, combined with the custom function_declarations
        # above (Gemini 3 models support mixing built-in + custom tools in
        # the same request — no separate call needed). Both are read-only
        # and safe for guests too, so they're not gated by include_automation.
        #
        # google_search: general web search grounding — the model decides
        # on its own when a query needs current/external info and searches
        # automatically, no explicit tool call from us required.
        #
        # url_context: reads the actual content of specific URL(s) the user
        # or the conversation mentions (e.g. "check this GitHub repo:
        # <link>", "what does this article say") instead of just searching
        # for the URL's title/snippet.
        types.Tool(google_search=types.GoogleSearch()),
        types.Tool(url_context=types.UrlContext()),
    ]
