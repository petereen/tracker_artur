import asyncio
from types import SimpleNamespace

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core import enterprise_deps
from app.core.database import get_db
from app.core.enterprise_deps import apply_workspace_mode, build_actor_context, get_actor, require_roles


def actor(*roles: str):
    return build_actor_context(account_id=1, organization_id=1, employee_id=2, email="m@example.test", locale="mn", roles=frozenset(roles))


def test_member_mode_narrows_management_roles_to_a_personal_scope():
    narrowed = apply_workspace_mode(actor("admin", "hr", "manager"), "member")
    assert narrowed.roles == frozenset({"member"})
    assert narrowed.granted_roles == frozenset({"admin", "hr", "manager"})
    assert narrowed.workspace_mode == "member"
    assert not narrowed.has_any_role("admin", "manager", "team_lead", "hr")


def test_manager_mode_and_unknown_values_keep_full_scope():
    full = actor("manager")
    assert apply_workspace_mode(full, "manager") is full
    assert apply_workspace_mode(full, None) is full
    assert apply_workspace_mode(full, "company") is full


def test_roles_without_a_mode_toggle_are_never_narrowed():
    hr = actor("hr")
    assert apply_workspace_mode(hr, "member") is hr
    member = actor("member")
    assert apply_workspace_mode(member, "member") is member


def test_header_drives_role_checks_but_not_the_mode_preference(monkeypatch):
    async def from_token(token, _db):
        return actor(token)

    monkeypatch.setattr(enterprise_deps, "actor_from_token", from_token)
    app = FastAPI()
    app.dependency_overrides[get_db] = lambda: None

    @app.get("/admin-only")
    async def admin_only(_actor=Depends(require_roles("admin"))):
        return {"ok": True}

    @app.get("/whoami")
    async def whoami(current=Depends(get_actor)):
        return {"roles": sorted(current.roles), "granted": sorted(current.granted_roles), "mode": current.workspace_mode}

    client = TestClient(app)
    admin = {"Authorization": "Bearer admin"}
    assert client.get("/admin-only", headers=admin).status_code == 200
    assert client.get("/admin-only", headers={**admin, "X-Workspace-Mode": "member"}).status_code == 403
    assert client.get("/whoami", headers={**admin, "X-Workspace-Mode": "member"}).json() == {"roles": ["member"], "granted": ["admin"], "mode": "member"}


def test_member_mode_manager_can_still_switch_back(monkeypatch):
    from app.routers import enterprise_auth

    saved = SimpleNamespace(preferences={"workspace_mode": {"mode": "member"}})

    class Db:
        async def get(self, *_args, **_kwargs):
            return saved

        async def commit(self):
            return None

    async def from_token(token, _db):
        return actor(token)

    monkeypatch.setattr(enterprise_deps, "actor_from_token", from_token)
    app = FastAPI()
    app.include_router(enterprise_auth.router, prefix="/v1/auth")
    app.dependency_overrides[get_db] = lambda: Db()
    client = TestClient(app)
    headers = {"Authorization": "Bearer manager", "X-Workspace-Mode": "member"}
    assert client.get("/v1/auth/preferences/workspace-mode", headers=headers).json() == {"mode": "member"}
    response = client.put("/v1/auth/preferences/workspace-mode", headers=headers, json={"mode": "manager"})
    assert response.status_code == 200 and saved.preferences["workspace_mode"] == {"mode": "manager"}
    member = {"Authorization": "Bearer member"}
    assert client.put("/v1/auth/preferences/workspace-mode", headers=member, json={"mode": "manager"}).status_code == 403


def test_me_reports_effective_and_granted_roles(monkeypatch):
    from app.routers.enterprise_auth import me

    class Db:
        async def get(self, *_args, **_kwargs):
            return SimpleNamespace(name="Болд", metadata_json={})

    narrowed = apply_workspace_mode(actor("admin"), "member")
    out = asyncio.run(me(db=Db(), actor=narrowed))
    assert out.roles == ["member"] and out.account_roles == ["admin"] and out.workspace_mode == "member"
