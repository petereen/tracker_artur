"""Тесты для app.services.task_ai (без сети — только parse_llm_json и ai_enabled)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from app.services.task_ai import ai_enabled, parse_llm_json

# ---------------------------------------------------------------------------
# Вспомогательные данные
# ---------------------------------------------------------------------------

VALID_ROSTER_IDS = {1, 2, 3}

_VALID_PAYLOAD = {
    "title": "Подготовить отчёт",
    "description": "За прошлую неделю",
    "assignee_id": 2,
    "deadline_iso": "2030-06-01T12:00:00+05:00",
    "priority": 1,
    "needs_clarification": False,
    "clarification": None,
}


def _raw(overrides: dict | None = None) -> str:
    """Сериализует _VALID_PAYLOAD с опциональными overrides."""
    payload = {**_VALID_PAYLOAD, **(overrides or {})}
    return json.dumps(payload, ensure_ascii=False)


# ---------------------------------------------------------------------------
# parse_llm_json — валидный JSON
# ---------------------------------------------------------------------------


class TestParseValidJson:
    def test_returns_dict(self):
        result = parse_llm_json(_raw(), VALID_ROSTER_IDS)
        assert isinstance(result, dict)

    def test_title_preserved(self):
        result = parse_llm_json(_raw(), VALID_ROSTER_IDS)
        assert result["title"] == "Подготовить отчёт"

    def test_title_truncated_to_80(self):
        long_title = "А" * 100
        result = parse_llm_json(_raw({"title": long_title}), VALID_ROSTER_IDS)
        assert len(result["title"]) == 80

    def test_description_preserved(self):
        result = parse_llm_json(_raw(), VALID_ROSTER_IDS)
        assert result["description"] == "За прошлую неделю"

    def test_description_none_when_empty(self):
        result = parse_llm_json(_raw({"description": "   "}), VALID_ROSTER_IDS)
        assert result["description"] is None

    def test_description_none_when_not_string(self):
        result = parse_llm_json(_raw({"description": 42}), VALID_ROSTER_IDS)
        assert result["description"] is None

    def test_assignee_id_valid(self):
        result = parse_llm_json(_raw({"assignee_id": 3}), VALID_ROSTER_IDS)
        assert result["assignee_id"] == 3

    def test_needs_clarification_false(self):
        result = parse_llm_json(_raw(), VALID_ROSTER_IDS)
        assert result["needs_clarification"] is False

    def test_needs_clarification_true(self):
        result = parse_llm_json(
            _raw({"needs_clarification": True, "clarification": "Уточните срок"}),
            VALID_ROSTER_IDS,
        )
        assert result["needs_clarification"] is True
        assert result["clarification"] == "Уточните срок"

    def test_deadline_parsed_as_datetime(self):
        result = parse_llm_json(_raw(), VALID_ROSTER_IDS)
        assert isinstance(result["deadline_at"], datetime)

    def test_deadline_with_z_suffix(self):
        result = parse_llm_json(
            _raw({"deadline_iso": "2030-07-15T09:00:00Z"}), VALID_ROSTER_IDS
        )
        assert isinstance(result["deadline_at"], datetime)
        assert result["deadline_at"].tzinfo is not None


# ---------------------------------------------------------------------------
# parse_llm_json — assignee_id вне ростера → null
# ---------------------------------------------------------------------------


class TestAssigneeNotInRoster:
    def test_assignee_id_outside_roster_becomes_none(self):
        result = parse_llm_json(_raw({"assignee_id": 99}), VALID_ROSTER_IDS)
        assert result["assignee_id"] is None

    def test_assignee_id_zero_not_in_roster(self):
        result = parse_llm_json(_raw({"assignee_id": 0}), VALID_ROSTER_IDS)
        assert result["assignee_id"] is None

    def test_assignee_id_null_stays_null(self):
        result = parse_llm_json(_raw({"assignee_id": None}), VALID_ROSTER_IDS)
        assert result["assignee_id"] is None

    def test_assignee_id_string_becomes_none_if_invalid(self):
        # "abc" нельзя привести к int → None
        result = parse_llm_json(_raw({"assignee_id": "abc"}), VALID_ROSTER_IDS)
        assert result["assignee_id"] is None

    def test_assignee_id_string_int_in_roster(self):
        # LLM может вернуть id строкой — кастим и проверяем roster
        result = parse_llm_json(_raw({"assignee_id": "2"}), VALID_ROSTER_IDS)
        assert result["assignee_id"] == 2

    def test_empty_roster_ids_always_null(self):
        result = parse_llm_json(_raw({"assignee_id": 1}), set())
        assert result["assignee_id"] is None


# ---------------------------------------------------------------------------
# parse_llm_json — priority клампится в 1..3
# ---------------------------------------------------------------------------


class TestPriorityClamping:
    def test_priority_9_clamps_to_3(self):
        result = parse_llm_json(_raw({"priority": 9}), VALID_ROSTER_IDS)
        assert result["priority"] == 3

    def test_priority_0_clamps_to_1(self):
        result = parse_llm_json(_raw({"priority": 0}), VALID_ROSTER_IDS)
        assert result["priority"] == 1

    def test_priority_minus_1_clamps_to_1(self):
        result = parse_llm_json(_raw({"priority": -1}), VALID_ROSTER_IDS)
        assert result["priority"] == 1

    def test_priority_2_stays(self):
        result = parse_llm_json(_raw({"priority": 2}), VALID_ROSTER_IDS)
        assert result["priority"] == 2

    def test_priority_invalid_string_defaults_to_2(self):
        result = parse_llm_json(_raw({"priority": "high"}), VALID_ROSTER_IDS)
        assert result["priority"] == 2

    def test_priority_float_is_clamped(self):
        # 1.7 → int(1.7)=1 → valid
        result = parse_llm_json(_raw({"priority": 1.7}), VALID_ROSTER_IDS)
        assert result["priority"] == 1


# ---------------------------------------------------------------------------
# parse_llm_json — битый JSON → None
# ---------------------------------------------------------------------------


class TestBrokenJson:
    def test_broken_json_returns_none(self):
        assert parse_llm_json("не JSON вообще", VALID_ROSTER_IDS) is None

    def test_empty_string_returns_none(self):
        assert parse_llm_json("", VALID_ROSTER_IDS) is None

    def test_json_array_returns_none(self):
        # Ожидаем объект, а не массив
        assert parse_llm_json("[1, 2, 3]", VALID_ROSTER_IDS) is None

    def test_truncated_json_returns_none(self):
        assert parse_llm_json('{"title": "Задача"', VALID_ROSTER_IDS) is None

    def test_json_without_title_returns_none(self):
        # title обязателен
        payload = {k: v for k, v in _VALID_PAYLOAD.items() if k != "title"}
        assert parse_llm_json(json.dumps(payload), VALID_ROSTER_IDS) is None

    def test_json_with_empty_title_returns_none(self):
        assert parse_llm_json(_raw({"title": "   "}), VALID_ROSTER_IDS) is None


# ---------------------------------------------------------------------------
# parse_llm_json — deadline_iso невалидный → deadline None
# ---------------------------------------------------------------------------


class TestInvalidDeadline:
    def test_deadline_invalid_string_becomes_none(self):
        result = parse_llm_json(_raw({"deadline_iso": "не дата"}), VALID_ROSTER_IDS)
        assert result["deadline_at"] is None

    def test_deadline_null_becomes_none(self):
        result = parse_llm_json(_raw({"deadline_iso": None}), VALID_ROSTER_IDS)
        assert result["deadline_at"] is None

    def test_deadline_empty_string_becomes_none(self):
        result = parse_llm_json(_raw({"deadline_iso": ""}), VALID_ROSTER_IDS)
        assert result["deadline_at"] is None

    def test_deadline_number_becomes_none(self):
        result = parse_llm_json(_raw({"deadline_iso": 12345}), VALID_ROSTER_IDS)
        assert result["deadline_at"] is None


# ---------------------------------------------------------------------------
# ai_enabled() — False без OPENAI_API_KEY
# ---------------------------------------------------------------------------


class TestAiEnabled:
    def test_false_without_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        assert ai_enabled() is False

    def test_false_with_empty_key(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "")
        assert ai_enabled() is False

    def test_false_with_whitespace_key(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "   ")
        assert ai_enabled() is False

    def test_true_with_key(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
        assert ai_enabled() is True
