"""OYUNS ERP SaaS end to end against PostgreSQL with the real migrations.

Runs only when TENANCY_TEST_DATABASE_URL points at a *throwaway* database
(its ``public`` schema is dropped and rebuilt with ``alembic upgrade head``),
e.g. ``postgresql+asyncpg://tracker:tracker@127.0.0.1:5432/tenancy_test``.
If the user may create roles, the API runs as a non-superuser role so
row-level security is really enforced; otherwise RLS checks are skipped.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest

DATABASE_URL = os.environ.get("TENANCY_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TENANCY_TEST_DATABASE_URL is not set")

if DATABASE_URL:
    os.environ.setdefault("DATABASE_URL", DATABASE_URL)
    os.environ.setdefault("SYNC_DATABASE_URL", DATABASE_URL.replace("+asyncpg", "+psycopg2"))
    os.environ.setdefault("SECRET_KEY", "tenancy-test-secret-key-0123456789abcdef")

BACKEND = Path(__file__).resolve().parents[1]
APP_ROLE = "oyuns_tenancy_test_app"
APP_ROLE_PASSWORD = "tenancy-test-app"
ROOT_HOST = "app.oyunserp.test"


def _migrate_fresh_schema() -> None:
    from sqlalchemy import create_engine, text

    sync_url = DATABASE_URL.replace("+asyncpg", "+psycopg2")
    engine = create_engine(sync_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    env = {**os.environ, "DATABASE_URL": DATABASE_URL, "SYNC_DATABASE_URL": sync_url}
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, check=True, capture_output=True)


def _app_role_url() -> str | None:
    """Create a NOSUPERUSER NOBYPASSRLS role like production should use."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    engine = create_engine(DATABASE_URL.replace("+asyncpg", "+psycopg2"), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            exists = connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :name"), {"name": APP_ROLE}).scalar()
            if not exists:
                connection.execute(text(f"CREATE ROLE {APP_ROLE} LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD '{APP_ROLE_PASSWORD}'"))
            connection.execute(text(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}"))
            connection.execute(text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}"))
            connection.execute(text(f"GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}"))
            connection.execute(text(f"GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO {APP_ROLE}"))
    except Exception:
        return None
    finally:
        engine.dispose()
    return make_url(DATABASE_URL).set(username=APP_ROLE, password=APP_ROLE_PASSWORD).render_as_string(hide_password=False)


def test_operator_to_tenant_saas_lifecycle(monkeypatch):
    _migrate_fresh_schema()
    app_url = _app_role_url()
    asyncio.run(_scenario(monkeypatch, app_url))


async def _scenario(monkeypatch, app_url: str | None) -> None:
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import select, text
    from sqlalchemy.exc import DBAPIError
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core import tenancy
    from app.core.config import settings
    from app.core.database import get_db
    from app.core.security import hash_account_password
    from app.main import app
    from app.models import models as m
    from app.models.platform import PlatformOperator, TenantLicense
    from app.services import licensing

    private_pem, _ = licensing.generate_keypair()
    monkeypatch.setattr(settings, "LICENSE_SIGNING_PRIVATE_KEY", private_pem)
    monkeypatch.setattr(settings, "LICENSE_SIGNING_KEY_ID", "tenancy-test")
    monkeypatch.setattr(settings, "LICENSE_PUBLIC_KEYS", "")
    monkeypatch.setattr(settings, "TENANT_BASE_DOMAIN", "oyunserp.test")
    monkeypatch.setattr(settings, "PLATFORM_ROOT_HOSTS", ROOT_HOST)
    monkeypatch.setattr(settings, "PLATFORM_CONSOLE_HOSTS", "")
    monkeypatch.setattr(settings, "PLATFORM_ALLOWED_CIDRS", "")

    owner_engine = create_async_engine(DATABASE_URL)
    app_engine = create_async_engine(app_url) if app_url else owner_engine
    owner_sessions = async_sessionmaker(owner_engine, expire_on_commit=False)
    app_sessions = async_sessionmaker(app_engine, expire_on_commit=False)

    async def override_db():
        bound = tenancy.current_tenant_id()
        try:
            async with app_sessions() as session:
                yield session
        finally:
            tenancy.set_current_tenant(bound)

    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(tenancy.tenant_directory, "_session_factory", app_sessions)
    tenancy.tenant_directory.invalidate()
    tenancy.install_tenant_guards()

    # The migrations seed the pre-SaaS company (id 1) and turn it into the
    # grandfathered primary tenant; add its administrator.
    async with owner_sessions() as db:
        primary = await db.get(m.Organization, 1)
        assert primary.is_primary and primary.slug == "oyuns" and not primary.license_required
        assert "legacy_workspace" in primary.features and primary.seat_limit is None
        primary_admin = m.UserAccount(organization_id=1, email="owner@oyuns.test", password_hash=hash_account_password("owner-password-1"))
        db.add(primary_admin)
        await db.flush()
        db.add(m.RoleAssignment(account_id=primary_admin.id, role="admin"))
        db.add(PlatformOperator(email="ops@oyuns.test", role="superadmin", password_hash=hash_account_password("operator-password-1")))
        db.add(PlatformOperator(email="support@oyuns.test", role="support", password_hash=hash_account_password("support-password-1")))
        await db.commit()
        primary_admin_id = primary_admin.id

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url=f"http://{ROOT_HOST}") as client:
            async def login(email: str, password: str, host: str = ROOT_HOST):
                return await client.post("/v1/auth/login", json={"email": email, "password": password}, headers={"host": host, "origin": "capacitor://localhost"})

            def bearer(token: str, host: str = ROOT_HOST) -> dict:
                return {"Authorization": f"Bearer {token}", "host": host}

            # ── operator console ────────────────────────────────────────────
            operator_login = await client.post("/v1/platform/auth/login", json={"email": "ops@oyuns.test", "password": "operator-password-1"})
            assert operator_login.status_code == 200, operator_login.text
            ops = {"Authorization": f"Bearer {operator_login.json()['access_token']}"}
            support_login = await client.post("/v1/platform/auth/login", json={"email": "support@oyuns.test", "password": "support-password-1"})
            support = {"Authorization": f"Bearer {support_login.json()['access_token']}"}

            plans = (await client.get("/v1/platform/plans", headers=ops)).json()
            assert [plan["code"] for plan in plans] == ["starter", "professional", "enterprise"]
            assert (await client.post("/v1/platform/tenants", headers=support, json={})).status_code in {403, 422}

            created = await client.post("/v1/platform/tenants", headers=ops, json={
                "name": "Acme LLC", "slug": "acme", "plan_code": "professional", "seat_limit": 3,
                "admin": {"email": "admin@acme.test", "password": "acme-admin-pass-1"},
                "license": {"seat_limit": 3, "duration_months": 12},
                "branding": {"primary_color": "#123456"},
            })
            assert created.status_code == 201, created.text
            tenant = created.json()["tenant"]
            assert tenant["status"] == "pending_activation" and tenant["seats_used"] == 1
            assert tenant["features"] == ["ai_assistant", "budget", "contracts", "crm"]
            acme_id = tenant["id"]
            license_token = created.json()["license"]["token"]

            # ── tenant admin: license required until activation ────────────
            acme_login = await login("admin@acme.test", "acme-admin-pass-1")
            assert acme_login.status_code == 200, acme_login.text
            acme = acme_login.json()["access_token"]
            blocked = await client.get("/v1/settings/permissions", headers=bearer(acme))
            assert blocked.status_code == 402 and blocked.json()["detail"]["code"] == "license_required"
            context = (await client.get("/v1/tenant/context", headers=bearer(acme))).json()
            assert context["license"]["state"] == "missing" and context["seats"] == {"used": 1, "limit": 3, "available": 2, "unlimited": False}

            wrong = await client.post("/v1/tenant/license/verify", headers=bearer(acme), json={"token": license_token[:-4] + "AAAA"})
            assert wrong.status_code == 422 and wrong.json()["detail"]["code"] == "bad_signature"
            preview = await client.post("/v1/tenant/license/verify", headers=bearer(acme), json={"token": license_token})
            assert preview.status_code == 200 and preview.json()["claims"]["seats"] == 3
            activated = await client.post("/v1/tenant/license/activate", headers=bearer(acme), json={"token": license_token})
            assert activated.status_code == 200, activated.text
            assert activated.json()["active"]["status"] == "active"
            assert (await client.get("/v1/settings/permissions", headers=bearer(acme))).status_code == 200

            # A token for another tenant never activates here.
            primary_ops_license = await client.post("/v1/platform/tenants/1/licenses", headers=ops, json={"seat_limit": 50})
            assert primary_ops_license.status_code == 201
            foreign = await client.post("/v1/tenant/license/activate", headers=bearer(acme), json={"token": primary_ops_license.json()["token"]})
            assert foreign.status_code == 422 and foreign.json()["detail"]["code"] == "tenant_mismatch"

            # ── seats ───────────────────────────────────────────────────────
            async def add_user(email: str):
                return await client.post("/v1/auth/accounts", headers=bearer(acme), json={"email": email, "password": "member-password-1", "roles": ["member"]})

            first = await add_user("one@acme.test")
            assert first.status_code == 201, first.text
            assert (await add_user("two@acme.test")).status_code == 201
            full = await add_user("three@acme.test")
            assert full.status_code == 409 and full.json()["detail"]["code"] == "seat_limit_reached"
            assert full.json()["detail"]["used"] == 3 and full.json()["detail"]["limit"] == 3
            duplicate = await client.post("/v1/auth/accounts", headers=bearer(acme), json={"email": "owner@oyuns.test", "password": "member-password-1", "roles": ["member"]})
            assert duplicate.status_code == 409  # logins are unique platform-wide, even under RLS
            disabled = await client.patch(f"/v1/auth/accounts/{first.json()['id']}", headers=bearer(acme), json={"status": "disabled"})
            assert disabled.status_code == 200
            assert (await add_user("three@acme.test")).status_code == 201
            reenable = await client.patch(f"/v1/auth/accounts/{first.json()['id']}", headers=bearer(acme), json={"status": "active"})
            assert reenable.status_code == 409 and reenable.json()["detail"]["code"] == "seat_limit_reached"

            # The database trigger is the backstop for any code path.
            async with app_sessions() as db:
                with tenancy.tenant_scope(acme_id):
                    with pytest.raises(DBAPIError) as trigger:
                        db.add(m.UserAccount(organization_id=acme_id, email="raw@acme.test", password_hash="x"))
                        await db.commit()
                    assert "seat_limit_exceeded" in str(trigger.value)
                    await db.rollback()

            # ── isolation ───────────────────────────────────────────────────
            accounts = (await client.get("/v1/auth/accounts", headers=bearer(acme))).json()
            assert {row["email"] for row in accounts} == {"admin@acme.test", "one@acme.test", "two@acme.test", "three@acme.test"}
            owner = (await login("owner@oyuns.test", "owner-password-1")).json()["access_token"]
            owner_accounts = (await client.get("/v1/auth/accounts", headers=bearer(owner))).json()
            assert {row["email"] for row in owner_accounts} == {"owner@oyuns.test"}

            mismatch = await client.get("/v1/settings/permissions", headers=bearer(owner, host="acme.oyunserp.test"))
            assert mismatch.status_code == 403 and mismatch.json()["detail"]["code"] == "tenant_mismatch"
            assert (await client.get("/v1/settings/permissions", headers=bearer(acme, host="acme.oyunserp.test"))).status_code == 200
            assert (await login("owner@oyuns.test", "owner-password-1", host="acme.oyunserp.test")).status_code == 401
            assert (await client.get("/v1/tenant/branding", headers={"host": "nope.oyunserp.test"})).status_code == 404
            assert (await client.get("/v1/tenant/branding", headers={"host": "acme.oyunserp.test"})).json()["primary_color"] == "#123456"

            gated = await client.get("/v1/erp/payroll/monthly", headers=bearer(acme))
            assert gated.status_code == 403 and gated.json()["detail"]["code"] == "feature_not_licensed"
            assert (await client.get("/questions", headers=bearer(acme))).json()["detail"]["code"] == "feature_not_licensed"
            assert (await client.get("/v1/platform/tenants", headers=bearer(acme))).status_code == 401
            assert (await client.get("/v1/platform/tenants", headers={**ops, "host": "acme.oyunserp.test"})).status_code == 404

            async with app_sessions() as db:
                with tenancy.tenant_scope(acme_id):
                    try:
                        leaked = await db.get(m.UserAccount, primary_admin_id)
                    except tenancy.TenantBoundaryViolation:
                        leaked = None  # superuser connection: the ORM guard caught it
                    assert leaked is None
                    if app_url:
                        # RLS filters even raw SQL that forgets the tenant.
                        visible = await db.scalar(text("SELECT count(*) FROM user_accounts"))
                        assert visible == 4
                        orgs = (await db.execute(text("SELECT id FROM organizations"))).scalars().all()
                        assert orgs == [acme_id]
                        with pytest.raises(DBAPIError):
                            await db.execute(text("INSERT INTO employees (organization_id, name) VALUES (1, 'Cross-tenant')"))
                        await db.rollback()

            # ── branding by the tenant admin ────────────────────────────────
            branded = await client.put("/v1/tenant/branding/settings", headers=bearer(acme), json={"display_name": "Acme ERP", "secondary_color": "#ABCDEF", "logo_url": "javascript:alert(1)"})
            assert branded.status_code == 422
            branded = await client.put("/v1/tenant/branding/settings", headers=bearer(acme), json={"display_name": "Acme ERP", "secondary_color": "#ABCDEF"})
            assert branded.status_code == 200 and branded.json()["preview"]["name"] == "Acme ERP"
            assert branded.json()["preview"]["secondary_color"] == "#abcdef"

            # ── operator lifecycle: suspend, reactivate, upgrade, revoke ────
            assert (await client.post(f"/v1/platform/tenants/{acme_id}/suspend", headers=ops, json={"reason": "invoice overdue"})).status_code == 200
            suspended = await client.get("/v1/settings/permissions", headers=bearer(acme))
            assert suspended.status_code == 403 and suspended.json()["detail"]["code"] == "tenant_suspended"
            assert (await login("admin@acme.test", "acme-admin-pass-1")).status_code == 403
            assert (await client.post(f"/v1/platform/tenants/{acme_id}/reactivate", headers=ops, json={})).json()["status"] == "active"
            acme = (await login("admin@acme.test", "acme-admin-pass-1")).json()["access_token"]

            detail = (await client.get(f"/v1/platform/tenants/{acme_id}", headers=ops)).json()
            active_license = next(row for row in detail["licenses"] if row["status"] == "active")
            upgraded = await client.post(f"/v1/platform/licenses/{active_license['id']}/renew", headers=ops, json={"seat_limit": 5, "activate": True})
            assert upgraded.status_code == 201, upgraded.text
            assert (await client.get("/v1/tenant/seats", headers=bearer(acme))).json()["limit"] == 5
            assert (await client.patch(f"/v1/auth/accounts/{first.json()['id']}", headers=bearer(acme), json={"status": "active"})).status_code == 200
            async with owner_sessions() as db:
                statuses = dict((await db.execute(select(TenantLicense.public_id, TenantLicense.status).where(TenantLicense.organization_id == acme_id))).all())
            assert sorted(statuses.values()) == ["active", "superseded"]

            revoked = await client.post(f"/v1/platform/licenses/{upgraded.json()['id']}/revoke", headers=ops, json={"reason": "chargeback"})
            assert revoked.status_code == 200 and revoked.json()["status"] == "revoked"
            assert (await client.get("/v1/settings/permissions", headers=bearer(acme))).status_code == 402
            reuse = await client.post("/v1/tenant/license/activate", headers=bearer(acme), json={"token": upgraded.json()["token"]})
            assert reuse.status_code == 422 and reuse.json()["detail"]["code"] == "revoked"

            system = (await client.get("/v1/platform/system", headers=ops)).json()
            assert system["license_signing"]["available"] is True
            assert system["rls"]["protected_tables"] == system["rls"]["tenant_tables"]
            assert system["rls"]["effective"] is bool(app_url)
            audit_actions = {row["action"] for row in (await client.get(f"/v1/platform/audit?tenant_id={acme_id}", headers=ops)).json()}
            assert {"tenant.created", "license.issued", "license.activated", "tenant.suspended", "license.revoked"} <= audit_actions

            # ── termination ────────────────────────────────────────────────
            refused = await client.post(f"/v1/platform/tenants/{acme_id}/terminate", headers=ops, json={"reason": "contract ended", "confirm_slug": "wrong"})
            assert refused.status_code == 422
            terminated = await client.post(f"/v1/platform/tenants/{acme_id}/terminate", headers=ops, json={"reason": "contract ended", "confirm_slug": "acme"})
            assert terminated.status_code == 200 and terminated.json()["status"] == "terminated"
            assert (await login("admin@acme.test", "acme-admin-pass-1")).status_code == 401
            assert (await client.post("/v1/platform/tenants/1/terminate", headers=ops, json={"reason": "not allowed", "confirm_slug": "oyuns"})).status_code == 409
    finally:
        app.dependency_overrides.pop(get_db, None)
        tenancy.tenant_directory._session_factory = None
        tenancy.tenant_directory.invalidate()
        await app_engine.dispose()
        if app_engine is not owner_engine:
            await owner_engine.dispose()
