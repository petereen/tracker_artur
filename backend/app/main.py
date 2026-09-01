from contextlib import asynccontextmanager

from app.observability.sentry import init_from_env

init_from_env(server_name="tracker-artur-api")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import AsyncSessionLocal, engine
from app.core.security import hash_password
from app.models.models import AdminUser, ManagerSettings, Organization, RoleAssignment, UserAccount
from app.routers import assistant_learning, auth, calls, chat, company_files, company_plans, contracts, dashboard, employees, enterprise, enterprise_auth, journal, knowledge, manager, mobile, mobile_updates, onboarding, questions, realtime, schedules, tasks, work_reports, worktime_qr, worktime_reports
from app.erp import router as erp
from app import mcp_executor
from app.hr import router as hr_router
from sqlalchemy import func, or_, select


@asynccontextmanager
async def lifespan(app: FastAPI):
    await seed_admin()
    yield


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
        organization = await db.get(Organization, 1)
        if not organization:
            organization = Organization(id=1, name="OYUNS", timezone="Asia/Ulaanbaatar", base_currency="MNT")
            db.add(organization)
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


app = FastAPI(title="OYUNS Agent — API", lifespan=lifespan)

cors_origins = {
    origin.strip()
    for configured in (settings.CORS_ORIGINS, settings.NATIVE_APP_ORIGINS)
    for origin in configured.split(",")
    if origin.strip()
}

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
app.include_router(enterprise.router, prefix="/v1", tags=["v1-enterprise"])
app.include_router(worktime_qr.router, prefix="/v1/worktime-qr", tags=["v1-worktime-qr"])
app.include_router(erp.router, prefix="/v1/erp", tags=["v1-erp"])
app.include_router(hr_router, prefix="/v1/hr", tags=["v1-hr"])
app.include_router(mcp_executor.router, prefix="/v1/mcp-executor", tags=["v1-mcp-executor"])


@app.get("/health")
async def health():
    return {"status": "ok"}
