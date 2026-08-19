"""
One-time migration: generate embeddings for every existing long-term memory
entry (across all users + guest) that doesn't have one yet.

Run this ONCE after pulling in the semantic search upgrade:

    python -m scripts.migrate_embeddings

Run with --force whenever MODEL_NAME in embeddings.py changes (e.g. after
switching from an English-only model to a multilingual one) — this
regenerates every entry's embedding instead of only filling in missing ones,
since old vectors are not comparable in the new model's embedding space:

    python -m scripts.migrate_embeddings --force

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


def _migrate_file(path: str, label: str, force: bool = False):
    if not os.path.exists(path):
        print(f"  [skip] {label}: no long_term_mem.json found")
        return

    with open(path, "r", encoding="utf-8") as f:
        memories = json.load(f)

    if not memories:
        print(f"  [skip] {label}: empty")
        return

    if force:
        # Regenerate EVERY entry's embedding, even ones that already have
        # one. Needed after switching MODEL_NAME (e.g. English-only ->
        # multilingual) — old vectors live in a different embedding space
        # and are not comparable to new query vectors. Without --force they
        # just silently stop matching well instead of erroring, which is
        # much harder to notice.
        missing = memories
    else:
        missing = [m for m in memories if "embedding" not in m or not m["embedding"]]

    if not missing:
        print(f"  [ok]   {label}: {len(memories)} entries, all already embedded")
        return

    verb = "re-embedding" if force else "embedding"
    print(f"  [work] {label}: {verb} {len(missing)}/{len(memories)} entries...")
    texts = [embeddings.embedding_text_for_entry(m.get("content", ""), m.get("tags", {})) for m in missing]
    vectors = embeddings.embed_texts(texts)

    for mem, vec in zip(missing, vectors):
        mem["embedding"] = vec

    with open(path, "w", encoding="utf-8") as f:
        json.dump(memories, f, indent=4, ensure_ascii=False)

    print(f"  [done] {label}: {len(missing)} entries embedded and saved")


def main():
    force = "--force" in sys.argv
    print("Migrating long-term memory entries to include embeddings...")
    if force:
        print("(--force: re-embedding ALL entries, including already-embedded ones)")
    print("(first run also downloads the embedding model — one-time cost)\n")

    # Guest memory
    guest_path = user_context.get_path("long_term", is_guest=True)
    _migrate_file(guest_path, "guest", force=force)

    # Every real user under backend/memory/users/<user_id>/
    users_dir = user_context.USERS_DIR
    if os.path.isdir(users_dir):
        for user_id in sorted(os.listdir(users_dir)):
            user_path = user_context.get_path("long_term", user_id=user_id, is_guest=False)
            _migrate_file(user_path, f"user:{user_id}", force=force)

    print("\nMigration complete.")


if __name__ == "__main__":
    main()
