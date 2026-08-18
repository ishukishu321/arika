"""
Account store for named (non-guest) users.

Stores login_id -> password_hash in backend/memory/users.json. Guest mode
does not go through here at all — it never gets an account, never touches
this file, and can't be confused with a real login_id because "guest" is a
reserved name (see register_user).
"""

import json
import os
from datetime import datetime

from werkzeug.security import check_password_hash, generate_password_hash

from backend import user_context
from backend import admin_manager

USERS_FILE = os.path.join(user_context.MEMORY_ROOT, "users.json")

RESERVED_LOGIN_IDS = {"guest"}


def _load():
    if not os.path.exists(USERS_FILE):
        return {}
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {}


def _save(users: dict):
    os.makedirs(os.path.dirname(USERS_FILE), exist_ok=True)
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=4, ensure_ascii=False)


def _normalize(login_id: str) -> str:
    return (login_id or "").strip().lower()


def user_exists(login_id: str) -> bool:
    return _normalize(login_id) in _load()


def register_user(login_id: str, password: str):
    """Create a new account. Raises ValueError with a user-facing message
    on any problem."""
    login_id = _normalize(login_id)

    if not login_id or not password:
        raise ValueError("Login ID and password are both required.")
    if login_id in RESERVED_LOGIN_IDS:
        raise ValueError("'guest' is reserved — use the Guest button instead, or pick another login ID.")
    if len(login_id) < 3:
        raise ValueError("Login ID must be at least 3 characters.")
    if len(password) < 4:
        raise ValueError("Password must be at least 4 characters.")

    users = _load()
    if login_id in users:
        raise ValueError("That login ID is already taken.")

    users[login_id] = {
        "password_hash": generate_password_hash(password),
        "created_at": datetime.now().isoformat(),
    }
    _save(users)
    user_context.ensure_user_dir(login_id, is_guest=False)

    # First account ever created on this install becomes Admin automatically.
    # Everyone registered after this is a normal (non-automation) account.
    if not admin_manager.admin_is_set():
        admin_manager.set_admin(login_id)


def verify_user(login_id: str, password: str) -> bool:
    login_id = _normalize(login_id)
    entry = _load().get(login_id)
    if not entry:
        return False
    return check_password_hash(entry["password_hash"], password)
