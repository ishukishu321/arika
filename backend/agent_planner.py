"""
Agent Planner
=============
This is the "agentic task" layer on top of task_manager.py.

task_manager.py tracks ONE action at a time (open_app, browser_click, ...).
That's fine for single commands, but it can't answer "what's your plan for
finishing this whole task" or show the Admin a to-do list.

This file adds that layer: when the Admin gives Arika something bigger than
one action ("login to my college portal and download the fee receipt",
"research 3 AI/ML courses in Japan and summarize them"), Gemini calls the
create_plan tool ONCE with a goal + an ordered list of steps (each step is
in PLAIN LANGUAGE — what to do and how — same as Ishu would write in a
notebook). We store that as a plan, then execute_plan_step() drives Gemini
through the steps one at a time, marking each pending -> in_progress ->
done/failed/needs_input, so at any point (even a fresh stateless API call)
we can show the Admin exactly what Arika is doing and why.

One active plan per user at a time (same single-file-per-session pattern as
tasks.json / profile.json in user_context.py).
"""

import json
import os
import time
import uuid

from backend import user_context


def _plan_file():
    return user_context.get_path("plan")


def _load():
    path = _plan_file()
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _save(plan):
    path = _plan_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2, ensure_ascii=False)


def create_plan(goal: str, steps: list) -> dict:
    """steps: list of plain-language step descriptions written by Gemini,
    e.g. ["Open the college portal login page",
          "Type roll number and password into the login form",
          "Click the 'Fee Receipt' link",
          "Download/screenshot the receipt and confirm to the Admin"].
    Replaces any previous plan for this user — only one active plan at a
    time keeps things easy to reason about and show in the UI."""
    plan = {
        "id": uuid.uuid4().hex[:8],
        "goal": goal,
        "status": "in_progress",  # in_progress -> done / failed / needs_input / cancelled
        "created_at": time.time(),
        "updated_at": time.time(),
        "current_step": 0,
        "steps": [
            {
                "index": i,
                "text": text,
                "status": "pending",  # pending -> in_progress -> done / failed / skipped
                "result": None,
                "error": None,
            }
            for i, text in enumerate(steps)
        ],
    }
    _save(plan)
    return plan


def get_plan() -> dict:
    """Returns the current plan (or None if there isn't one). Safe to call
    every turn — this is what powers the Todo List widget in the UI."""
    return _load()


def _update_plan(**kwargs):
    plan = _load()
    if not plan:
        return None
    plan.update(kwargs)
    plan["updated_at"] = time.time()
    _save(plan)
    return plan


def mark_step(index: int, status: str, result=None, error=None):
    plan = _load()
    if not plan:
        return None
    for step in plan["steps"]:
        if step["index"] == index:
            step["status"] = status
            if result is not None:
                step["result"] = result
            if error is not None:
                step["error"] = error
            break
    plan["updated_at"] = time.time()
    _save(plan)
    return plan


def advance_cursor() -> int:
    """Move current_step to the next pending step. Returns the new index,
    or -1 if every step is already done/skipped (plan complete)."""
    plan = _load()
    if not plan:
        return -1
    for step in plan["steps"]:
        if step["status"] in ("pending", "in_progress", "failed"):
            plan["current_step"] = step["index"]
            _save(plan)
            return step["index"]
    plan["current_step"] = -1
    plan["status"] = "done"
    _save(plan)
    return -1


def set_plan_status(status: str):
    return _update_plan(status=status)


def cancel_plan():
    return _update_plan(status="cancelled")


def clear_plan():
    path = _plan_file()
    if os.path.exists(path):
        os.remove(path)


def summary() -> dict:
    """Compact snapshot for the AI/UI: what's the goal, kaunsa step chal
    raha hai, kitna baaki hai."""
    plan = _load()
    if not plan:
        return {"has_plan": False}

    done = [s for s in plan["steps"] if s["status"] == "done"]
    failed = [s for s in plan["steps"] if s["status"] == "failed"]
    pending = [s for s in plan["steps"] if s["status"] in ("pending", "in_progress")]

    return {
        "has_plan": True,
        "id": plan["id"],
        "goal": plan["goal"],
        "status": plan["status"],
        "current_step": plan["current_step"],
        "total_steps": len(plan["steps"]),
        "done_count": len(done),
        "failed_count": len(failed),
        "pending_count": len(pending),
        "steps": plan["steps"],
    }
