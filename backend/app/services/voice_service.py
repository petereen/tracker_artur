"""Incoming transcription and optional outgoing Chimege speech."""
from __future__ import annotations

import logging
import os
import re
import textwrap
import wave
from io import BytesIO
from typing import Optional

import aiohttp

log = logging.getLogger(__name__)

OPENAI_TRANSCRIBE_URL = "https://api.openai.com/v1/audio/transcriptions"
CHIMEGE_TRANSCRIBE_URL = "https://api.chimege.com/v1.2/transcribe"
CHIMEGE_NORMALIZE_TEXT_URL = "https://api.chimege.com/v1.2/normalize-text"
CHIMEGE_SYNTHESIZE_URL = "https://api.chimege.com/v1.2/synthesize"


def transcription_enabled() -> bool:
    return bool(
        os.getenv("CHIMEGE_API_TOKEN", "").strip()
        or os.getenv("OPENAI_API_KEY", "").strip()
    )


def synthesis_enabled() -> bool:
    """Whether outgoing Chimege text-to-speech is configured."""
    return bool(os.getenv("CHIMEGE_TTS_API_TOKEN", "").strip())


def _prepare_synthesis_text(text: str) -> str:
    """Keep only the Cyrillic and punctuation characters accepted by Chimege."""
    normalized = text.strip().lower()
    # Chimege accepts Cyrillic letters, whitespace, and only these marks:
    # ?, !, dots, hyphen, apostrophe, quote, colon, and comma.
    normalized = re.sub(r"[^\u0400-\u04ff\s?!.,:'\"-]", " ", normalized)
    return " ".join(normalized.split())


def _split_synthesis_text(text: str, width: int = 220) -> list[str]:
    """Split before normalization so Chimege's 300-char limit is respected."""
    return textwrap.wrap(
        text.strip(),
        width=width,
        break_long_words=False,
        break_on_hyphens=False,
    ) or []


def _merge_wav_segments(segments: list[bytes]) -> bytes:
    """Join Chimege WAV responses while preserving the WAV header format."""
    if len(segments) == 1:
        return segments[0]
    output = BytesIO()
    with wave.open(BytesIO(segments[0]), "rb") as first:
        params = first.getparams()
        frames = [first.readframes(first.getnframes())]
    for segment in segments[1:]:
        with wave.open(BytesIO(segment), "rb") as current:
            # Frame counts are expected to differ between chunks; compare
            # only channel count, sample width, and sample rate.
            if current.getparams()[:3] != params[:3]:
                raise ValueError("Chimege returned incompatible WAV segments")
            frames.append(current.readframes(current.getnframes()))
    with wave.open(output, "wb") as merged:
        merged.setparams(params)
        merged.writeframes(b"".join(frames))
    return output.getvalue()


async def _synthesize_chunk(
    session: aiohttp.ClientSession,
    raw_text: str,
    *,
    headers: dict[str, str],
    depth: int = 0,
) -> tuple[list[bytes], Optional[str]]:
    """Normalize and synthesize one chunk, splitting again when expansion is large."""
    async with session.post(
        CHIMEGE_NORMALIZE_TEXT_URL,
        headers=headers,
        data=raw_text.encode("utf-8"),
    ) as normalize_resp:
        normalized_body = await normalize_resp.read()
        if normalize_resp.status == 200 and normalized_body.strip():
            text = normalized_body.decode("utf-8", errors="replace")
        else:
            log.warning(
                "Chimege normalize-text API %s: %s",
                normalize_resp.status,
                normalized_body.decode("utf-8", errors="replace")[:300],
            )
            text = raw_text
    text = _prepare_synthesis_text(text)

    if len(text) > 300 and depth < 6:
        pieces = _split_synthesis_text(raw_text, max(40, len(raw_text) // 2))
        if len(pieces) > 1:
            result: list[bytes] = []
            for piece in pieces:
                audio, error = await _synthesize_chunk(
                    session,
                    piece,
                    headers=headers,
                    depth=depth + 1,
                )
                if error:
                    return [], error
                result.extend(audio)
            return result, None

    if not text:
        return [], "Хоосон хариултыг дуу болгон хөрвүүлэх боломжгүй."

    async with session.post(
        CHIMEGE_SYNTHESIZE_URL,
        headers=headers,
        data=text.encode("utf-8"),
    ) as resp:
        body = await resp.read()
        if resp.status == 200:
            return ([body], None) if body else ([], "Chimege хоосон аудио буцаалаа.")
        detail = body.decode("utf-8", errors="replace").strip()
        log.warning("Chimege TTS API %s: %s", resp.status, detail[:300])
        if resp.status == 400 and depth < 6:
            pieces = _split_synthesis_text(raw_text, max(40, len(raw_text) // 2))
            if len(pieces) > 1:
                result: list[bytes] = []
                for piece in pieces:
                    audio, error = await _synthesize_chunk(
                        session,
                        piece,
                        headers=headers,
                        depth=depth + 1,
                    )
                    if error:
                        return [], error
                    result.extend(audio)
                return result, None
        if resp.status == 403:
            return [], "Chimege API token хүчингүй эсвэл идэвхгүй байна."
        if resp.status == 400:
            return [], "Chimege хөрвүүлэх текстийг хүлээж авсангүй."
        if resp.status == 503:
            return [], "Chimege үйлчилгээ ачаалалтай байна. Дахин оролдоно уу."
        return [], "Chimege дуу үүсгэх үйлчилгээ түр алдаатай байна."


async def synthesize(text: str) -> tuple[Optional[bytes], Optional[str]]:
    """Convert text to Mongolian speech through Chimege's synchronous TTS API."""
    token = os.getenv("CHIMEGE_TTS_API_TOKEN", "").strip()
    if not token:
        return None, "Chimege TTS token тохируулагдаагүй байна."
    headers = {
        "Content-Type": "text/plain; charset=utf-8",
        "Token": token,
    }
    try:
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            # Normalize each bounded chunk so number expansion stays within
            # Chimege's 300-character normalized-text limit.
            segments: list[bytes] = []
            for chunk in _split_synthesis_text(text):
                audio, error = await _synthesize_chunk(session, chunk, headers=headers)
                if error:
                    return None, error
                segments.extend(audio)
            return (_merge_wav_segments(segments), None) if segments else (
                None,
                "Хоосон хариултыг дуу болгон хөрвүүлэх боломжгүй.",
            )
    except (ValueError, wave.Error):
        log.exception("Chimege WAV segment merge failed")
        return None, "Chimege аудио хэсгүүдийг нэгтгэж чадсангүй."
    except Exception:  # noqa: BLE001 — retain the text answer as a fallback
        log.exception("Chimege synthesis failed")
        return None, "Chimege дуу үүсгэх үйлчилгээтэй холбогдож чадсангүй."


async def _transcribe_chimege(audio: bytes, token: str) -> tuple[Optional[str], Optional[str]]:
    """Transcribe Mongolian speech through Chimege's synchronous STT endpoint."""
    headers = {
        "Content-Type": "application/octet-stream",
        "Punctuate": os.getenv("CHIMEGE_PUNCTUATE", "true"),
        "Token": token,
    }
    try:
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(CHIMEGE_TRANSCRIBE_URL, headers=headers, data=audio) as resp:
                body = (await resp.text()).strip()
                if resp.status == 200:
                    return body or None, None
                log.warning("Chimege STT API %s: %s", resp.status, body[:300])
                if resp.status == 403:
                    return None, "Chimege API token хүчингүй эсвэл идэвхгүй байна."
                if resp.status == 400:
                    return None, f"Chimege аудиог хүлээж авсангүй: {body[:240] or 'аудио формат эсвэл бичлэгийг шалгана уу'}"
                if resp.status == 503:
                    return None, "Chimege үйлчилгээ ачаалалтай байна. Дахин оролдоно уу."
                return None, "Chimege дуу хоолой таних үйлчилгээ түр алдаатай байна."
    except Exception:  # noqa: BLE001 — allow text task entry as a fallback
        log.exception("Chimege transcription failed")
        return None, "Chimege дуу хоолой таних үйлчилгээтэй холбогдож чадсангүй."


def _api_error_message(body: str) -> str:
    """Return a compact upstream error suitable for a Telegram user message."""
    match = re.search(r'"message"\s*:\s*"([^"]+)', body)
    message = match.group(1) if match else body
    return " ".join(message.split())[:240]


async def transcribe(audio: bytes, filename: str = "voice.ogg") -> tuple[Optional[str], Optional[str]]:
    """Возвращает распознанный текст и безопасное для пользователя описание ошибки."""
    chimege_token = os.getenv("CHIMEGE_API_TOKEN", "").strip()
    if chimege_token:
        return await _transcribe_chimege(audio, chimege_token)

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
