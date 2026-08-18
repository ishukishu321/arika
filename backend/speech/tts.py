"""
Text-to-Speech module.
Splits long replies into speakable chunks and generates audio for each one
in parallel using edge-tts. The voice is read from settings_manager, so it
can be changed at runtime from the web Settings panel without touching code.
"""

import asyncio
import os
import re
import time

import edge_tts

from backend import settings_manager


def chunk_text(text: str, max_length: int = 150):
    """Split text into chunks based on punctuation, to avoid breaking words
    and to keep each TTS request short enough to feel responsive."""
    sentences = re.split(r'(?<=[.!?\n])\s+', text)
    chunks = []
    current_chunk = ""

    for sentence in sentences:
        if len(current_chunk) + len(sentence) < max_length:
            current_chunk += " " + sentence
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = sentence

    if current_chunk:
        chunks.append(current_chunk.strip())
    return chunks


async def _delayed_generate(text: str, filename: str, audio_dir: str, delay_sec: float, voice: str):
    """Generate one audio chunk, staggered slightly to avoid TTS rate limits."""
    await asyncio.sleep(delay_sec)
    communicate = edge_tts.Communicate(text, voice)
    try:
        await communicate.save(os.path.join(audio_dir, filename))
        return filename
    except Exception as e:
        print(f"[TTS Error in chunk] {e}")
        return None


async def generate_audio_chunks(text: str, audio_dir: str, voice: str = None):
    """Process multiple text chunks in parallel and return the list of
    generated filenames (in order)."""
    if voice is None:
        voice = settings_manager.get_tts_voice()

    os.makedirs(audio_dir, exist_ok=True)

    chunks = chunk_text(text)
    tasks = []

    for i, chunk in enumerate(chunks):
        if not chunk.strip():
            continue
        filename = f"resp_{int(time.time())}_{i}.mp3"
        # 0.2s stagger gap between requests to keep it fast but avoid limits
        tasks.append(_delayed_generate(chunk, filename, audio_dir, delay_sec=i * 0.2, voice=voice))

    if not tasks:
        return []

    results = await asyncio.gather(*tasks)
    return [f for f in results if f]


def generate_audio_chunks_sync(text: str, audio_dir: str, voice: str = None):
    """Convenience sync wrapper for Flask routes."""
    return asyncio.run(generate_audio_chunks(text, audio_dir, voice=voice))


async def list_voices(locale_prefix: str = None):
    """Return all voices edge-tts can see, optionally filtered by locale
    prefix (e.g. 'en-IN', 'hi-IN'). Useful if you want to offer the full
    catalogue in the settings UI instead of the curated shortlist."""
    voices = await edge_tts.list_voices()
    if locale_prefix:
        voices = [v for v in voices if v["Locale"].startswith(locale_prefix)]
    return voices
