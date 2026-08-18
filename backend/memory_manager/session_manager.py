"""
Session manager.

A "session" = one continuous chat, started fresh every time someone logs in
(or hits "New chat"). This is separate from short_term.py's rolling memory:

- short_term.py / summary_maker.py / long_term_mem.py keep the LLM's own
  working memory (last few exchanges + rolling summaries) — that's what
  actually gets fed into the Gemini prompt, and it gets reset when a new
  session starts.
- session_manager.py keeps a PERMANENT, un-summarized, un-rotated transcript
  of every session, purely so the sidebar can list past chats and the user
  can re-open and read one later. Opening an old session is read-only — it
  does not resume feeding that old context back into the live LLM prompt.

Two things live on disk here:
  backend/memory/static_short_term.json
      A flat index, across every user AND the guest bucket, of
      {session_id, owner, is_guest, title, created_at, updated_at,
      message_count}. Small and fast to scan for the sidebar.
  backend/memory/users/<login_id>/sessions/<session_id>.json
  backend/memory/guest/sessions/<session_id>.json
      The full raw transcript for one session.
"""

import json
import os
import uuid
from datetime import datetime

from backend import user_context

INDEX_FILE = user_context.STATIC_SHORT_TERM_FILE


def _load_index():
    if not os.path.exists(INDEX_FILE):
        return []
    try:
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return []


def _save_index(sessions):
    os.makedirs(os.path.dirname(INDEX_FILE), exist_ok=True)
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(sessions, f, indent=4, ensure_ascii=False)


def _sessions_dir():
    return os.path.join(user_context.get_base_dir(), "sessions")


def _transcript_path(session_id):
    return os.path.join(_sessions_dir(), f"{session_id}.json")


def delete_session(session_id):
    """Delete a session transcript and remove its index entry if it belongs to current user."""
    sessions = _load_index()
    entry = _find_entry(sessions, session_id)
    if entry is None or entry.get("owner") != _owner_key():
        return False

    # remove transcript file
    path = _transcript_path(session_id)
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass

    # remove from index
    sessions = [s for s in sessions if s.get("session_id") != session_id]
    _save_index(sessions)
    return True


def _owner_key():
    """Guests all share one bucket ('guest'); real users are scoped by
    their own login_id so nobody can read anyone else's sessions."""
    return "guest" if user_context.is_guest() else user_context.get_user_id()


def _find_entry(sessions, session_id):
    for s in sessions:
        if s["session_id"] == session_id:
            return s
    return None


def create_session(title=None):
    """Start a brand-new, empty session for the CURRENT user and record it
    in the index. Returns the new session_id.

    New format: DD-MM-YYYY-XXX (daily sequence, zero-padded to 3 digits)
    scoped per-owner so each user gets their own numbering.
    """
    owner = _owner_key()
    today = datetime.now().date()

    # compute sequence for today for this owner
    sessions = _load_index()
    seq = 1
    for s in sessions:
        try:
            if s.get("owner") == owner:
                created = datetime.fromisoformat(s.get("created_at"))
                if created.date() == today:
                    seq += 1
        except Exception:
            # ignore parse errors for older entries
            continue

    session_id = f"{today.strftime('%d-%m-%Y')}-{seq:03d}"

    os.makedirs(_sessions_dir(), exist_ok=True)

    with open(_transcript_path(session_id), "w", encoding="utf-8") as f:
        json.dump([], f, indent=4)

    now = datetime.now().isoformat()
    sessions.append({
        "session_id": session_id,
        "owner": owner,
        "is_guest": user_context.is_guest(),
        "title": title or "New chat",
        "created_at": now,
        "updated_at": now,
        "message_count": 0,
    })
    _save_index(sessions)
    return session_id


def list_sessions(limit=30):
    """Recent sessions belonging to the CURRENT user only, newest first."""
    owner = _owner_key()
    mine = [s for s in _load_index() if s.get("owner") == owner]
    mine.sort(key=lambda s: s.get("updated_at", ""), reverse=True)
    return mine[:limit]


def append_message(session_id, user_message, assistant_message):
    """Append one exchange to a session's permanent transcript and bump its
    entry in the index. No-ops quietly if the session doesn't belong to the
    current user (defensive — should never happen via the API)."""
    if not session_id:
        return

    sessions = _load_index()
    entry = _find_entry(sessions, session_id)
    if entry is None or entry.get("owner") != _owner_key():
        return

    path = _transcript_path(session_id)
    try:
        with open(path, "r", encoding="utf-8") as f:
            transcript = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        transcript = []

    transcript.append({
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "user": user_message,
        "arika": assistant_message,
    })

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(transcript, f, indent=4, ensure_ascii=False)

    entry["message_count"] = len(transcript)
    entry["updated_at"] = datetime.now().isoformat()
    if entry.get("title") in (None, "", "New chat"):
        entry["title"] = user_message[:40]
    _save_index(sessions)


def get_session_messages(session_id):
    """Read a session's transcript — ONLY if it belongs to the current
    user/guest bucket. Returns None if not found or not yours (caller
    should treat that as 404/403)."""
    entry = _find_entry(_load_index(), session_id)
    if entry is None or entry.get("owner") != _owner_key():
        return None

    try:
        with open(_transcript_path(session_id), "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []
