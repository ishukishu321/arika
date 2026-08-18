"""
Long-term memory manager.
Saves mega summaries to long_term_mem.json and removes old summaries from summary.json
"""

import json
import os
import sys
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.memory_manager import summary_maker
from backend.memory_manager import embeddings
from backend import user_context

create_mega_summary = summary_maker.create_mega_summary
load_summaries = summary_maker.load_summaries


def _long_term_file():
    return user_context.get_path("long_term")


def _summary_file():
    return user_context.get_path("summary")


def initialize_long_term():
    """Creates the long-term memory file if it doesn't exist."""
    path = _long_term_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)

    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump([], f, indent=4)


def load_long_term():
    """Load all long-term memory entries."""
    initialize_long_term()

    with open(_long_term_file(), "r", encoding="utf-8") as f:
        return json.load(f)


def save_long_term(entries):
    """Save long-term memory entries."""
    with open(_long_term_file(), "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=4, ensure_ascii=False)


def remove_old_summaries(summary_ids):
    """Remove specific summaries from summary.json by their IDs."""
    summaries = load_summaries()

    # Filter out the old summaries
    remaining_summaries = [s for s in summaries if s["id"] not in summary_ids]

    with open(_summary_file(), "w", encoding="utf-8") as f:
        json.dump(remaining_summaries, f, indent=4, ensure_ascii=False)


def process_mega_summary():
    """
    Main function:
    1. Create mega summary (if 5+ summaries exist)
    2. Save to long_term_mem.json with sequential numeric id and timestamp
    3. Remove old 5 summaries from summary.json
    """
    mega_summary = create_mega_summary()

    if mega_summary is None:
        return False

    # Load current long-term memory
    long_term_entries = load_long_term()

    # Safely generate the next numeric ID
    if not long_term_entries:
        next_id = 1
    else:
        # Purane string IDs ko ignore karke highest numeric ID nikalna
        numeric_ids = [int(e["id"]) for e in long_term_entries if str(e.get("id", "")).isdigit()]
        next_id = max(numeric_ids, default=0) + 1

    # Create new entry with unique ID and timestamp
    new_entry = {
        "id": next_id,
        "timestamp": datetime.now().isoformat(),
        "content": mega_summary["content"],
        "tags": mega_summary["tags"],
        "source_summary_ids": mega_summary["source_summary_ids"]
    }

    # Generate + store the embedding right away so search time never has to
    # wait on it. If the model/embedding step fails for any reason (e.g. no
    # internet on first-ever download of the model), don't block memory
    # creation — the entry is still saved, and search_memories_semantic()
    # will lazily embed it on first access instead.
    try:
        embed_text = embeddings.embedding_text_for_entry(new_entry["content"], new_entry["tags"])
        new_entry["embedding"] = embeddings.embed_text(embed_text)
    except Exception as e:
        print(f"[Long Term Mem] Warning: embedding generation failed ({e}); will lazy-embed on search.")

    # Add to long-term memory
    long_term_entries.append(new_entry)
    save_long_term(long_term_entries)

    # Remove old summaries from summary.json
    remove_old_summaries(mega_summary["source_summary_ids"])

    print(f"✅ Mega summary created and archived!")
    print(f"   ID: {new_entry['id']}")
    print(f"   Timestamp: {new_entry['timestamp']}")
    print(f"   Tags: {len(new_entry['tags'])} tags created")
    print(f"   Removed 5 old summaries from summary.json")

    return True


if __name__ == "__main__":
    success = process_mega_summary()
    exit(0 if success else 1)
