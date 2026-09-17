"""Shared language and Unicode query helpers for assistant transports."""
from __future__ import annotations

import re
from enum import Enum
from typing import Iterable


class AssistantLanguage(str, Enum):
    MN = "mn"
    RU = "ru"
    EN = "en"


_MN_HINT_RE = re.compile(r"[өүңһ]", re.I)
_MN_LATIN_HINT_RE = re.compile(r"\b(?:sain|baina|uu|minii|daalgavar|hural|margaash|bayarlalaa)\b", re.I)
# Most Mongolian Cyrillic letters overlap with Russian.  The four letters
# above are useful signals, but they are not present in common messages such
# as “Сайн байна уу” or “Маргааш хурал”.  Prefer high-signal workplace and
# conversational words before falling back to script detection.
_MN_WORD_HINT_RE = re.compile(
    r"\b(?:сайн|байна|маргааш|өнөөдөр|өнөөдрийн|миний|надад|даалгавар|даалгаврын|"
    r"ажил|ажилтан|ажилтнууд|хурал|уулзалт|тайлан|компанийн|хэрхэн|яаж|юу|"
    r"ямар|хаана|хэзээ|яагаад|туслаач|харуул|өгөөч|үүсгэ|үүсгэх|бүгд|би|та|"
    r"хэрэгтэй|болно|засах|цагт|цагаас)\b",
    re.I,
)
_RU_WORD_HINT_RE = re.compile(
    r"\b(?:привет|здравствуй(?:те)?|покажи|показать|мои|моя|мои|задач(?:а|и|у|ей)|"
    r"сотрудник(?:и|ов|ам)?|работник(?:и|ов|ам)?|назначенн(?:ая|ые|ую)|создай|"
    r"сегодня|завтра|когда|почему|как|что|где|спасибо|пожалуйста)\b",
    re.I,
)
_CYRILLIC_RE = re.compile(r"[а-яёъыэ]", re.I)
_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
STOP_WORDS = frozenset("a an and are can do for how i in is me my of on the to what with в для и как мне мой моя о по что это ба би бол миний надад нь тухай юу ямар яаж".split())


def detect_language(text: str) -> AssistantLanguage:
    value = text or ""
    if _MN_HINT_RE.search(value) or _MN_LATIN_HINT_RE.search(value) or _MN_WORD_HINT_RE.search(value):
        return AssistantLanguage.MN
    if _RU_WORD_HINT_RE.search(value):
        return AssistantLanguage.RU
    if _CYRILLIC_RE.search(value):
        # Mongolian is the product's default language; ambiguous Cyrillic is
        # safer as Mongolian than silently replying in Russian.
        return AssistantLanguage.MN
    return AssistantLanguage.EN if re.search(r"[A-Za-z]", value) else AssistantLanguage.MN


def tokenize_search_terms(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        for token in _WORD_RE.findall((value or "").casefold()):
            if len(token) < 2 or token in STOP_WORDS or token in seen:
                continue
            seen.add(token)
            result.append(token)
            if len(result) >= 24:
                return result
    return result
