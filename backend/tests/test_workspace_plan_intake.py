import pytest
from pydantic import ValidationError

from app.routers.enterprise import EnterpriseTaskInput
from app.services.work_report_service import plan_idea_fields


def test_task_priority_accepts_bot_priority_scale_only():
    assert EnterpriseTaskInput(title="Хийх ажил", priority=1).priority == 1
    assert EnterpriseTaskInput(title="Хийх ажил", priority=3).priority == 3
    with pytest.raises(ValidationError):
        EnterpriseTaskInput(title="Хийх ажил", priority=4)


def test_telegram_plan_text_uses_first_non_empty_line_as_title():
    assert plan_idea_fields("\n  Шинэ борлуулалт  \nЭхний алхам\nХоёр дахь алхам") == (
        "Шинэ борлуулалт",
        "Эхний алхам\nХоёр дахь алхам",
    )


def test_empty_telegram_plan_does_not_create_an_idea():
    assert plan_idea_fields(" \n ") is None
