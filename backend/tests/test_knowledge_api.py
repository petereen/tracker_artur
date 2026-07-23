import pytest
from pydantic import ValidationError

from app.routers.knowledge import KnowledgeCreate, KnowledgeUpdate


def test_knowledge_create_strips_fields():
    entry = KnowledgeCreate(
        title="  Leave policy  ",
        category="  HR  ",
        content="  Approved policy text.  ",
    )
    assert entry.title == "Leave policy"
    assert entry.category == "HR"
    assert entry.content == "Approved policy text."
    assert entry.is_active is True


@pytest.mark.parametrize(
    "payload",
    [
        {"title": " ", "category": None, "content": "Content", "is_active": True},
        {"title": "Title", "category": None, "content": " ", "is_active": True},
        {"title": "Title", "category": None, "content": "x" * 20_001, "is_active": True},
    ],
)
def test_knowledge_rejects_invalid_content(payload):
    with pytest.raises(ValidationError):
        KnowledgeCreate.model_validate(payload)


def test_knowledge_put_requires_complete_representation():
    with pytest.raises(ValidationError):
        KnowledgeUpdate.model_validate({"is_active": False})
