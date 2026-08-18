from backend.memory_manager.short_term import get_recent_messages
from backend.memory_manager.summary_maker import get_recent_summaries
from backend.memory_manager.long_term_mem_manager import search_memories_semantic, get_memory_context_for_prompt
from backend.memory_manager import minecraft_memory
from backend import user_context
from backend import minecraft_manager

# How confident the auto-search has to be before it silently injects context.
# Higher than the manual review_mem path (0.28) on purpose — this runs on
# EVERY message including "ok"/"thanks", so we only want it firing on genuinely
# strong matches. Weak/ambiguous cases are left for Gemini's manual review_mem
# tool call instead, which can build smarter multi-tag queries from full
# conversation context rather than just the raw current message.
#
# Recalibrated from 0.5 -> 0.35 (2026-08-16): measured against this project's
# actual archive, short/casual queries against long narrative entries score
# 0.28-0.40 for genuine matches, while small-talk/irrelevant queries ("ok
# thanks", "lol nice") top out around 0.12-0.18. 0.5 was rejecting real
# matches; 0.35 keeps a safety margin above the irrelevant-query ceiling.
AUTO_SEARCH_MIN_SCORE = 0.35


def _auto_search_long_term(user_message: str) -> str:
    """
    Runs once per message, automatically, using the raw user message as the
    query — no Gemini tool call needed. Fails silently (returns None) on any
    error so a slow/broken embedding backend never blocks a reply; Gemini's
    manual review_mem tool remains available as a fallback in that case.
    """
    try:
        user_id = user_context.get_user_id()
        is_guest = user_context.is_guest()
        result = search_memories_semantic(
            user_message,
            user_id=user_id,
            is_guest=is_guest,
            min_score=AUTO_SEARCH_MIN_SCORE,
        )
        if result["status"] == "found":
            top_score = result["contexts"][0]["match_score"]
            print(f"[Auto Search] MATCH found (top score {top_score}) for: {user_message[:60]!r}")
        else:
            print(f"[Auto Search] no match ({result['status']}) for: {user_message[:60]!r}")
        return get_memory_context_for_prompt(result)
    except Exception as e:
        print(f"[Prompt Builder] Auto memory search skipped: {e}")
        return None


def build_prompt(user_message: str, long_term_context: str = None) -> str:
    """
    Builds the conversation prompt for Gemini.

    Args:
        user_message: The current user message
        long_term_context: Optional long-term memory context. If not given,
            build_prompt automatically runs a semantic search on user_message
            itself and uses that when a strong match is found. Pass this
            explicitly (as app.py/cli.py already do after a manual review_mem
            tool call) to skip the auto-search and use that context instead.
    """

    messages = get_recent_messages()
    summaries = get_recent_summaries()

    conversation = ""
    summary_context = ""
    long_term_section = ""

    if long_term_context is None:
        long_term_context = _auto_search_long_term(user_message)

    for summary in summaries:
        summary_context += f"Summary {summary['id']}: {summary['summary']}\n\n"

    for msg in messages:
        conversation += (
            f"Time: {msg['timestamp']}\n"
            f"User: {msg['user']}\n"
            f"Arika: {msg['arika']}\n\n"
        )

    # Add long-term memory context if provided
    if long_term_context:
        long_term_section = f"""
==============================
LONG-TERM MEMORY ARCHIVE
==============================

{long_term_context}
"""

    # Minecraft's own short-term memory (last ~25 events + running summary +
    # world_state) is kept OUT of every normal prompt by default — it only
    # gets folded in here while Minecraft mode is active, per
    # backend/minecraft_manager.py's mode gating. When mode is off, this
    # memory is still reachable through the recall_minecraft_memory tool
    # instead (backend/command_router.py), without loading full context.
    minecraft_section = ""
    if minecraft_manager.is_active():
        mc_context = minecraft_memory.get_context_block()
        if mc_context:
            minecraft_section = f"""
==============================
MINECRAFT SHORT-TERM MEMORY
==============================

{mc_context}
"""

    prompt = f"""
==============================
CONVERSATION SUMMARIES
==============================

{summary_context}{long_term_section}{minecraft_section}

==============================
RECENT CONVERSATION
==============================

{conversation}

==============================
CURRENT USER MESSAGE
==============================

User: {user_message}
"""

    return prompt