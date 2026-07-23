import pytest
from pydantic import ValidationError

from app.routers.assistant_learning import PromoteUnknownRequest, UnknownRequestStatusUpdate


def test_unknown_request_status_is_constrained():
    assert UnknownRequestStatusUpdate(status="reviewed").status == "reviewed"
    with pytest.raises(ValidationError):
        UnknownRequestStatusUpdate(status="anything")


def test_promoted_knowledge_requires_title_and_content():
    with pytest.raises(ValidationError):
        PromoteUnknownRequest(title="", content="answer")
    with pytest.raises(ValidationError):
        PromoteUnknownRequest(title="Title", content="")
