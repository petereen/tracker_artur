"""ElevenLabs for OYUNS voice calls: streaming TTS and Scribe STT.

The browser streams speech straight from ElevenLabs' ``stream-input``
WebSocket with a single-use ``tts_websocket`` token minted here, so the
organization API key never leaves the server (like the OpenAI client secret).
"""
from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import quote, urlencode

import aiohttp

log = logging.getLogger(__name__)

API_BASE = "https://api.elevenlabs.io"
WS_BASE = "wss://api.elevenlabs.io"
TOKEN_URL = f"{API_BASE}/v1/single-use-token/tts_websocket"
STT_URL = f"{API_BASE}/v1/speech-to-text"
VOICES_URL = f"{API_BASE}/v1/voices"
STT_MODEL = "scribe_v2"
# Raw 16-bit mono PCM: the browser schedules it without decoding.
OUTPUT_FORMAT = "pcm_24000"
OUTPUT_SAMPLE_RATE = 24_000
# Seconds the socket waits for text; the client sends the answer at once.
INACTIVITY_TIMEOUT = 30
# Scribe language codes (ISO 639-1 or -3) → the three call languages.
CALL_LANGUAGES = {"mn": "mn", "mon": "mn", "khk": "mn", "ru": "ru", "rus": "ru", "en": "en", "eng": "en"}


class ElevenLabsError(RuntimeError):
    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind


def error_kind(status: int) -> str:
    return {401: "invalid_key", 403: "forbidden", 404: "not_found", 422: "rejected", 429: "rate_limited"}.get(status, "provider_error" if status >= 500 else "rejected")


async def create_tts_token(api_key: str) -> str:
    """A single-use, 15-minute token for one TTS WebSocket connection."""
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.post(TOKEN_URL, headers={"xi-api-key": api_key}) as response:
                if response.status != 200:
                    log.warning("elevenlabs.token_failed status=%s detail=%s", response.status, (await response.text())[:300])
                    raise ElevenLabsError(error_kind(response.status))
                body = await response.json()
    except (aiohttp.ClientError, TimeoutError) as exc:
        raise ElevenLabsError("network") from exc
    token = body.get("token") if isinstance(body, dict) else None
    if not token:
        raise ElevenLabsError("invalid_response")
    return str(token)


def stream_url(voice_id: str, model_id: str, token: str) -> str:
    query = urlencode({
        "model_id": model_id,
        "output_format": OUTPUT_FORMAT,
        "inactivity_timeout": INACTIVITY_TIMEOUT,
        "single_use_token": token,
    })
    return f"{WS_BASE}/v1/text-to-speech/{quote(voice_id, safe='')}/stream-input?{query}"


async def _post_stt(audio: bytes, api_key: str, language_code: str | None, content_type: str) -> tuple[int, dict | str]:
    form = aiohttp.FormData()
    form.add_field("model_id", STT_MODEL)
    form.add_field("tag_audio_events", "false")
    if language_code:
        form.add_field("language_code", language_code)
    form.add_field("file", audio, filename="speech.wav", content_type=content_type)
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
        async with session.post(STT_URL, headers={"xi-api-key": api_key}, data=form) as response:
            if response.status != 200:
                return response.status, (await response.text())[:300]
            return 200, await response.json()


async def transcribe(audio: bytes, api_key: str, *, fallback_language: str, content_type: str = "audio/wav") -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Scribe STT limited to the call languages: (text, language, error).

    Auto-detection first, so a caller can switch between Mongolian, Russian and
    English; a detection outside those (Mongolian heard as Kazakh or Korean)
    is retried pinned to the call language.
    """
    language_code: str | None = None
    try:
        for _ in range(2):
            status, body = await _post_stt(audio, api_key, language_code, content_type)
            if status != 200 or not isinstance(body, dict):
                log.warning("elevenlabs.stt_failed status=%s detail=%s", status, body)
                return None, None, error_kind(status)
            text = str(body.get("text") or "").strip()
            detected = CALL_LANGUAGES.get(str(body.get("language_code") or "").lower())
            if detected or language_code or not text:
                return text or None, detected or language_code or fallback_language, None
            language_code = fallback_language
    except (aiohttp.ClientError, TimeoutError):
        log.warning("elevenlabs.stt_network", exc_info=True)
        return None, None, "network"
    return None, None, "not_understood"


async def list_voices(api_key: str) -> list[dict]:
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.get(VOICES_URL, headers={"xi-api-key": api_key}) as response:
                if response.status != 200:
                    raise ElevenLabsError(error_kind(response.status))
                body = await response.json()
    except (aiohttp.ClientError, TimeoutError) as exc:
        raise ElevenLabsError("network") from exc
    voices = []
    for item in body.get("voices", []) if isinstance(body, dict) else []:
        if not isinstance(item, dict) or not item.get("voice_id"):
            continue
        labels = item.get("labels") if isinstance(item.get("labels"), dict) else {}
        voices.append({
            "voice_id": str(item["voice_id"]),
            "name": str(item.get("name") or item["voice_id"]),
            "category": item.get("category"),
            "description": ", ".join(str(value) for key, value in labels.items() if key in {"gender", "accent", "age"} and value) or None,
        })
    return sorted(voices, key=lambda voice: voice["name"].lower())
