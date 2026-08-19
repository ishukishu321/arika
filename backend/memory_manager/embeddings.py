"""
Embeddings helper for semantic (RAG) memory search.

Uses fastembed (ONNX runtime backend) instead of sentence-transformers/torch
to keep RAM + install size low on constrained hardware (i3, 8GB RAM).

Model is loaded ONCE per process (singleton) — loading it per-call would be
slow and wasteful. First call downloads the model (~250MB, multilingual model
is larger than the old English-only one) to a local cache
folder and keeps it there for future runs (no re-download).
"""

import math
import os

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBED_DIM = 384

# Was: sentence-transformers/all-MiniLM-L6-v2.
# That model is ENGLISH-ONLY — it was never going to embed Hinglish/Hindi
# queries close to English-phrased memory content in vector space. That is
# the real cause of weak/missed matches on Hinglish queries, not the
# similarity threshold. paraphrase-multilingual-MiniLM-L12-v2 supports 50+
# languages including Hindi, keeps the same 384-dim output (so existing
# cosine_similarity/threshold code needs no other changes), and is still
# small enough to run comfortably via fastembed/ONNX on this hardware.
#
# IMPORTANT: changing MODEL_NAME changes the embedding space. Old vectors
# stored on existing long-term memory entries were computed with the old
# model and are NOT comparable to new query vectors — they must be
# regenerated, or every existing memory will silently stop matching (scores
# will look near-random, not obviously wrong). Re-run
# scripts/migrate_embeddings.py (or force it to overwrite existing
# 'embedding' fields, not just fill missing ones) after this change,
# otherwise old entries just quietly go dark instead of matching worse.

# Cache the ONNX model files inside the project so it's not scattered in the
# user's global home directory, and so it survives if HOME changes.
_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "memory",
    ".embedding_model_cache",
)

_model = None  # lazy singleton


def warmup():
    """Force-load the embedding model right now (downloading it if needed)
    instead of waiting for the first real embed_text/embed_texts call.

    Used by installer.py so the ~250MB model download happens once during
    setup — with the setup window open and the user expecting a wait — 
    rather than silently blocking the first chat message or the first
    migrate_embeddings run after install.
    """
    _get_model()


def _get_model():
    """Load the fastembed model once and reuse it for the lifetime of the process."""
    global _model
    if _model is None:
        from fastembed import TextEmbedding
        os.makedirs(_CACHE_DIR, exist_ok=True)
        print("[Embeddings] Loading paraphrase-multilingual-MiniLM-L12-v2 (fastembed/ONNX)... first run downloads ~250MB")
        _model = TextEmbedding(model_name=MODEL_NAME, cache_dir=_CACHE_DIR)
        print("[Embeddings] Model ready.")
    return _model


def embed_text(text: str) -> list:
    """Embed a single string. Returns a plain python list[float] (JSON-serializable)."""
    if not text or not text.strip():
        return [0.0] * EMBED_DIM
    model = _get_model()
    vector = next(model.embed([text]))
    return vector.tolist()


def embed_texts(texts: list) -> list:
    """Batch-embed multiple strings at once (faster than calling embed_text in a loop)."""
    if not texts:
        return []
    model = _get_model()
    vectors = list(model.embed(texts))
    return [v.tolist() for v in vectors]


def cosine_similarity(a: list, b: list) -> float:
    """Standard cosine similarity between two equal-length vectors. Returns 0.0 on any mismatch."""
    if not a or not b or len(a) != len(b):
        return 0.0

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot / (norm_a * norm_b)


# Max number of tags folded into the embedding text. Mega-summary entries can
# carry 30+ tags; embedding all of them dilutes the actual signal so much that
# genuinely relevant queries (e.g. "what am I learning") score below the
# search thresholds even when the content clearly answers them. Keeping only
# the highest-importance tags preserves the topic signal without drowning it.
MAX_EMBED_TAGS = 8


def embedding_text_for_entry(content: str, tags: dict) -> str:
    """
    Build the text that actually gets embedded for a long-term memory entry.
    Combining content + the entry's most important tag names (underscores ->
    spaces) gives the model more signal than content alone, since tags capture
    topic/intent explicitly. Only the top MAX_EMBED_TAGS by importance are
    used — including every tag (an entry can have 30+) dilutes the embedding
    and drags down similarity scores for genuinely relevant queries.
    """
    tags = tags or {}

    def _importance(item):
        _, meta = item
        if isinstance(meta, dict):
            return meta.get("importance", 0)
        return 0

    top_tags = sorted(tags.items(), key=_importance, reverse=True)[:MAX_EMBED_TAGS]
    tag_text = " ".join(tag.replace("_", " ") for tag, _ in top_tags)
    return f"{content} {tag_text}".strip()
