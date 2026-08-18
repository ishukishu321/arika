"""
Task Manager
============
The Gemini API is stateless — every request starts fresh with no memory of
what it did last time. So if Arika kicks off automation tasks (open app,
create folder, screenshot, ...), something OUTSIDE the API call has to keep
score. That's this file.

Every task gets written to disk (tasks.json, one per user/guest — same
pattern as short_term.json, profile.json etc. in user_context.py) with a
status: pending -> in_progress -> done / failed.

command_router.py calls create_task() before running an action and
update_task() right after, so at any point later (even in a brand-new
stateless API call) we can answer "kitna kaam bacha hai" by just reading
this file.
"""

import json
import os
import time
import uuid

from backend import user_context


def _tasks_file():
    return user_context.get_path("tasks")


def _load():
    path = _tasks_file()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save(tasks):
    path = _tasks_file()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(tasks, f, indent=2, ensure_ascii=False)


def create_task(action: str, target=None) -> str:
    """Call this BEFORE running an automation action. Returns a task_id."""
    tasks = _load()
    task = {
        "id": uuid.uuid4().hex[:8],
        "action": action,
        "target": target,
        "status": "pending",
        "result": None,
        "error": None,
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    tasks.append(task)
    _save(tasks)
    return task["id"]


def mark_in_progress(task_id: str):
    _update(task_id, status="in_progress")


def mark_done(task_id: str, result=None):
    _update(task_id, status="done", result=result)


def mark_failed(task_id: str, error=None):
    _update(task_id, status="failed", error=error)


def _update(task_id: str, status: str, result=None, error=None):
    tasks = _load()
    for t in tasks:
        if t["id"] == task_id:
            t["status"] = status
            t["updated_at"] = time.time()
            if result is not None:
                t["result"] = result
            if error is not None:
                t["error"] = error
            break
    _save(tasks)


def list_tasks(status: str = None, limit: int = 50):
    tasks = _load()
    if status:
        tasks = [t for t in tasks if t["status"] == status]
    return tasks[-limit:]


def summary() -> dict:
    """Compact snapshot for the AI to read back to the user: kitna hua,
    kitna bacha, kya fail hua."""
    tasks = _load()
    pending = [t for t in tasks if t["status"] in ("pending", "in_progress")]
    done = [t for t in tasks if t["status"] == "done"]
    failed = [t for t in tasks if t["status"] == "failed"]

    return {
        "total_tasks": len(tasks),
        "pending_count": len(pending),
        "done_count": len(done),
        "failed_count": len(failed),
        "pending": [
            {"id": t["id"], "action": t["action"], "target": t["target"]}
            for t in pending
        ],
        "recent_done": [
            {"id": t["id"], "action": t["action"], "target": t["target"], "result": t["result"]}
            for t in done[-5:]
        ],
        "recent_failed": [
            {"id": t["id"], "action": t["action"], "target": t["target"], "error": t["error"]}
            for t in failed[-5:]
        ],
    }


def clear_tasks():
    _save([])
