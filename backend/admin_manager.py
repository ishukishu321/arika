"""
Admin identity
==============
Automation (PC control AND phone control) is restricted to ONE specific
account — the Admin — even though this app can have several registered
logins (friends/family could each have their own account for chatting).

The Admin's login_id lives in a single plain-text file:
    backend/memory/admin.txt

Whoever's name is written there is the ONLY account allowed to trigger
automation commands. Every other registered account, and guest sessions,
can still chat with Arika normally — automation commands just get blocked
for them (see command_router.py).

The first person to ever register on a fresh install is automatically
made Admin (see auth_manager.register_user). After that, admin.txt is the
single source of truth. To hand admin to someone else later, just edit
that file (or call set_admin() from a Python shell).
"""

import os
from typing import Optional

from backend import user_context

ADMIN_FILE = os.path.join(user_context.MEMORY_ROOT, "admin.txt")


def get_admin() -> Optional[str]:
    if not os.path.exists(ADMIN_FILE):
        return None
    try:
        with open(ADMIN_FILE, "r", encoding="utf-8") as f:
            name = f.read().strip()
        return name or None
    except OSError:
        return None


def bootstrap_admin_if_needed():
    """Call once at app startup. Handles the 'I already had an account
    before this admin.txt system existed' case: if no admin is set yet but
    exactly one registered user already exists, that person becomes Admin
    automatically — no manual setup needed for existing installs."""
    if admin_is_set():
        return
    from backend import auth_manager  # local import: avoids circular import
    users = auth_manager._load()
    if len(users) == 1:
        only_user = next(iter(users))
        set_admin(only_user)
        print(f"[Admin] Bootstrapped existing account '{only_user}' as Admin.")


def set_admin(login_id: str):
    os.makedirs(os.path.dirname(ADMIN_FILE), exist_ok=True)
    with open(ADMIN_FILE, "w", encoding="utf-8") as f:
        f.write((login_id or "").strip().lower())


def admin_is_set() -> bool:
    return get_admin() is not None


def is_admin() -> bool:
    """Is the CURRENTLY logged-in user (from user_context's per-request
    contextvar) the Admin? Guests are never Admin."""
    if user_context.is_guest():
        return False
    current = (user_context.get_user_id() or "").strip().lower()
    admin_name = get_admin()
    if not admin_name or not current:
        return False
    return current == admin_name
