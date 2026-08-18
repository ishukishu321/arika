import json
import os
from datetime import datetime
import sys

# Add parent directory to path so we can import gemini
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.gemini import ask_gemini
from backend import user_context

GEMINI_MODEL = "gemini-3.1-flash-lite"


def _summary_file():
    """Resolves to the CURRENT user's (or guest's) summary file."""
    return user_context.get_path("summary")


def initialize():
    """Creates the summary-memory file when it does not exist."""
    path = _summary_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)

    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump([], f, indent=4)


def load_summaries():
    initialize()

    with open(_summary_file(), "r", encoding="utf-8") as f:
        return json.load(f)


def _build_summary_prompt(messages):
    conversation = "\n\n".join(
        f"User: {message['user']}\nArika: {message['arika']}"
        for message in messages
    )

    return f"""
Create a short, factual memory summary of this conversation segment.
Return only the summary text and do not add labels, numbering, or explanations.
Keep important facts, decisions, user preferences, questions, and unresolved tasks.
Do not invent details. Do not mention that you are summarizing.

CONVERSATION SEGMENT
{conversation}
"""


def _normalize_summary_text(text):
    if not text:
        return ""

    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="ignore")

    text = text.strip()
    for prefix in ["Summary:", "Summary -", "Summary"]:
        if text.startswith(prefix):
            text = text[len(prefix):].strip(" :\n")
            break

    return text


def _extract_summary(response):
    choices = []
    if isinstance(response, dict):
        choices = response.get("choices", [])
    else:
        choices = getattr(response, "choices", [])

    if not choices:
        return "", response

    first_choice = choices[0]
    summary = None

    if isinstance(first_choice, dict):
        summary = (
            first_choice.get("message", {}).get("content")
            or first_choice.get("content")
        )
    else:
        summary = getattr(getattr(first_choice, "message", None), "content", None)
        if summary is None:
            summary = getattr(first_choice, "content", None)

    return _normalize_summary_text(summary), response


def create_summary(messages):
    """Use Gemini to turn exactly five old exchanges into a summary."""
    if len(messages) != 5:
        raise ValueError("A summary batch must contain exactly 5 exchanges.")

    last_error = None

    prompt = _build_summary_prompt(messages)
    for attempt in range(2):
        response_text = ask_gemini(prompt, model=GEMINI_MODEL)
        summary = _normalize_summary_text(response_text)

        if summary:
            return summary


def _build_mega_summary_prompt(summaries):
    """Build prompt to create mega summary from 5 old summaries."""
    combined = "\n\n".join(
        f"Summary {i+1}:\n{s['summary']}"
        for i, s in enumerate(summaries)
    )
    
    return f"""
You are a memory consolidation expert. Create a comprehensive MEGA SUMMARY by synthesizing these 5 older summaries.

IMPORTANT INSTRUCTIONS:
1. Extract and merge key facts, decisions, user preferences, patterns, and unresolved tasks
2. Preserve critical context and timeline
3. Remove redundancy but keep important details
4. Format: Return ONLY the consolidated summary text. No labels or intro.

OLD SUMMARIES TO CONSOLIDATE:
{combined}

Create the mega summary now:
"""


def _extract_json_object(text):
    """Extract the first balanced JSON object from the text."""
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    for index, char in enumerate(text[start:], start):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return None


def _clean_json_text(text):
    """Clean common LLM JSON formatting issues."""
    import re

    cleaned = text
    cleaned = re.sub(r'```(?:json)?\n', "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'```', "", cleaned)
    cleaned = re.sub(r'^[^\{]*', "", cleaned)
    cleaned = re.sub(r'[^\}]*$', "", cleaned)
    cleaned = cleaned.replace("'", '"')
    cleaned = re.sub(r',\s*\}', '}', cleaned)
    cleaned = re.sub(r',\s*\]', ']', cleaned)

    return cleaned


def _generate_tags_from_mega_summary(mega_summary):
    """Generate 30+ relevant tags with positions and importance scores using Gemini."""
    prompt = f"""
You are a tagging expert. Analyze this mega summary and extract 30-40 unique, meaningful tags.

MEGA SUMMARY:
{mega_summary}

INSTRUCTIONS:
1. Generate 30-40 tags that capture key topics, entities, concepts, and themes
2. For each tag, provide:
   - Tag name (lowercase, no spaces, use underscores)
   - Position: Line and character offset where this tag concept appears in the summary
   - Importance: Score 1-10 (10 = most important/frequently mentioned)

Return ONLY a valid JSON object in this format:
{{
    "tag1_name": {{"position": 45, "importance": 9}},
    "tag2_name": {{"position": 120, "importance": 7}},
    ...
}}
"""
    
    response_text = ask_gemini(prompt, model=GEMINI_MODEL)
    
    try:
        json_text = _extract_json_object(response_text)
        if json_text:
            return json.loads(json_text)

        cleaned = _clean_json_text(response_text)
        json_text = _extract_json_object(cleaned)
        if json_text:
            return json.loads(json_text)

        return json.loads(cleaned)
    except:
        pass
    
    # Fallback: generate basic tags if parsing fails
    return {
        "memory_consolidation": {"position": 0, "importance": 10},
        "user_interactions": {"position": 50, "importance": 8},
        "key_decisions": {"position": 100, "importance": 9},
        "unresolved_tasks": {"position": 150, "importance": 7},
        "user_preferences": {"position": 200, "importance": 8}
    }


def create_mega_summary():
    """
    Check if 5+ summaries exist. If yes:
    - Take 5 oldest summaries
    - Create mega summary using Gemini
    - Generate 30+ tags with positions and importance
    - Return mega summary with tags
    """
    summaries = load_summaries()
    
    if len(summaries) < 5:
        return None
    
    # Get 5 oldest summaries
    old_5_summaries = summaries[:5]
    
    # Create mega summary from the 5 old ones
    mega_prompt = _build_mega_summary_prompt(old_5_summaries)
    mega_summary_text = ask_gemini(mega_prompt, model=GEMINI_MODEL)
    mega_summary_text = _normalize_summary_text(mega_summary_text)
    
    # Generate tags
    tags = _generate_tags_from_mega_summary(mega_summary_text)
    
    # Return in the required format
    return {
        "content": mega_summary_text,
        "tags": tags,
        "timestamp": datetime.now().isoformat(),
        "source_summary_ids": [s["id"] for s in old_5_summaries]
    }


def save_summary(summary, source_messages):
    """Persist a completed summary."""
    summaries = load_summaries()
    next_id = max((s.get("id", 0) for s in summaries if isinstance(s.get("id", 0), int)), default=0) + 1

    summaries.append({
        "id": next_id,
        "summary": summary
    })

    with open(_summary_file(), "w", encoding="utf-8") as f:
        json.dump(summaries, f, indent=4, ensure_ascii=False)


def get_recent_summaries(limit=3):
    """Return up to the latest three summaries for the LLM prompt."""
    return load_summaries()[-limit:]


if __name__ == "__main__":
    """Run standalone to check if mega summary can be created."""
    print("🔍 Summary Maker - Checking for mega summary creation...")
    print(f"   Current summaries: {len(load_summaries())}")
    
    mega = create_mega_summary()
    if mega:
        print("✅ Mega summary created successfully!")
        print(f"   Content length: {len(mega['content'])} chars")
        print(f"   Tags: {len(mega['tags'])} tags")
    else:
        print("⏳ Not enough summaries yet (need 8+)")

