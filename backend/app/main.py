from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.database import AsyncSessionLocal, engine
from app.core.security import hash_password
from app.models.models import AdminUser, ManagerSettings
from app.routers import auth, dashboard, employees, journal, manager, onboarding, questions, schedules, tasks
from sqlalchemy import select


@asynccontextmanager
async def lifespan(app: FastAPI):
    await seed_admin()
    yield


async def seed_admin():
    from app.core.config import settings
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(AdminUser).where(AdminUser.email == settings.ADMIN_EMAIL))
        if not result.scalar_one_or_none():
            db.add(AdminUser(email=settings.ADMIN_EMAIL, password_hash=hash_password(settings.ADMIN_PASSWORD)))
            await db.commit()
        result2 = await db.execute(select(ManagerSettings))
        if not result2.scalar_one_or_none():
            db.add(ManagerSettings())
            await db.commit()


app = FastAPI(title="Sales Tracker API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://artur.adarasoft.com"],
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


@app.get("/health")
async def health():
    return {"status": "ok"}
