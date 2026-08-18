"""
One-time migration: generate embeddings for every existing long-term memory
entry (across all users + guest) that doesn't have one yet.

Run this ONCE after pulling in the semantic search upgrade:

    python -m scripts.migrate_embeddings

(run from the Arika/ project root, so the `backend` package resolves)

After this runs, search_memories_semantic()'s lazy-embed fallback will have
nothing left to do for old entries — new entries get embedded automatically
the moment they're created (see long_term_mem.py).
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import user_context
from backend.memory_manager import embeddings


def _migrate_file(path: str, label: str):
    if not os.path.exists(path):
        print(f"  [skip] {label}: no long_term_mem.json found")
        return

    with open(path, "r", encoding="utf-8") as f:
        memories = json.load(f)

    if not memories:
        print(f"  [skip] {label}: empty")
        return

    missing = [m for m in memories if "embedding" not in m or not m["embedding"]]
    if not missing:
        print(f"  [ok]   {label}: {len(memories)} entries, all already embedded")
        return

    print(f"  [work] {label}: embedding {len(missing)}/{len(memories)} entries...")
    texts = [embeddings.embedding_text_for_entry(m.get("content", ""), m.get("tags", {})) for m in missing]
    vectors = embeddings.embed_texts(texts)

    for mem, vec in zip(missing, vectors):
        mem["embedding"] = vec

    with open(path, "w", encoding="utf-8") as f:
        json.dump(memories, f, indent=4, ensure_ascii=False)

    print(f"  [done] {label}: {len(missing)} entries embedded and saved")


def main():
    print("Migrating long-term memory entries to include embeddings...")
    print("(first run also downloads the ~90MB MiniLM model — one-time cost)\n")

    # Guest memory
    guest_path = user_context.get_path("long_term", is_guest=True)
    _migrate_file(guest_path, "guest")

    # Every real user under backend/memory/users/<user_id>/
    users_dir = user_context.USERS_DIR
    if os.path.isdir(users_dir):
        for user_id in sorted(os.listdir(users_dir)):
            user_path = user_context.get_path("long_term", user_id=user_id, is_guest=False)
            _migrate_file(user_path, f"user:{user_id}")

    print("\nMigration complete.")


if __name__ == "__main__":
    main()
