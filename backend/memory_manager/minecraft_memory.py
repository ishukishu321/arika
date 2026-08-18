"""
Minecraft short-term memory (separate domain).
================================================
Why separate from backend/memory_manager/short_term.py?

Minecraft mode is INACTIVE by default (see backend/minecraft_manager.py).
Normal chat turns must never pay the token cost of "current coords, nearby
mobs, last 25 game events" sitting in their prompt. So Minecraft gets its
own rolling short-term log, its own file on disk, and its own
summarization cutoff — but it still lives under the same per-user folder
(backend/memory/users/<id>/) via user_context.get_path(), so it travels
with the rest of that user's memory and survives restarts.

Retrieval works even when Minecraft mode is OFF: prompt_builder / gemini.py
can call recall(query) to answer "mera base kahan tha?" without loading the
whole gameplay context, per the spec.

Record shape:
    {
      "id": int,
      "timestamp": "...",
      "type": "event" | "action" | "note",
      "text": "human-readable line, e.g. 'PLAYER_DAMAGED near (120,64,-42)'",
    }

RAW_LIMIT (~25) detailed records are kept verbatim. Once exceeded, the
oldest batch is folded into a running summary that preserves: current
world/location, coordinates, objectives, discovered locations, important
entities, inventory/resources, recent actions/decisions, important events.
"""

import json
import os
from datetime import datetime

from backend import user_context

RAW_LIMIT = 25
SUMMARY_BATCH_SIZE = 10  # fold the oldest 10 into the summary once we're over RAW_LIMIT


def _file():
    return user_context.get_path("minecraft_short_term")


def _default():
    return {"records": [], "summary": "", "world_state": {}}


def _load():
    path = _file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(_default(), f, indent=4)
        return _default()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        data = _default()
    for key, val in _default().items():
        data.setdefault(key, val)
    return data


def _save(data):
    path = _file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def _summarize_batch(records, previous_summary):
    """Fold a batch of old records into the running summary. Kept as a
    plain-text merge (no LLM call) so this never blocks the game loop —
    it just appends compact facts. If you want a nicer LLM-written
    summary, call backend.gemini.ask_gemini(..., enable_tools=False) here
    with a summarization prompt instead; left simple on purpose so
    Minecraft memory never depends on an extra API round trip during
    active gameplay."""
    lines = [previous_summary] if previous_summary else []
    lines.append(f"--- Summarized {len(records)} older Minecraft records ---")
    for r in records:
        lines.append(f"[{r['timestamp']}] {r['type']}: {r['text']}")
    return "\n".join(l for l in lines if l).strip()


def add_record(text: str, record_type: str = "event"):
    """Append one Minecraft short-term record (event/action/note). Folds
    the oldest batch into the summary once RAW_LIMIT is exceeded."""
    data = _load()
    next_id = max((r["id"] for r in data["records"]), default=0) + 1
    data["records"].append({
        "id": next_id,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "type": record_type,
        "text": text,
    })

    if len(data["records"]) > RAW_LIMIT:
        overflow = len(data["records"]) - RAW_LIMIT
        batch = data["records"][:max(overflow, SUMMARY_BATCH_SIZE)]
        data["records"] = data["records"][len(batch):]
        data["summary"] = _summarize_batch(batch, data["summary"])

    _save(data)


def update_world_state(patch: dict):
    """Merge a few durable facts into world_state (current world/dimension,
    last known base coords, current objective, discovered locations,
    important entities). This is NOT the noisy per-tick status dump — it's
    the small set of things worth remembering long after mode deactivates."""
    data = _load()
    data["world_state"].update({k: v for k, v in (patch or {}).items() if v is not None})
    _save(data)


def get_world_state() -> dict:
    return _load()["world_state"]


def get_detailed_records(limit: int = RAW_LIMIT) -> list:
    return _load()["records"][-limit:]


def get_summary() -> str:
    return _load()["summary"]


def get_context_block() -> str:
    """Compact text block for injection into the prompt ONLY while
    Minecraft mode is active (see prompt_builder.build_prompt)."""
    data = _load()
    parts = []
    if data["world_state"]:
        parts.append("Known world state: " + json.dumps(data["world_state"], ensure_ascii=False))
    if data["summary"]:
        parts.append("Earlier session summary:\n" + data["summary"])
    if data["records"]:
        recent = "\n".join(f"[{r['timestamp']}] {r['type']}: {r['text']}" for r in data["records"])
        parts.append("Recent Minecraft events (latest ~25):\n" + recent)
    return "\n\n".join(parts)


def recall(query: str = "") -> str:
    """Retrieval path used when Minecraft mode is OFF (e.g. Admin asks
    'mera base kahan tha?' outside gameplay). Simple keyword-relevance
    filter over world_state + summary + records so we don't have to spin
    up embeddings for a small, structured memory domain like this one.
    Returns "" if nothing looks relevant and there's nothing stored."""
    data = _load()
    if not data["world_state"] and not data["summary"] and not data["records"]:
        return ""

    q = (query or "").lower().strip()
    parts = []
    if data["world_state"]:
        parts.append("Known Minecraft world state: " + json.dumps(data["world_state"], ensure_ascii=False))
    if data["summary"]:
        parts.append("Minecraft session summary:\n" + data["summary"])

    if q:
        matches = [
            f"[{r['timestamp']}] {r['type']}: {r['text']}"
            for r in data["records"]
            if any(word in r["text"].lower() for word in q.split())
        ]
        if matches:
            parts.append("Matching Minecraft events:\n" + "\n".join(matches[-10:]))
    else:
        recent = data["records"][-10:]
        if recent:
            parts.append("Recent Minecraft events:\n" + "\n".join(
                f"[{r['timestamp']}] {r['type']}: {r['text']}" for r in recent
            ))

    return "\n\n".join(parts)


def clear():
    _save(_default())
