import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.enterprise_deps import ActorContext
from app.main import app
from app.models.models import Base
from app.routers.company_files import _clean_name, _has_deleted_ancestor, _item_for_actor, browse_company_files


def actor(*roles: str, organization_id: int = 1) -> ActorContext:
    return ActorContext(account_id=1, organization_id=organization_id, employee_id=2, email="user@example.com", locale="mn", roles=frozenset(roles))


def test_company_file_schema_and_routes_are_registered():
    assert "company_library_items" in Base.metadata.tables
    paths = {route.path for route in app.routes}
    assert {
        "/v1/company-files",
        "/v1/company-files/folders",
        "/v1/company-files/upload",
        "/v1/company-files/{item_id}",
        "/v1/company-files/{item_id}/restore",
        "/v1/company-files/{item_id}/permanent",
        "/v1/company-files/{item_id}/download",
    }.issubset(paths)


def test_company_file_names_are_sanitized_and_invalid_names_rejected():
    assert _clean_name("../documents/report.pdf") == "report.pdf"
    for value in ("", "  ", ".", ".."):
        with pytest.raises(HTTPException) as exc:
            _clean_name(value)
        assert exc.value.status_code == 422


def test_deleted_or_missing_ancestors_hide_descendants():
    deleted = SimpleNamespace(id=1, parent_id=None, deleted_at=datetime.now(timezone.utc))
    child = SimpleNamespace(id=2, parent_id=1, deleted_at=None)
    grandchild = SimpleNamespace(id=3, parent_id=2, deleted_at=None)
    by_id = {1: deleted, 2: child, 3: grandchild}
    assert _has_deleted_ancestor(child, by_id)
    assert _has_deleted_ancestor(grandchild, by_id)
    assert not _has_deleted_ancestor(SimpleNamespace(id=4, parent_id=None, deleted_at=None), by_id)


def test_members_cannot_browse_trash():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(browse_company_files(parent_id=None, q=None, sort="name", trash=True, db=SimpleNamespace(), actor=actor("member")))
    assert exc.value.status_code == 403


def test_items_from_another_organization_are_not_visible():
    class FakeDb:
        async def get(self, *_args):
            return SimpleNamespace(id=7, organization_id=2)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(_item_for_actor(FakeDb(), 7, actor("admin", organization_id=1)))
    assert exc.value.status_code == 404
