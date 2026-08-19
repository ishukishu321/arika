"""
Long-term memory manager.
Handles searching through archived memories using tags with parallel processing.
"""

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Tuple

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import user_context
from backend.memory_manager import embeddings


def _long_term_file(user_id: str = None, is_guest: bool = None):
    return user_context.get_path("long_term", user_id=user_id, is_guest=is_guest)


def load_long_term_memories(user_id: str = None, is_guest: bool = None):
    """Load all long-term memory entries for the given user or current context."""
    path = _long_term_file(user_id=user_id, is_guest=is_guest)
    try:
        if not os.path.exists(path):
            return []

        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        # Was a bare `except: return []` — that silently treated ANY error
        # (corrupt JSON, permissions, disk issues) as "no memories exist",
        # with zero trace anywhere. At least log it now so a broken memory
        # file shows up as a loud warning instead of quietly acting like
        # the archive is empty.
        print(f"[Long Term Mem Manager] Failed to load memories ({path}): {e}")
        return []


def _match_tags(memory_id: str, memory_entry: Dict, search_tags: Dict) -> Tuple[str, int, Dict]:
    """
    Match search tags against a memory entry's tags.
    Returns: (memory_id, match_score, memory_entry)
    """
    match_score = 0
    memory_tags = memory_entry.get("tags", {})
    
    # Count how many search tags match with memory tags
    for search_tag_key in search_tags.keys():
        if search_tag_key in memory_tags:
            # Higher importance = higher score
            importance = memory_tags[search_tag_key].get("importance", 0)
            match_score += importance
    
    return memory_id, match_score, memory_entry


def _extract_context(content: str, position: int, context_chars: int = 50) -> str:
    """
    Extract context around a position in the content.
    Returns text with `context_chars` before and after the position.
    """
    start = max(0, position - context_chars)
    end = min(len(content), position + context_chars)
    
    return content[start:end].strip()


def _extract_keywords(search_tags: Dict) -> List[str]:
    keywords = []
    for key in search_tags.keys():
        if not isinstance(key, str):
            continue
        normalized = key.replace("_", " ").strip().lower()
        if normalized:
            keywords.extend(normalized.split())
    return [kw for kw in keywords if kw]


def _score_by_keywords(content: str, keywords: List[str]) -> int:
    text = content.lower()
    score = 0
    for kw in keywords:
        score += text.count(kw)
    return score


def _save_long_term_memories(memories: List[Dict], user_id: str = None, is_guest: bool = None):
    """Persist the (possibly embedding-updated) memories list back to disk."""
    path = _long_term_file(user_id=user_id, is_guest=is_guest)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(memories, f, indent=4, ensure_ascii=False)


def _ensure_embeddings(memories: List[Dict], user_id: str = None, is_guest: bool = None) -> List[Dict]:
    """
    Lazy migration: any entry missing an 'embedding' (e.g. created before this
    feature existed, or created while embedding generation failed) gets one
    computed now. Only writes to disk if something actually changed, so this
    stays cheap on every call once memories are fully migrated.
    """
    changed = False

    missing = [m for m in memories if "embedding" not in m or not m["embedding"]]
    if missing:
        texts = [embeddings.embedding_text_for_entry(m.get("content", ""), m.get("tags", {})) for m in missing]
        try:
            vectors = embeddings.embed_texts(texts)
            for mem, vec in zip(missing, vectors):
                mem["embedding"] = vec
            changed = True
        except Exception as e:
            print(f"[Long Term Mem Manager] Lazy embedding failed: {e}")

    if changed:
        _save_long_term_memories(memories, user_id=user_id, is_guest=is_guest)

    return memories


def search_memories_semantic(
    query_text: str,
    user_id: str = None,
    is_guest: bool = None,
    top_k: int = 3,
    min_score: float = 0.28,
) -> Dict:
    """
    Semantic (embedding-based) search over long-term memories.

    Unlike the old tag/keyword matcher, this compares MEANING via cosine
    similarity, so a query like "study abroad plans" can match an entry about
    "AI/ML engineering program in Japan" even with zero shared keywords.

    min_score is a similarity threshold (cosine similarity ranges -1..1, but
    for real sentences it's almost always 0..1). Below this, a match is
    considered too weak to be useful context and gets dropped.
    """
    if not query_text or not query_text.strip():
        return {"status": "error", "message": "No query text provided"}

    memories = load_long_term_memories(user_id=user_id, is_guest=is_guest)
    if not memories:
        return {"status": "not_found", "message": "Memory archive is empty"}

    try:
        memories = _ensure_embeddings(memories, user_id=user_id, is_guest=is_guest)
        query_vector = embeddings.embed_text(query_text)
    except Exception as e:
        return {"status": "error", "message": f"Embedding backend unavailable: {e}"}

    scored = []
    for mem in memories:
        vec = mem.get("embedding")
        if not vec:
            continue
        score = embeddings.cosine_similarity(query_vector, vec)
        if score >= min_score:
            scored.append((score, mem))

    if not scored:
        return {"status": "not_found", "message": "No semantically relevant memories found"}

    scored.sort(key=lambda x: x[0], reverse=True)
    top_matches = scored[:top_k]

    contexts = []
    for score, entry in top_matches:
        contexts.append({
            "id": entry["id"],
            "context": entry.get("content", "")[:200],
            "full_content": entry.get("content", ""),
            "match_score": round(float(score), 4),
        })

    return {
        "status": "found",
        "matches": len(contexts),
        "contexts": contexts,
    }


def search_memories(search_tags: Dict, user_id: str = None, is_guest: bool = None) -> Dict:
    """
    Search long-term memories using tags.
    
    Args:
        search_tags: Dictionary with tag names as keys
        user_id: Optional explicit user to load memory for
        is_guest: Optional explicit guest flag to load guest memory
        
    Returns:
        Dictionary with matching memory contexts or "Memory not found" message
    """
    
    if not search_tags:
        return {"status": "error", "message": "No tags provided"}

    # --- Try semantic search first ---
    # Gemini's review_mem tool still hands us a tag dict (that part of the
    # tool schema didn't change), so we turn those tags into a natural
    # language query ("user_preferences task_history" -> "user preferences
    # task history") and embed THAT. This upgrades matching from literal
    # keyword overlap to actual meaning, without touching the tool schema
    # or system prompt Gemini already relies on.
    query_text = " ".join(tag.replace("_", " ") for tag in search_tags.keys())
    print(f"[Review Mem] Gemini called review_mem with tags: {list(search_tags.keys())}")
    semantic_result = search_memories_semantic(query_text, user_id=user_id, is_guest=is_guest)
    if semantic_result["status"] == "found":
        top_score = semantic_result["contexts"][0]["match_score"]
        print(f"[Review Mem] semantic search MATCHED (top score {top_score})")
        return semantic_result
    print(f"[Review Mem] semantic search found nothing ({semantic_result['status']}), falling back to keyword matcher")
    # If embedding backend itself errored (e.g. fastembed not installed yet,
    # or first-run model download failed with no internet), fall through to
    # the old keyword matcher below rather than surfacing an error to the user.

    # Load all long-term memories for the requested user or current context
    memories = load_long_term_memories(user_id=user_id, is_guest=is_guest)
    
    if not memories:
        return {"status": "not_found", "message": "Memory archive is empty"}
    
    # --- Fallback: old tag/keyword matcher (kept as a safety net) ---
    # Parallel processing: match tags for each memory
    matches = []
    
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(_match_tags, mem["id"], mem, search_tags): mem["id"]
            for mem in memories
        }
        
        for future in as_completed(futures):
            memory_id, match_score, memory_entry = future.result()
            
            if match_score > 0:  # Only keep matches
                matches.append({
                    "id": memory_id,
                    "score": match_score,
                    "entry": memory_entry
                })
    
    if not matches:
        # Fallback: search by keywords extracted from tag names
        keywords = _extract_keywords(search_tags)
        fallback_matches = []
        for mem in memories:
            score = _score_by_keywords(mem.get("content", ""), keywords)
            if score > 0:
                fallback_matches.append({
                    "id": mem["id"],
                    "score": score,
                    "entry": mem
                })

        if fallback_matches:
            fallback_matches.sort(key=lambda x: x["score"], reverse=True)
            matches = fallback_matches[:3]
        else:
            return {"status": "not_found", "message": "No matching memories found"}
    
    # Sort by match score and take top 3
    matches.sort(key=lambda x: x["score"], reverse=True)
    top_matches = matches[:3]
    
    # Extract contexts from top matches
    contexts = []
    
    for match in top_matches:
        entry = match["entry"]
        content = entry.get("content", "")
        tags = entry.get("tags", {})
        
        # Find first matching tag's position
        position = 0
        for tag_key in search_tags.keys():
            if tag_key in tags:
                position = tags[tag_key].get("position", 0)
                break
        
        # Extract context around position
        context_text = _extract_context(content, position, context_chars=50)
        
        # Get importance scores for all matching tags
        importance_scores = {}
        for tag_key in search_tags.keys():
            if tag_key in tags:
                importance_scores[tag_key] = tags[tag_key].get("importance", 0)
        
        contexts.append({
            "id": entry["id"],
            "context": context_text,
            "importance_scores": importance_scores,
            "full_content": content,
            "match_score": match["score"]
        })
    
    return {
        "status": "found",
        "matches": len(contexts),
        "contexts": contexts
    }


def get_memory_context_for_prompt(search_result: Dict) -> str:
    """
    Convert search result into formatted text for prompt builder.
    Handles both result shapes: the old keyword matcher's 'importance_scores'
    and the new semantic search's 'match_score' (whichever is present).
    """
    if search_result["status"] != "found":
        return None
    
    formatted_text = "=== LONG-TERM MEMORY CONTEXT ===\n\n"
    
    for i, context in enumerate(search_result["contexts"], 1):
        formatted_text += f"Memory {i} (ID: {context['id']}):\n"
        formatted_text += f"Context: {context['context']}\n"
        if "importance_scores" in context:
            formatted_text += f"Importance Scores: {context['importance_scores']}\n\n"
        elif "match_score" in context:
            formatted_text += f"Relevance Score: {context['match_score']}\n\n"
        else:
            formatted_text += "\n"
    
    return formatted_text
