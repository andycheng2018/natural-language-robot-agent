import os
import hashlib
import time
from pathlib import Path

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "")
ELEVENLABS_MODEL = os.getenv("ELEVENLABS_MODEL", "eleven_flash_v2_5")
ELEVENLABS_OUTPUT_FORMAT = os.getenv("ELEVENLABS_OUTPUT_FORMAT", "mp3_44100_128")
ELEVENLABS_TIMEOUT = int(os.getenv("ELEVENLABS_TIMEOUT_SECONDS", "15"))
ELEVENLABS_MAX_CHARS = int(os.getenv("ELEVENLABS_MAX_CHARS", "500"))
ELEVENLABS_STABILITY = float(os.getenv("ELEVENLABS_STABILITY", "0.50"))
ELEVENLABS_SIMILARITY = float(os.getenv("ELEVENLABS_SIMILARITY_BOOST", "0.75"))
ELEVENLABS_STYLE = float(os.getenv("ELEVENLABS_STYLE", "0.10"))
ELEVENLABS_SPEAKER_BOOST = os.getenv("ELEVENLABS_SPEAKER_BOOST", "true").lower() == "true"
TTS_CACHE = os.getenv("ELEVENLABS_TTS_CACHE", "true").lower() == "true"

_tts_cache: dict[str, bytes] = {}


def is_configured() -> bool:
    return bool(ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID)


def get_config_status() -> dict:
    return {
        "configured": is_configured(),
        "model": ELEVENLABS_MODEL,
        "voice_id": ELEVENLABS_VOICE_ID[:8] + "..." if ELEVENLABS_VOICE_ID else None,
        "cache_enabled": TTS_CACHE,
    }


def _cache_key(text: str) -> str:
    return hashlib.sha256(f"{ELEVENLABS_VOICE_ID}:{ELEVENLABS_MODEL}:{text}".encode()).hexdigest()


async def speak(text: str) -> tuple[bytes | None, str]:
    """
    Returns (audio_bytes, cache_status) where cache_status is 'hit', 'miss', or 'error'.
    Returns (None, 'error') if TTS is not configured or the request fails.
    """
    if not is_configured():
        return None, "not_configured"

    text = text[:ELEVENLABS_MAX_CHARS]
    key = _cache_key(text)

    if TTS_CACHE and key in _tts_cache:
        return _tts_cache[key], "hit"

    try:
        import httpx

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"
        headers = {
            "xi-api-key": ELEVENLABS_API_KEY,
            "Content-Type": "application/json",
        }
        payload = {
            "text": text,
            "model_id": ELEVENLABS_MODEL,
            "output_format": ELEVENLABS_OUTPUT_FORMAT,
            "voice_settings": {
                "stability": ELEVENLABS_STABILITY,
                "similarity_boost": ELEVENLABS_SIMILARITY,
                "style": ELEVENLABS_STYLE,
                "use_speaker_boost": ELEVENLABS_SPEAKER_BOOST,
            },
        }

        async with httpx.AsyncClient(timeout=ELEVENLABS_TIMEOUT) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            audio = resp.content

        if TTS_CACHE:
            _tts_cache[key] = audio

        return audio, "miss"

    except Exception as e:
        print(f"ElevenLabs TTS error: {e}")
        return None, "error"