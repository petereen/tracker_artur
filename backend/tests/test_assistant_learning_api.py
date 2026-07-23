import pytest
from pydantic import ValidationError

from app.routers.assistant_learning import (
    ContextExampleCreate,
    PromoteUnknownRequest,
    PromoteUnknownToContext,
    UnknownRequestStatusUpdate,
)


def test_unknown_request_status_is_constrained():
    assert UnknownRequestStatusUpdate(status="reviewed").status == "reviewed"
    with pytest.raises(ValidationError):
        UnknownRequestStatusUpdate(status="anything")


def test_promoted_knowledge_requires_title_and_content():
    with pytest.raises(ValidationError):
        PromoteUnknownRequest(title="", content="answer")
    with pytest.raises(ValidationError):
        PromoteUnknownRequest(title="Title", content="")


def test_context_dictionary_entry_requires_clean_phrase_and_meaning():
    entry = ContextExampleCreate(
        phrase="  бүгдээрээ   цугламаар байна ",
        intent="create_task_draft",
        meaning="Бүх ажилтанд уулзалтын даалгаврын ноорог бэлтгэ.",
    )
    assert entry.phrase == "бүгдээрээ цугламаар байна"
    with pytest.raises(ValidationError):
        ContextExampleCreate(phrase="   ", intent="create_task_draft", meaning="test")


def test_unknown_phrase_can_be_promoted_without_retyping_it():
    data = PromoteUnknownToContext(
        intent="create_task_draft",
        meaning="Бүх ажилтанд уулзалтын даалгаврын ноорог бэлтгэ.",
    )
    assert data.phrase is None
