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
_CYRILLIC_RE = re.compile(r"[а-яёъыэ]", re.I)
_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
STOP_WORDS = frozenset("a an and are can do for how i in is me my of on the to what with в для и как мне мой моя о по что это ба би бол миний надад нь тухай юу ямар яаж".split())


def detect_language(text: str) -> AssistantLanguage:
    if _MN_HINT_RE.search(text or "") or _MN_LATIN_HINT_RE.search(text or ""):
        return AssistantLanguage.MN
    if _CYRILLIC_RE.search(text or ""):
        return AssistantLanguage.RU
    return AssistantLanguage.EN if re.search(r"[A-Za-z]", text or "") else AssistantLanguage.MN


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
