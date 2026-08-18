"""
Speech-to-Text module.

STT is fully browser-integrated: live listening + wake-word detection
happen client-side via the Web Speech API in
frontend/static/js/stt.js — no server round-trip, no local model to
install or manage (no Vosk, no whisper, nothing to download).

This module just holds the small bits of STT config that both the
frontend and backend need to agree on (language, wake word), plus a
matching helper kept in sync with the JS-side logic in case anything
server-side ever needs to double check a transcript.
"""

from backend import settings_manager


def get_stt_lang() -> str:
    """Language/locale handed to the browser's SpeechRecognition."""
    return settings_manager.get_stt_lang()


def get_wake_word() -> str:
    return settings_manager.get_wake_word()


def matches_wake_word(transcript: str, wake_word: str = None) -> bool:
    """Loose wake-word check, mirrors the JS-side logic in stt.js.
    An empty wake word means wake-word gating is disabled: everything
    heard is treated as a match."""
    if not transcript:
        return False
    wake_word = (wake_word if wake_word is not None else get_wake_word()).strip().lower()
    if not wake_word:
        return True
    text = transcript.strip().lower()
    return text.startswith(wake_word) or f" {wake_word}" in text or text.startswith(wake_word[:1])
