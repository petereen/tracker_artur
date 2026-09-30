from contextlib import asynccontextmanager

from app.observability.sentry import init_from_env

init_from_env(server_name="tracker-artur-api")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError
from starlette.requests import Request

from app.core.config import settings
from app.core.database import AsyncSessionLocal, engine
from app.core.security import hash_password
from app.core.tenancy import TENANT_FEATURES, TenantBoundaryViolation, install_tenant_guards
from app.core.tenant_middleware import TenantContextMiddleware
from app.models.models import AdminUser, ManagerSettings, Organization, RoleAssignment, UserAccount
from app.routers import ai_settings, assistant_learning, assistant_voice, auth, calls, chat, company_files, company_plans, contracts, dashboard, employees, enterprise, enterprise_auth, journal, knowledge, manager, mobile, mobile_updates, onboarding, platform, questions, realtime, report_insights, schedules, tasks, tenant, work_reports, worktime_qr, worktime_reports
from app.services.tenant_service import is_seat_limit_error
from app.erp import router as erp
from app import mcp_executor
from app.hr import router as hr_router
from sqlalchemy import func, or_, select, text

install_tenant_guards()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await seed_admin()
    async with AsyncSessionLocal() as db:
        await platform.seed_platform_operator(db)
    yield


def _repair_seeded_admin_account(account: UserAccount, password_hash: str) -> None:
    """Restore the configured seeded admin after stale credentials/lockouts."""
    account.password_hash = password_hash
    account.status = "active"
    account.failed_login_count = 0
    account.locked_until = None


async def seed_admin():
    async with AsyncSessionLocal() as db:
        admin_identifier = (settings.ADMIN_USERNAME or settings.ADMIN_EMAIL).strip().lower()
        result = await db.execute(select(AdminUser).where(func.lower(AdminUser.email) == admin_identifier))
        admin = result.scalar_one_or_none()
        if not admin:
            admin = AdminUser(email=admin_identifier, password_hash=hash_password(settings.ADMIN_PASSWORD))
            db.add(admin)
            await db.commit()
            await db.refresh(admin)
        else:
            # Keep the configured seeded credentials authoritative for the
            # legacy row as well as the enterprise account.
            admin.password_hash = hash_password(settings.ADMIN_PASSWORD)
        organization = await db.get(Organization, 1)
        if not organization:
            # A fresh install's first company is the primary tenant, exactly
            # like the one the multi-tenant migration backfills.
            organization = Organization(
                id=1, name="OYUNS", timezone="Asia/Ulaanbaatar", base_currency="MNT",
                slug="oyuns", is_primary=True, status="active", plan_code=None,
                features=sorted(TENANT_FEATURES), license_required=False,
                branding={"display_name": "OYUNS"},
            )
            db.add(organization)
            await db.flush()
            # An explicit id does not advance the sequence; keep the next
            # console-created tenant from colliding with this one.
            await db.execute(text("SELECT setval(pg_get_serial_sequence('organizations', 'id'), (SELECT max(id) FROM organizations))"))
            await db.commit()
        account = (
            await db.execute(
                select(UserAccount).where(
                    or_(
                        UserAccount.legacy_admin_id == admin.id,
                        func.lower(UserAccount.email) == admin.email.strip().lower(),
                    )
                )
            )
        ).scalar_one_or_none()
        if not account:
            account = UserAccount(
                organization_id=organization.id,
                legacy_admin_id=admin.id,
                email=admin.email.strip().lower(),
                password_hash=admin.password_hash,
                status="active",
                locale="mn",
            )
            db.add(account)
            await db.flush()
            db.add(RoleAssignment(account_id=account.id, role="admin"))
            await db.commit()
        else:
            if not account.legacy_admin_id:
                account.legacy_admin_id = admin.id
            # The configured ADMIN_* credentials are the recovery source of
            # truth for the seeded administrator. Existing accounts may have
            # been created before the username/password changed, or may have
            # been left in a temporary lockout after failed login attempts.
            _repair_seeded_admin_account(account, admin.password_hash)
            has_admin_role = await db.scalar(
                select(RoleAssignment.id).where(
                    RoleAssignment.account_id == account.id,
                    RoleAssignment.role == "admin",
                )
            )
            if not has_admin_role:
                db.add(RoleAssignment(account_id=account.id, role="admin"))
            await db.commit()
        result2 = await db.execute(select(ManagerSettings))
        if not result2.scalar_one_or_none():
            db.add(ManagerSettings())
            await db.commit()


app = FastAPI(title="OYUNS ERP — API", lifespan=lifespan)


@app.exception_handler(TenantBoundaryViolation)
async def tenant_boundary_violation(request: Request, exc: TenantBoundaryViolation):
    # A query reached another tenant's row: refuse instead of leaking. The
    # guard already logged the details for investigation.
    return JSONResponse(status_code=403, content={"detail": {"code": "tenant_boundary", "message": "Хандах эрхгүй өгөгдөл."}})


@app.exception_handler(DBAPIError)
async def database_error(request: Request, exc: DBAPIError):
    if is_seat_limit_error(exc):
        return JSONResponse(status_code=409, content={"detail": {"code": "seat_limit_reached", "message": "Лицензийн хэрэглэгчийн хязгаар дүүрсэн байна. Багцаа өргөтгөнө үү."}})
    raise exc


@app.middleware("http")
async def retire_legacy_payroll_api(request: Request, call_next):
    path = request.url.path
    if path.startswith("/v1/erp/payroll/") and not path.startswith("/v1/erp/payroll/monthly/") and path != "/v1/erp/payroll/capabilities":
        return JSONResponse(status_code=410, content={"detail": {"code": "payroll_workflow_retired", "message": "Хуучин цалингийн урсгал хаагдсан. Сарын цалингийн самбарыг ашиглана уу.", "monthly_path": "/v1/erp/payroll/monthly"}})
    return await call_next(request)

cors_origins = {
    origin.strip()
    for configured in (settings.CORS_ORIGINS, settings.NATIVE_APP_ORIGINS)
    for origin in configured.split(",")
    if origin.strip()
}

# Inside CORS so tenant denials still carry CORS headers for native apps.
app.add_middleware(TenantContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(employees.router, prefix="/employees", tags=["employees"])
app.include_router(questions.router, prefix="/questions", tags=["questions"])
app.include_router(schedules.router, prefix="/schedules", tags=["schedules"])
app.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
app.include_router(journal.router, prefix="/answers", tags=["answers"])
app.include_router(manager.router, prefix="/manager-settings", tags=["manager"])
app.include_router(onboarding.router, prefix="/onboarding", tags=["onboarding"])
app.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
app.include_router(tasks.miniapp_router, prefix="/miniapp", tags=["miniapp"])
app.include_router(work_reports.router, prefix="/work-reports", tags=["work-reports"])
app.include_router(worktime_reports.router, prefix="/v1/worktime-reports", tags=["v1-worktime-reports"])
app.include_router(report_insights.router, prefix="/v1/report-insights", tags=["v1-report-insights"])
app.include_router(company_plans.router, prefix="/company-plans", tags=["company-plans"])
app.include_router(knowledge.router, prefix="/knowledge", tags=["knowledge"])
app.include_router(assistant_learning.router, prefix="/assistant-learning", tags=["assistant-learning"])
app.include_router(enterprise_auth.router, prefix="/v1/auth", tags=["v1-auth"])
app.include_router(mobile.router, prefix="/v1/mobile", tags=["v1-mobile"])
app.include_router(mobile_updates.router, prefix="/v1/mobile-updates", tags=["v1-mobile-updates"])
app.include_router(realtime.router, prefix="/v1", tags=["v1-realtime"])
app.include_router(chat.router, prefix="/v1/chat", tags=["v1-chat"])
app.include_router(calls.router, prefix="/v1/calls", tags=["v1-calls"])
app.include_router(company_files.router, prefix="/v1/company-files", tags=["v1-company-files"])
app.include_router(contracts.router, prefix="/v1", tags=["v1-contracts"])
app.include_router(ai_settings.router, prefix="/v1/settings/ai-agent", tags=["v1-ai-settings"])
app.include_router(assistant_voice.router, prefix="/v1/assistant/voice", tags=["v1-assistant-voice"])
app.include_router(enterprise.router, prefix="/v1", tags=["v1-enterprise"])
app.include_router(worktime_qr.router, prefix="/v1/worktime-qr", tags=["v1-worktime-qr"])
app.include_router(erp.router, prefix="/v1/erp", tags=["v1-erp"])
app.include_router(hr_router, prefix="/v1/hr", tags=["v1-hr"])
app.include_router(mcp_executor.router, prefix="/v1/mcp-executor", tags=["v1-mcp-executor"])
app.include_router(tenant.router, prefix="/v1/tenant", tags=["v1-tenant"])
app.include_router(platform.router, prefix="/v1/platform", tags=["v1-platform"])


@app.get("/health")
async def health():
    return {"status": "ok"}
