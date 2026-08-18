"""
Settings manager.
Handles app-level settings (TTS voice, wake word, model name, etc.)
Separate from profile.py, which stores facts ABOUT the user (name, birthday...).
"""

import json
import os

from backend import user_context


def _settings_file():
    return user_context.get_path("settings")

DEFAULT_SETTINGS = {
    "tts_voice": "en-US-AvaNeural",
    "wake_word": "arika",
    "stt_lang": "en-IN",
    "gemini_model": "gemini-3.1-flash-lite",
    "show_avatar": True,
    # Saved wireless-debugging address for the phone, e.g. "192.168.1.42:5555".
    # Used by phone_automation.auto_connect() to reconnect automatically
    # every time the app starts, instead of running `adb connect` by hand.
    # Leave blank if you only ever use a USB cable (auto-connect isn't
    # needed for USB — plugging in is enough).
    "phone_adb_address": "",
    # For send_email — Gmail App Password, not your normal password:
    # https://myaccount.google.com/apppasswords
    "email_address": "",
    "email_app_password": "",
    # For browser_control ATTACH MODE — leave blank to use LAUNCH MODE
    # (Selenium starts its own Chrome). Set this to attach to a Chrome
    # window you started yourself with --remote-debugging-port=<same
    # number> instead — needed for "Sign in with Google" to work, since
    # Google blocks automation-launched browsers. See browser_manager.py
    # docstring for the one-time setup steps.
    "browser_debug_port": "",
    # Minecraft — saved connection defaults so the Admin doesn't have to
    # repeat host/port/username every time they say "minecraft khelte hain".
    # Used by minecraft_manager.set_mode() when the chat turn's tool call
    # doesn't include explicit connect details.
    "minecraft_host": "localhost",
    "minecraft_port": 25565,
    "minecraft_username": "Arika",
    "minecraft_auth": "offline",  # "offline" = TLauncher/cracked-friendly, "microsoft" for a real account
}

# A small curated list of edge-tts voices to offer in the UI.
# (Full list can be fetched live via `edge-tts --list-voices`, but a fixed
# list keeps the settings endpoint fast and avoids an extra network call.)
AVAILABLE_TTS_VOICES = [
    {"id": "en-US-AvaNeural", "label": "Ava (US, Female)"},
    {"id": "en-US-EmmaNeural", "label": "Emma (US, Female)"},
    {"id": "en-US-AriaNeural", "label": "Aria (US, Female)"},
    {"id": "en-GB-SoniaNeural", "label": "Sonia (UK, Female)"},
    {"id": "en-IN-NeerjaNeural", "label": "Neerja (India, Female)"},
    {"id": "hi-IN-SwaraNeural", "label": "Swara (Hindi, Female)"},
]

# Gemini models available to pick from Settings.
# As of mid-2026, Google's rule of thumb is: Flash / Flash-Lite models keep
# a free tier (with rate limits, e.g. ~10-15 requests/min, ~1000/day), while
# Pro models are paid-only (no free tier at all since April 2026).
# Pricing/free-tier terms change over time — always double check the
# current numbers at https://ai.google.dev/pricing before relying on this.
AVAILABLE_GEMINI_MODELS = [
    {
        "id": "gemini-3.1-flash-lite",
        "label": "Gemini 3.1 Flash-Lite",
        "tier": "free",
        "note": "Default. Fastest & cheapest, free tier with rate limits (best for a personal assistant like this).",
    },
    {
        "id": "gemini-2.5-flash-lite",
        "label": "Gemini 2.5 Flash-Lite",
        "tier": "free",
        "note": "Older/legacy Flash-Lite. Still free-tier eligible, slightly less capable than 3.1.",
    },
    {
        "id": "gemini-3-flash",
        "label": "Gemini 3 Flash",
        "tier": "free",
        "note": "Stronger than Flash-Lite, still free tier with rate limits. Good middle ground.",
    },
    {
        "id": "gemini-3.5-flash",
        "label": "Gemini 3.5 Flash",
        "tier": "paid",
        "note": "Newest Flash, beats older Pro models on reasoning/coding — but billing must be enabled (no free tier).",
    },
    {
        "id": "gemini-3.1-pro-preview",
        "label": "Gemini 3.1 Pro (Preview)",
        "tier": "paid",
        "note": "Flagship, 2M context window, most capable — paid only, noticeably more $ per message.",
    },
]


def _ensure_file():
    path = _settings_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_SETTINGS, f, indent=4)


def load_settings() -> dict:
    """Load settings, filling in any missing keys with defaults."""
    _ensure_file()
    try:
        with open(_settings_file(), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        data = {}

    merged = {**DEFAULT_SETTINGS, **data}
    if merged != data:
        save_settings(merged)
    return merged


def save_settings(new_settings: dict) -> dict:
    """Merge new_settings into existing settings and persist."""
    path = _settings_file()
    current = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                current = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            current = {}

    current = {**DEFAULT_SETTINGS, **current, **new_settings}

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(current, f, indent=4)

    return current


def get_tts_voice() -> str:
    return load_settings().get("tts_voice", DEFAULT_SETTINGS["tts_voice"])


def get_wake_word() -> str:
    return load_settings().get("wake_word", DEFAULT_SETTINGS["wake_word"])


def get_stt_lang() -> str:
    return load_settings().get("stt_lang", DEFAULT_SETTINGS["stt_lang"])


def get_gemini_model() -> str:
    return load_settings().get("gemini_model", DEFAULT_SETTINGS["gemini_model"])


def get_show_avatar() -> bool:
    return bool(load_settings().get("show_avatar", DEFAULT_SETTINGS["show_avatar"]))


def get_phone_adb_address() -> str:
    return load_settings().get("phone_adb_address", DEFAULT_SETTINGS["phone_adb_address"])
