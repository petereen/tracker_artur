"""Транскрипция голосовых (OpenAI Whisper). No-op без ключа — graceful fallback."""
from __future__ import annotations

import logging
import os
import re
from typing import Optional

import aiohttp

log = logging.getLogger(__name__)

OPENAI_TRANSCRIBE_URL = "https://api.openai.com/v1/audio/transcriptions"


def transcription_enabled() -> bool:
    return bool(os.getenv("OPENAI_API_KEY", "").strip())


def _api_error_message(body: str) -> str:
    """Return a compact upstream error suitable for a Telegram user message."""
    match = re.search(r'"message"\s*:\s*"([^"]+)', body)
    message = match.group(1) if match else body
    return " ".join(message.split())[:240]


async def transcribe(audio: bytes, filename: str = "voice.ogg") -> tuple[Optional[str], Optional[str]]:
    """Возвращает распознанный текст и безопасное для пользователя описание ошибки."""
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None, "OpenAI API түлхүүр тохируулагдаагүй байна."
    model = os.getenv("OPENAI_WHISPER_MODEL", "gpt-4o-mini-transcribe")
    try:
        # Do not force Russian: Whisper can auto-detect Mongolian, English,
        # Russian, and other supported languages from the recording.
        language = os.getenv("OPENAI_TRANSCRIBE_LANGUAGE", "").strip()
        mongolian_hint = language.lower() in {"mn", "mon"}
        # Whisper rejects the `mn` hint, while it can still auto-detect spoken
        # Mongolian when the language field is omitted.
        if mongolian_hint:
            log.info("Ignoring unsupported Whisper language hint: %s", language)
            language = ""
            # Mongolian is not a quality-guaranteed Whisper language. Prefer
            # the newer transcription model unless an operator explicitly
            # chooses a different Mongolian model.
            if model == "whisper-1":
                model = os.getenv("OPENAI_MONGOLIAN_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")
        form = aiohttp.FormData()
        form.add_field("model", model)
        if mongolian_hint:
            form.add_field(
                "prompt",
                "The audio is spoken in Mongolian. Transcribe it in Mongolian Cyrillic.",
            )
        if language:
            form.add_field("language", language)
        form.add_field("file", audio, filename=filename, content_type="audio/ogg")
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                OPENAI_TRANSCRIBE_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                data=form,
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    log.warning("Whisper API %s: %s", resp.status, body[:300])
                    if resp.status == 401:
                        return None, "OpenAI API түлхүүр хүчингүй, хугацаа нь дууссан эсвэл хүчингүй болгогдсон байна."
                    if resp.status == 429:
                        return None, "OpenAI-ийн quota/лимит хүрсэн байна. Billing болон usage-аа шалгана уу."
                    if resp.status == 400:
                        detail = _api_error_message(body)
                        return None, f"OpenAI аудио хүсэлтийг хүлээж авсангүй: {detail or 'тодорхойгүй алдаа'}"
                    return None, "Дуу хоолой таних үйлчилгээ түр алдаатай байна. Дахин оролдоно уу."
                data = await resp.json()
                text = (data.get("text") or "").strip()
                return text or None, None
    except Exception:  # noqa: BLE001 — фолбэк на текстовый ввод
        log.exception("Ошибка транскрипции голосового")
        return None, "OpenAI-ийн дуу хоолой таних үйлчилгээтэй холбогдож чадсангүй."
