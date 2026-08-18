import json
import os

from backend import user_context


def _profile_file():
    return user_context.get_path("profile")


def save_profile(data):
    path = _profile_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)

    try:
        with open(path, "r", encoding="utf-8") as f:
            profile = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        profile = {}

    profile.update(data)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=4, ensure_ascii=False)

    print("[Profile] Updated Successfully")


def load_profile():
    path = _profile_file()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def delete_profile():
    """Delete the current user's profile file."""
    path = _profile_file()
    try:
        if os.path.exists(path):
            os.remove(path)
            return True
    except Exception:
        pass
    return False
