import pytest
from pydantic import ValidationError

from fastapi import HTTPException

from app.core.enterprise_deps import build_actor_context
from app.routers.knowledge import KnowledgeCreate, KnowledgeUpdate, _can_manage_knowledge, _safe_attachment_filename


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


def test_knowledge_attachment_filename_is_sanitized_and_allowed():
    filename, extension = _safe_attachment_filename("../brand/logo.svg")
    assert filename == "logo.svg"
    assert extension == ".svg"


def test_knowledge_attachment_rejects_unsupported_file_type():
    with pytest.raises(HTTPException) as exc:
        _safe_attachment_filename("unsafe.exe")
    assert exc.value.status_code == 415


def test_company_knowledge_reader_access_is_read_only_for_members():
    member = build_actor_context(
        account_id=7,
        organization_id=1,
        employee_id=7,
        email="member@example.com",
        locale="mn",
        roles=frozenset({"member"}),
    )
    admin = build_actor_context(
        account_id=8,
        organization_id=1,
        employee_id=8,
        email="admin@example.com",
        locale="mn",
        roles=frozenset({"admin"}),
    )
    assert _can_manage_knowledge(member) is False
    assert _can_manage_knowledge(admin) is True
