"""Транскрипция голосовых (OpenAI Whisper). No-op без ключа — graceful fallback."""
from __future__ import annotations

import logging
import os
from typing import Optional

import aiohttp

log = logging.getLogger(__name__)

OPENAI_TRANSCRIBE_URL = "https://api.openai.com/v1/audio/transcriptions"


def transcription_enabled() -> bool:
    return bool(os.getenv("OPENAI_API_KEY", "").strip())


async def transcribe(audio: bytes, filename: str = "voice.oga") -> tuple[Optional[str], Optional[str]]:
    """Возвращает распознанный текст и безопасное для пользователя описание ошибки."""
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None, "OpenAI API түлхүүр тохируулагдаагүй байна."
    model = os.getenv("OPENAI_WHISPER_MODEL", "whisper-1")
    try:
        form = aiohttp.FormData()
        form.add_field("model", model)
        # Do not force Russian: Whisper can auto-detect Mongolian, English,
        # Russian, and other supported languages from the recording.
        language = os.getenv("OPENAI_TRANSCRIBE_LANGUAGE", "").strip()
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
                    log.warning("Whisper API %s: %s", resp.status, (await resp.text())[:300])
                    if resp.status == 401:
                        return None, "OpenAI API түлхүүр хүчингүй, хугацаа нь дууссан эсвэл хүчингүй болгогдсон байна."
                    if resp.status == 429:
                        return None, "OpenAI-ийн quota/лимит хүрсэн байна. Billing болон usage-аа шалгана уу."
                    if resp.status == 400:
                        return None, "Аудио эсвэл Whisper-ийн тохиргоог OpenAI хүлээж авсангүй."
                    return None, "Дуу хоолой таних үйлчилгээ түр алдаатай байна. Дахин оролдоно уу."
                data = await resp.json()
                text = (data.get("text") or "").strip()
                return text or None, None
    except Exception:  # noqa: BLE001 — фолбэк на текстовый ввод
        log.exception("Ошибка транскрипции голосового")
        return None, "OpenAI-ийн дуу хоолой таних үйлчилгээтэй холбогдож чадсангүй."
