"""
Calendar & Reminders
=====================
Upgrade over automation.py's old `set_reminder` (which was purely in-memory
via threading.Timer and forgot everything on restart). This version:

- Persists every reminder/event to disk (backend/memory/calendar.json) so
  they survive an app restart.
- Supports both relative ("in 20 minutes") and absolute ("2026-08-01 09:00")
  firing times.
- Runs ONE background thread (started once from main.py) that wakes up
  every 20 seconds, checks what's due, and fires it (console print +
  Windows toast, same fallback pattern as the old set_reminder).
- Calendar "events" are just reminders with notify=False by default (they
  show up in list_events but don't ping you, unless you ask to be notified).

This is intentionally a single shared file, not per-user, because
automation (and therefore this) is Admin-only anyway — see
admin_manager.py / command_router.py.
"""

import json
import os
import threading
import time
import uuid
from datetime import datetime, timedelta

from backend import user_context

CALENDAR_FILE = os.path.join(user_context.MEMORY_ROOT, "calendar.json")

_lock = threading.Lock()
_checker_started = False

# Accepted absolute datetime formats, tried in order.
_DATETIME_FORMATS = [
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%d-%m-%Y %H:%M",
    "%Y-%m-%dT%H:%M",
]


def _load():
    if not os.path.exists(CALENDAR_FILE):
        return []
    try:
        with open(CALENDAR_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save(items):
    os.makedirs(os.path.dirname(CALENDAR_FILE), exist_ok=True)
    with open(CALENDAR_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)


def _parse_when(when: str) -> float:
    """Accepts an absolute datetime string and returns a unix timestamp.
    Raises ValueError with a clear message if it can't be parsed."""
    when = (when or "").strip()
    for fmt in _DATETIME_FORMATS:
        try:
            return datetime.strptime(when, fmt).timestamp()
        except ValueError:
            continue
    raise ValueError(
        f"Couldn't understand the date/time '{when}'. Use a format like "
        f"'2026-08-01 09:00'."
    )


def add_reminder(text: str, seconds_from_now: int = None, when: str = None,
                  notify: bool = True, kind: str = "reminder") -> dict:
    """Create a reminder or calendar event. Give EITHER seconds_from_now
    (relative, e.g. 1200) OR when (absolute, e.g. '2026-08-01 09:00') —
    not both. kind is just a label ('reminder' vs 'event') for display."""
    text = (text or "").strip()
    if not text:
        raise ValueError("No text given for the reminder/event.")

    if when:
        fire_at = _parse_when(when)
    elif seconds_from_now is not None:
        try:
            seconds_from_now = int(seconds_from_now)
        except (TypeError, ValueError):
            raise ValueError("seconds_from_now must be a number.")
        if seconds_from_now <= 0:
            raise ValueError("seconds_from_now must be positive.")
        fire_at = time.time() + seconds_from_now
    else:
        raise ValueError("Give either 'when' (a date/time) or 'seconds_from_now'.")

    item = {
        "id": uuid.uuid4().hex[:8],
        "text": text,
        "fire_at": fire_at,
        "created_at": time.time(),
        "notify": bool(notify),
        "kind": kind,
        "fired": False,
    }

    with _lock:
        items = _load()
        items.append(item)
        _save(items)

    when_readable = datetime.fromtimestamp(fire_at).strftime("%d-%m-%Y %H:%M")
    return {"id": item["id"], "text": text, "fire_at_readable": when_readable}


def add_event(title: str, when: str, notify: bool = False) -> dict:
    """Convenience wrapper: a calendar event is just a reminder that
    defaults to NOT pinging you (notify=False) unless asked."""
    return add_reminder(title, when=when, notify=notify, kind="event")


def list_upcoming(limit: int = 20) -> list:
    items = _load()
    upcoming = [i for i in items if not i["fired"]]
    upcoming.sort(key=lambda i: i["fire_at"])
    out = []
    for i in upcoming[:limit]:
        out.append({
            "id": i["id"],
            "text": i["text"],
            "kind": i.get("kind", "reminder"),
            "fire_at_readable": datetime.fromtimestamp(i["fire_at"]).strftime("%d-%m-%Y %H:%M"),
        })
    return out


def delete_reminder(reminder_id: str) -> str:
    reminder_id = (reminder_id or "").strip()
    if not reminder_id:
        raise ValueError("No reminder/event id given.")
    with _lock:
        items = _load()
        remaining = [i for i in items if i["id"] != reminder_id]
        if len(remaining) == len(items):
            raise ValueError(f"No reminder/event found with id '{reminder_id}'.")
        _save(remaining)
    return f"Deleted reminder/event {reminder_id}"


def _fire(item: dict):
    label = "Event" if item.get("kind") == "event" else "Reminder"
    print(f"[{label}] {item['text']}")
    try:
        from win10toast import ToastNotifier
        ToastNotifier().show_toast(f"Arika {label.lower()}", item["text"], duration=10, threaded=True)
    except ImportError:
        pass  # console print above is the guaranteed fallback


def _checker_loop():
    while True:
        try:
            with _lock:
                items = _load()
                now = time.time()
                changed = False
                for i in items:
                    if not i["fired"] and i["fire_at"] <= now:
                        if i.get("notify", True):
                            _fire(i)
                        i["fired"] = True
                        changed = True
                if changed:
                    _save(items)
        except Exception as e:
            print(f"[Calendar] Checker loop error: {e}")
        time.sleep(20)


def start_background_checker():
    """Call ONCE at app startup (see main.py). Safe to call more than
    once — only the first call actually starts the thread."""
    global _checker_started
    if _checker_started:
        return
    _checker_started = True
    t = threading.Thread(target=_checker_loop, daemon=True)
    t.start()
    print("[Calendar] Background reminder/event checker started.")
