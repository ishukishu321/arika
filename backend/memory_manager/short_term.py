import json
import os
import sys
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import user_context

RAW_CHAT_LIMIT = 7
SUMMARY_BATCH_SIZE = 5
SUMMARY_TRIGGER = RAW_CHAT_LIMIT + SUMMARY_BATCH_SIZE


def _memory_file():
    """Resolves to the CURRENT user's (or guest's) rolling short-term file."""
    return user_context.get_path("short_term")


def initialize():
    """Creates the short-term memory file when it does not exist."""
    path = _memory_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)

    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump([], f, indent=4)


def _normalize_chats(data):
    """Read the current and older short-term memory formats safely."""
    chats = []

    for item in data:
        if {"id", "timestamp", "user", "arika"}.issubset(item):
            chats.append(item)
        elif "user" in item and "assistant" in item:
            chats.append({
                "id": item.get("id", len(chats) + 1),
                "timestamp": item.get("time", ""),
                "user": item["user"],
                "arika": item["assistant"]
            })

    return chats


def load_messages():
    """Load complete User-Arika exchanges in chronological order."""
    initialize()

    with open(_memory_file(), "r", encoding="utf-8") as f:
        return _normalize_chats(json.load(f))


def _save_messages(chats):
    with open(_memory_file(), "w", encoding="utf-8") as f:
        json.dump(chats, f, indent=4, ensure_ascii=False)


def _create_summaries_if_needed(chats):
    """Summarize the oldest five exchanges while preserving raw data on failure."""
    while len(chats) >= SUMMARY_TRIGGER:
        source_chats = chats[:SUMMARY_BATCH_SIZE]

        try:
            from backend.memory_manager.summary_maker import create_summary, save_summary
            from backend.memory_manager.long_term_mem import process_mega_summary

            # 1. Short term summary banao aur save karo
            summary = create_summary(source_chats)
            save_summary(summary, source_chats)

            # 2. Mega summary ka process trigger karo (Automatically check karega 8 hui ya nahi)
            process_mega_summary()

        except Exception as error:
            print(f"[Memory warning] Summary was not created: {error}")
            break

        chats = chats[SUMMARY_BATCH_SIZE:]
        _save_messages(chats)

    return chats


def save_chat(user_message, assistant_message):
    """Save one User-Arika exchange and summarize older exchanges if needed."""
    chats = load_messages()
    next_id = max((chat["id"] for chat in chats), default=0) + 1

    chats.append({
        "id": next_id,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "user": user_message,
        "arika": assistant_message
    })

    _save_messages(chats)
    _create_summaries_if_needed(chats)


def get_recent_messages(limit=RAW_CHAT_LIMIT):
    """Return the latest complete exchanges for the LLM prompt."""
    return load_messages()[-limit:]


def clear_memory():
    """Clears all short-term memory (called when a new session starts, so
    the LLM's rolling working memory doesn't bleed across sessions)."""
    _save_messages([])
