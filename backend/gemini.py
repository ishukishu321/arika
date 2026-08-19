import json
import os
import time
from google import genai
from google.genai import types
from google.genai import errors as genai_errors

from backend import settings_manager
from backend import user_context
from backend import admin_manager
from backend import gemini_tools
from backend import minecraft_manager

# Directory where this script is located
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
API_KEY_FILE = os.path.join(SCRIPT_DIR, "memory", "api_key.txt")
SYSTEM_INSTRUCTION_PATH = os.path.join(SCRIPT_DIR, "system_instruction.txt")
SYSTEM_INSTRUCTION_GUEST_PATH = os.path.join(SCRIPT_DIR, "system_instruction_guest.txt")

_client = None
_BASE_SYSTEM_INSTRUCTION = None
_GUEST_SYSTEM_INSTRUCTION = None


class MissingAPIKeyError(Exception):
    """Raised when no Gemini API key is configured anywhere (env / file)."""
    pass


def _load_system_instruction():
    """Pick the right persona file depending on whether the CURRENT user is
    a guest or a real logged-in account."""
    global _BASE_SYSTEM_INSTRUCTION, _GUEST_SYSTEM_INSTRUCTION

    if user_context.is_guest():
        if _GUEST_SYSTEM_INSTRUCTION is None:
            try:
                with open(SYSTEM_INSTRUCTION_GUEST_PATH, "r", encoding="utf-8") as f:
                    _GUEST_SYSTEM_INSTRUCTION = f.read()
            except FileNotFoundError:
                _GUEST_SYSTEM_INSTRUCTION = "You are a helpful assistant talking to a guest."
        return _GUEST_SYSTEM_INSTRUCTION

    if _BASE_SYSTEM_INSTRUCTION is None:
        try:
            with open(SYSTEM_INSTRUCTION_PATH, "r", encoding="utf-8") as f:
                _BASE_SYSTEM_INSTRUCTION = f.read()
        except FileNotFoundError:
            _BASE_SYSTEM_INSTRUCTION = "You are a helpful assistant."
    return _BASE_SYSTEM_INSTRUCTION


def has_api_key() -> bool:
    """Check (without raising/blocking) whether a key is available."""
    api_key = os.getenv("GEMINI_API_KEY")
    if api_key and api_key.strip():
        return True

    if os.path.exists(API_KEY_FILE):
        try:
            with open(API_KEY_FILE, "r", encoding="utf-8") as f:
                return bool(f.read().strip())
        except Exception:
            return False

    return False


def save_api_key(api_key: str):
    """Save/replace the Gemini API key (used by the web settings endpoint
    and by the CLI's interactive prompt). Resets the cached client so the
    new key takes effect immediately. This is a single, app-wide key shared
    by every account and guests alike (not per-user)."""
    global _client

    api_key = (api_key or "").strip()
    if not api_key:
        raise ValueError("Gemini API key is required.")

    os.makedirs(os.path.dirname(API_KEY_FILE), exist_ok=True)
    with open(API_KEY_FILE, "w", encoding="utf-8") as f:
        f.write(api_key)

    _client = None  # force re-init with the new key


def _load_api_key():
    api_key = os.getenv("GEMINI_API_KEY")
    if api_key and api_key.strip():
        return api_key.strip()

    if os.path.exists(API_KEY_FILE):
        try:
            with open(API_KEY_FILE, "r", encoding="utf-8") as f:
                stored_key = f.read().strip()
                if stored_key:
                    return stored_key
        except Exception:
            pass

    return None


def _get_api_key():
    """Return a usable API key WITHOUT ever calling input().
    The web app checks has_api_key() first and prompts via the browser
    (see /api/settings/api-key). The CLI prompts interactively itself and
    calls save_api_key() before this function is ever reached."""
    api_key = _load_api_key()
    if api_key:
        return api_key
    raise MissingAPIKeyError(
        "No Gemini API key configured. Set it via the web Settings panel "
        "or the GEMINI_API_KEY environment variable."
    )


def _get_client():
    global _client
    if _client is None:
        api_key = _get_api_key()
        _client = genai.Client(api_key=api_key)
    return _client


def _extract_text_from_response(response) -> str:
    """Return text from Gemini responses across different SDK versions.

    Newer google-genai responses can expose the finished text via
    response.candidates[].content.parts[].text even when response.text is
    empty or unavailable. This keeps the app working regardless of the SDK
    version in use.
    """
    text = getattr(response, "text", None)
    if text:
        return text

    parts = []
    for candidate in getattr(response, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", []) or []:
            part_text = getattr(part, "text", None)
            if part_text:
                parts.append(part_text)

    if parts:
        return "".join(parts)

    return ""


def _call_with_retry(fn, max_attempts: int = 4, base_delay: float = 8.0):
    """Run a Gemini API call, retrying ONLY on 429 (RESOURCE_EXHAUSTED)
    with exponential backoff (8s, 16s, 32s...). Free-tier models get
    RPM (per-minute) limits that a burst of calls in one request — the
    main reply + memory review + plan auto-continuation steps — can hit
    even though the daily quota shown in AI Studio still looks fine.
    Any other error (bad key, safety block, etc.) is raised immediately,
    no point retrying those.
    """
    last_err = None
    for attempt in range(max_attempts):
        try:
            return fn()
        except genai_errors.ClientError as e:
            is_rate_limit = getattr(e, "status_code", None) == 429 \
                or "RESOURCE_EXHAUSTED" in str(e)
            if not is_rate_limit or attempt == max_attempts - 1:
                raise
            last_err = e
            delay = base_delay * (2 ** attempt)
            print(f"[Gemini] 429 rate limited, retrying in {delay:.0f}s "
                  f"(attempt {attempt + 1}/{max_attempts})")
            time.sleep(delay)
    raise last_err


def ask_gemini(
    prompt: str,
    model: str = None,
    image_bytes: bytes = None,
    image_mime_type: str = None,
    enable_tools: bool = False,
):
    """Call Gemini.

    enable_tools=False (default): behaves exactly like before — plain text
    in, plain text out. Used by internal one-off calls that never need to
    trigger automation (see_screen/see_camera vision Q&A, email/session
    summarization) so they don't change behavior.

    enable_tools=True: attaches the native function-calling tool schema
    (backend/gemini_tools.py) so Gemini can return structured function
    calls instead of hand-typed <COMMAND> JSON, and returns
    {"text": str, "commands": [{"action": ..., "data": {...}}, ...]}.
    Use this for real chat turns (web app / CLI).
    """
    if model is None:
        model = settings_manager.get_gemini_model()

    base_system_instruction = _load_system_instruction()

    profile_path = user_context.get_path("profile")
    try:
        with open(profile_path, "r", encoding="utf-8") as f:
            profile = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        profile = {}

    minecraft_active = minecraft_manager.is_active()

    system_instruction = f"""
{base_system_instruction}

==============================
KNOWN USER INFORMATION
==============================

{json.dumps(profile, indent=4)}
"""

    # Minecraft gameplay context (controls, action-API explanation, current
    # game state) is only appended to the prompt while mode is ACTIVE — see
    # backend/minecraft_manager.py. This keeps every normal chat turn free
    # of Minecraft-specific tokens.
    if minecraft_active:
        status = minecraft_manager.get_compact_status()
        system_instruction += f"""

==============================
MINECRAFT MODE — ACTIVE
==============================

You are currently playing Minecraft with the Admin. A local bot handles
reflexes (movement, PvP, navigation) for you — you only make high-level
decisions and call the action tools (follow_player, stop, attack_target,
move_to, look_at, eat_food, equip, defend_player). You do NOT get raw
keyboard/mouse access to the game.

Current compact game state (health/food/position/target/inventory/nearby,
NOT a full dump):
{json.dumps(status, indent=2) if status else "(bot not connected yet — nothing to report)"}
"""

    # Build the message contents. When an image is attached we send the raw
    # bytes as an inline Part alongside the text prompt so Gemini actually
    # SEES the picture — not just a file path/URL sitting in the text (a
    # path string means nothing to the model; it can't fetch it itself).
    if image_bytes:
        contents = [
            prompt,
            types.Part.from_bytes(
                data=image_bytes,
                mime_type=image_mime_type or "image/jpeg",
            ),
        ]
    else:
        contents = prompt

    config = {"system_instruction": system_instruction}

    if enable_tools:
        # Only offer PC/phone/browser/mouse/keyboard tools to whoever
        # command_router.py will actually let use them (Admin, not guest).
        # Non-admin turns still get save_profile/review_mem/task_status.
        include_automation = (not user_context.is_guest()) and admin_manager.is_admin() \
            and user_context.get_user_id() == admin_manager.get_admin()
        config["tools"] = gemini_tools.build_tools(include_automation, minecraft_active=minecraft_active)
        # We route function calls through command_router.py ourselves —
        # never let the SDK try to auto-execute them.
        config["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(disable=True)

    response = _call_with_retry(
        lambda: _get_client().models.generate_content(
            model=model,
            contents=contents,
            config=config,
        )
    )

    model_text = _extract_text_from_response(response)

    if not enable_tools:
        return model_text

    commands = []
    for call in (response.function_calls or []):
        args = dict(call.args or {})
        if call.name == "save_profile":
            # save_profile's own tool parameter is called "data" (the
            # profile fields themselves), which would otherwise collide
            # with the command envelope's "data" key below and double-nest.
            args = args.get("data", args)
        commands.append({"action": call.name, "data": args})

    return {"text": model_text, "commands": commands}
