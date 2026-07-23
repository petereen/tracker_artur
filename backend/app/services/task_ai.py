"""LLM-структуризация задачи из свободного текста (OpenAI Chat Completions).
Опционален: без OPENAI_API_KEY все вызовы возвращают None — graceful fallback."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Optional

import aiohttp

log = logging.getLogger(__name__)

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"

_SYSTEM_PROMPT = (
    "Та бол OYUNS Agent — мэргэжлийн, товч, "
    "эмх цэгцтэй ажлын туслах. Чөлөөт текстийг даалгавар болгон бүтэцлэнэ. "
    "Монгол, англи эсвэл орос хэлээр ирсэн хүсэлтэд тухайн хэлээр нь гарчиг, "
    "тайлбар болон тодруулах асуулт бич. Өгөгдсөн ажилтны жагсаалтаас гадуур "
    "гүйцэтгэгч зохиож болохгүй."
)

_USER_TEMPLATE = """\
Одоогийн цаг: {now_iso} (цагийн бүс: {tz})

Ажилтнуудын жагсаалт:
{roster_json}

Даалгаврын текст:
{text}

Дараах бүтэцтэй үр дүн буцаана уу:
- "title": string (80 тэмдэгтээс уртгүй товч гарчиг)
- "description": string эсвэл null (дэлгэрэнгүй мэдээлэл байвал)
- "assignee_id": integer эсвэл null (ЗӨВХӨН жагсаалт дахь ажилтны id; тодорхойгүй бол null)
- "deadline_iso": string эсвэл null (цагийн бүсийг харгалзсан, зөвхөн ирээдүйн ISO 8601 хугацаа)
- "priority": 1, 2 эсвэл 3 (1=яаралтай, 2=ердийн, 3=бага)
- "needs_clarification": boolean (тодруулга шаардлагатай эсэх)
- "clarification": string эсвэл null (needs_clarification=true бол асуух асуулт)
"""

_TASK_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string"},
        "description": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "assignee_id": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
        "deadline_iso": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "priority": {"type": "integer", "enum": [1, 2, 3]},
        "needs_clarification": {"type": "boolean"},
        "clarification": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    },
    "required": [
        "title",
        "description",
        "assignee_id",
        "deadline_iso",
        "priority",
        "needs_clarification",
        "clarification",
    ],
}


def ai_enabled() -> bool:
    """True, если задан OPENAI_API_KEY."""
    return bool(os.getenv("OPENAI_API_KEY", "").strip())


def parse_llm_json(raw: str, roster_ids: set[int]) -> Optional[dict]:
    """Парсит и валидирует JSON-ответ LLM.

    Возвращает нормализованный dict или None при ошибке.
    Отдельная чистая функция — покрыта тестами, без сети.
    """
    if not raw:
        return None

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        log.debug("parse_llm_json: невалидный JSON: %r", raw[:200])
        return None

    if not isinstance(data, dict):
        return None

    # --- title ---
    title = data.get("title")
    if not isinstance(title, str) or not title.strip():
        return None
    title = title.strip()[:80]

    # --- description ---
    description = data.get("description")
    if not isinstance(description, str):
        description = None
    else:
        description = description.strip() or None

    # --- assignee_id ---
    assignee_id = data.get("assignee_id")
    if assignee_id is not None:
        try:
            assignee_id = int(assignee_id)
        except (TypeError, ValueError):
            assignee_id = None
        else:
            if assignee_id not in roster_ids:
                assignee_id = None

    # --- deadline_iso → datetime | None ---
    deadline_at: Optional[datetime] = None
    deadline_iso = data.get("deadline_iso")
    if isinstance(deadline_iso, str) and deadline_iso.strip():
        # Пробуем стандартный fromisoformat; фолбэк — dateparser
        deadline_at = _parse_deadline(deadline_iso.strip())

    # --- priority: клампим в 1..3 ---
    priority = data.get("priority", 2)
    try:
        priority = int(priority)
    except (TypeError, ValueError):
        priority = 2
    priority = max(1, min(3, priority))

    # --- needs_clarification ---
    needs_clarification = bool(data.get("needs_clarification", False))

    # --- clarification ---
    clarification = data.get("clarification")
    if not isinstance(clarification, str):
        clarification = None
    else:
        clarification = clarification.strip() or None

    return {
        "title": title,
        "description": description,
        "assignee_id": assignee_id,
        "deadline_at": deadline_at,
        "priority": priority,
        "needs_clarification": needs_clarification,
        "clarification": clarification,
    }


def _parse_deadline(raw: str) -> Optional[datetime]:
    """Парсит ISO-строку дедлайна; фолбэк на dateparser."""
    # Стандартный fromisoformat (Python 3.7+; с timezone-suffix — 3.11+)
    try:
        # Нормализуем Z → +00:00 для Python < 3.11
        normalized = raw.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    except (ValueError, AttributeError):
        pass

    # Фолбэк: dateparser (опциональная зависимость — уже используется в task_parser)
    try:
        import dateparser  # noqa: PLC0415

        result = dateparser.parse(
            raw,
            settings={
                "PREFER_DATES_FROM": "future",
                "RETURN_AS_TIMEZONE_AWARE": True,
            },
        )
        return result
    except Exception:  # noqa: BLE001
        return None


async def structure_task(
    text: str,
    *,
    roster: list[dict],
    now: datetime,
    tz: str,
) -> Optional[dict]:
    """Структурирует свободный текст задачи через OpenAI Chat Completions.

    Параметры:
        text    — свободный текст задачи.
        roster  — список сотрудников [{"id": int, "name": str, "username": str|None}].
        now     — текущее время (timezone-aware).
        tz      — строка часового пояса (например "Asia/Almaty").

    Возвращает dict с ключами:
        title, description, assignee_id, deadline_at (datetime|None),
        priority, needs_clarification, clarification.
    Возвращает None при отсутствии ключа, ошибке сети или таймауте.
    """
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None

    model = os.getenv("OPENAI_TASK_MODEL", "gpt-4o-mini")
    roster_ids = {int(e["id"]) for e in roster if e.get("id") is not None}

    roster_json = json.dumps(roster, ensure_ascii=False, indent=2)
    now_iso = now.isoformat()

    user_message = _USER_TEMPLATE.format(
        now_iso=now_iso,
        tz=tz,
        roster_json=roster_json,
        text=text,
    )

    payload = {
        "model": model,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "oyuns_task_draft",
                "strict": True,
                "schema": _TASK_RESPONSE_SCHEMA,
            },
        },
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.2,
    }

    timeout = aiohttp.ClientTimeout(total=30)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                OPENAI_CHAT_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            ) as resp:
                if resp.status != 200:
                    body = (await resp.text())[:300]
                    log.warning("OpenAI Chat API %s: %s", resp.status, body)
                    return None
                data = await resp.json()

        raw_content = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        result = parse_llm_json(raw_content, roster_ids)
        if result is None:
            log.warning("structure_task: не удалось распарсить ответ LLM: %r", raw_content[:300])
        return result

    except aiohttp.ClientConnectorError as exc:
        log.warning("structure_task: ошибка соединения: %s", exc)
        return None
    except Exception:  # noqa: BLE001 — не роняем процесс
        log.exception("structure_task: неожиданная ошибка")
        return None
