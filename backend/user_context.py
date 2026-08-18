"""
Per-request user context.

Every memory_manager module (short_term, summary_maker, long_term_mem,
long_term_mem_manager, profile, settings_manager) used to hardcode a single
shared file under backend/memory/. Now that logins + guest mode exist, each
of those needs to point at a different folder depending on WHO is asking.

Rather than threading a `user_id` argument through every function and every
call site (app.py -> prompt_builder.py -> short_term.py -> summary_maker.py
-> ...), we stash "who is asking right now" in a contextvar. app.py sets it
once per Flask request (from the session cookie); cli.py sets it once after
the login prompt. Everything else just calls get_path(...) and doesn't need
to know or care whether it's being called from the web app or the CLI.
"""

import contextvars
import os

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))          # backend/
MEMORY_ROOT = os.path.join(BACKEND_DIR, "memory")
USERS_DIR = os.path.join(MEMORY_ROOT, "users")
GUEST_DIR = os.path.join(MEMORY_ROOT, "guest")

# Global index of every session (real users + guest) — used to build the
# "recent chats" sidebar without opening every user's folder.
STATIC_SHORT_TERM_FILE = os.path.join(MEMORY_ROOT, "static_short_term.json")

_user_id_var = contextvars.ContextVar("arika_user_id", default=None)
_is_guest_var = contextvars.ContextVar("arika_is_guest", default=False)

# Guest data intentionally uses different filenames (as requested) so it's
# obvious at a glance, on disk, which files are throwaway guest data.
FILE_NAMES = {
    "short_term": {"user": "short_term.json", "guest": "guest_mem.json"},
    "summary":    {"user": "summary.json", "guest": "guest_summary.json"},
    "long_term":  {"user": "long_term_mem.json", "guest": "guest_long_term_mem.json"},
    "profile":    {"user": "profile.json", "guest": "guest_profile.json"},
    "settings":   {"user": "settings.json", "guest": "guest_settings.json"},
    "tasks":      {"user": "tasks.json", "guest": "guest_tasks.json"},
    "plan":       {"user": "plan.json", "guest": "guest_plan.json"},
    # Minecraft has its own memory domain (see backend/memory_manager/
    # minecraft_memory.py) — separate rolling short-term file + separate
    # persistent world-knowledge file, kept apart from normal chat memory
    # so it never bloats prompt_builder's default context, but still
    # synced/retrievable through the same per-user folder pattern.
    "minecraft_short_term": {"user": "minecraft_short_term.json", "guest": "guest_minecraft_short_term.json"},
    "minecraft_world":       {"user": "minecraft_world.json", "guest": "guest_minecraft_world.json"},
}


def set_current_user(user_id: str, is_guest: bool = False):
    """Call once per request/session. Everything after this call, on this
    thread/async-task, resolves memory paths for this user."""
    _user_id_var.set(user_id)
    _is_guest_var.set(bool(is_guest))
    ensure_user_dir(user_id, is_guest)


def clear_current_user():
    _user_id_var.set(None)
    _is_guest_var.set(False)


def get_user_id():
    return _user_id_var.get()


def is_guest():
    return _is_guest_var.get()


def get_base_dir():
    """Folder holding the CURRENT user's (or the shared guest bucket's)
    memory files."""
    if is_guest():
        return GUEST_DIR
    user_id = get_user_id() or "default"
    return os.path.join(USERS_DIR, user_id)


def ensure_user_dir(user_id: str, is_guest: bool = False):
    d = GUEST_DIR if is_guest else os.path.join(USERS_DIR, user_id or "default")
    os.makedirs(d, exist_ok=True)
    return d


def get_path(kind: str, user_id: str = None, is_guest: bool = None) -> str:
    """Resolve the on-disk path for a memory 'kind'.

    By default, this uses the CURRENT user context. If `user_id` is
    provided, it resolves the path for that explicit user (or guest).
    """
    if is_guest is None:
        is_guest = _is_guest_var.get()

    if user_id is None:
        base_dir = get_base_dir()
    else:
        base_dir = GUEST_DIR if is_guest else os.path.join(USERS_DIR, user_id or "default")

    os.makedirs(base_dir, exist_ok=True)
    names = FILE_NAMES[kind]
    fname = names["guest"] if is_guest else names["user"]
    return os.path.join(base_dir, fname)
