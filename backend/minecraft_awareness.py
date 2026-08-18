"""
Proactive Minecraft environment-awareness loop.
=================================================
While Minecraft mode is active, minecraft_manager's poll loop (every ~15s,
see POLL_INTERVAL_SEC) calls into this module with the latest compact status
+ any new bot events (see minecraft_manager.register_awareness_callback).

This module decides whether anything is actually worth interrupting the
Admin about. If so, it asks Gemini for a short in-character comment,
generates TTS audio for it, logs it to chat history, and stashes it so the
frontend can pick it up on its next poll (see /api/minecraft/awareness in
app.py) — all WITHOUT the Admin typing anything.

Kept deliberately quiet by default: a "sab normal hai" every 15 seconds
would be worse than saying nothing at all. Only fires on events the bot
itself already flags as notable — never on routine NEW_AREA/PLAYER_DAMAGED
spam alone — and rate-limited so a burst of events can't trigger back-to-
back Gemini calls.
"""

import threading
import time

NOTABLE_EVENT_TYPES = {
    "LOW_HEALTH", "TARGET_FOUND", "DEATH", "KICKED", "ERROR",
    "AUTO_DEFEND", "TARGET_KILLED", "PLAYER_TOO_FAR",
}

MIN_SECONDS_BETWEEN_COMMENTS = 20  # floor, even if events keep piling up

_lock = threading.Lock()
_pending = None  # {"text": str, "audio_urls": [str, ...]}
_last_fire_ts = 0.0


def _should_fire(events):
    return any(e.get("type") in NOTABLE_EVENT_TYPES for e in events)


def check_and_maybe_comment(
    status,
    events,
    ask_gemini_fn,
    tts_generate_fn,
    save_chat_fn,
    audio_url_builder,
    audio_dir,
):
    """Called from minecraft_manager's poll thread. All params are passed in
    (rather than imported) to avoid this module needing to import gemini.py
    / app.py directly — app.py wires the real functions in at startup.
    """
    global _last_fire_ts, _pending

    if not events or not _should_fire(events):
        return

    now = time.time()
    if now - _last_fire_ts < MIN_SECONDS_BETWEEN_COMMENTS:
        return
    _last_fire_ts = now

    event_summary = "; ".join(
        f"{e.get('type')}: {e.get('detail')}" for e in events if e.get("type") in NOTABLE_EVENT_TYPES
    )
    prompt_message = (
        "[System Note: Minecraft LIVE EVENT — the Admin hasn't typed anything, "
        f"you noticed this yourself from the game: {event_summary}\n\n"
        f"Current compact status: {status}\n\n"
        "If this is genuinely worth a short unprompted heads-up, reply with "
        "ONE short in-character line about it. If it's minor and not worth "
        "interrupting, reply with EXACTLY the single word: SKIP]"
    )

    try:
        reply = ask_gemini_fn(prompt_message, enable_tools=False)
    except Exception as e:
        print(f"[Minecraft Awareness] Gemini call failed: {e}")
        return

    text = (reply or "").strip()
    if not text or text.upper().strip(" .!") == "SKIP":
        return

    audio_urls = []
    try:
        filenames = tts_generate_fn(text, audio_dir)
        audio_urls = [audio_url_builder(fname) for fname in filenames]
    except Exception as e:
        print(f"[Minecraft Awareness] TTS generation failed: {e}")

    try:
        save_chat_fn("[Minecraft Live]", text)
    except Exception as e:
        print(f"[Minecraft Awareness] save_chat failed: {e}")

    with _lock:
        _pending = {"text": text, "audio_urls": audio_urls}


def pop_pending():
    """Called by GET /api/minecraft/awareness — returns and clears whatever
    proactive comment is waiting, or None if there's nothing new."""
    global _pending
    with _lock:
        msg = _pending
        _pending = None
        return msg
