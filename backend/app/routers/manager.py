from datetime import time
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.tenancy import current_tenant_id, tenant_directory
from app.models.models import Department, Employee, EmployeeDetails, ManagerSettings, RoleAssignment, UserAccount
from app.services.manager_recipients import manager_settings_for


def _parse_time(v: str | None) -> time | None:
    if not v:
        return None
    parts = v.split(":")
    return time(int(parts[0]), int(parts[1]))

router = APIRouter()

# Shown next to a recipient when the worker has no job title.
ROLE_LABELS = {
    "admin": "Админ", "manager": "Менежер", "team_lead": "Багийн ахлагч", "hr": "Хүний нөөц",
    "legal_counsel": "Хуульч", "member": "Ажилтан", "contractor": "Гэрээт", "client_auditor": "Аудитор",
}
ROLE_ORDER = tuple(ROLE_LABELS)


class ManagerSettingsOut(BaseModel):
    telegram_id: Optional[str]
    telegram_username: Optional[str]
    telegram_admin_ids: list[str]
    summary_time: Optional[str]
    weekly_summary_time: Optional[str]
    weekly_summary_day: int
    alerts_enabled: bool
    gamification_enabled: bool
    soft_mode_weeks: int
    tts_answers_enabled: bool
    daily_report_reminders_enabled: bool

    model_config = {"from_attributes": True}

    # The manager_settings singleton was partly seeded (only telegram_id set),
    # so these required columns — which had only client-side defaults and no
    # server_default — could be NULL and crash serialization (same class as
    # Sentry #28). Coerce to the model defaults defensively.
    @field_validator("weekly_summary_day", mode="before")
    @classmethod
    def _default_weekly_summary_day(cls, v):
        return 5 if v is None else v

    @field_validator("alerts_enabled", "gamification_enabled", mode="before")
    @classmethod
    def _default_flags(cls, v):
        return True if v is None else v

    @field_validator("soft_mode_weeks", mode="before")
    @classmethod
    def _default_soft_mode_weeks(cls, v):
        return 1 if v is None else v

    @field_validator("tts_answers_enabled", "daily_report_reminders_enabled", mode="before")
    @classmethod
    def _default_tts_answers_enabled(cls, v):
        return True if v is None else v


class ManagerSettingsUpdate(BaseModel):
    telegram_id: Optional[str] = None
    telegram_username: Optional[str] = None
    telegram_admin_ids: Optional[list[str]] = None
    summary_time: Optional[str] = None
    weekly_summary_time: Optional[str] = None
    weekly_summary_day: Optional[int] = None
    alerts_enabled: Optional[bool] = None
    gamification_enabled: Optional[bool] = None
    soft_mode_weeks: Optional[int] = None
    tts_answers_enabled: Optional[bool] = None
    daily_report_reminders_enabled: Optional[bool] = None


class RecipientOption(BaseModel):
    employee_id: int
    name: str
    telegram_id: str
    telegram_username: Optional[str]
    job_title: Optional[str]
    department: Optional[str]
    role: Optional[str]


async def _organization_id() -> int:
    """Settings belong to the caller's tenant (legacy admin tokens: primary)."""
    organization_id = current_tenant_id() or await tenant_directory.primary_id()
    if organization_id is None:
        raise HTTPException(status_code=503, detail="Organization setup is incomplete")
    return organization_id


async def _settings_row(db: AsyncSession, organization_id: int) -> ManagerSettings:
    s = await manager_settings_for(db, organization_id)
    if s is None:
        s = ManagerSettings(organization_id=organization_id)
        db.add(s)
    return s


@router.get("", response_model=ManagerSettingsOut)
async def get_settings(db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    organization_id = await _organization_id()
    s = await manager_settings_for(db, organization_id)
    if not s:
        s = await _settings_row(db, organization_id)
        await db.commit()
        await db.refresh(s)
    return _settings_out(s)


@router.get("/recipient-options", response_model=list[RecipientOption])
async def recipient_options(db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    """Workers of this tenant with a connected Telegram account."""
    organization_id = await _organization_id()
    rows = (await db.execute(
        select(Employee, EmployeeDetails, Department)
        .outerjoin(EmployeeDetails, EmployeeDetails.employee_id == Employee.id)
        .outerjoin(Department, Department.id == EmployeeDetails.department_id)
        .where(
            Employee.organization_id == organization_id,
            Employee.telegram_id.is_not(None),
            Employee.telegram_id != "",
            Employee.is_active.is_(True),
            Employee.deleted_at.is_(None),
        )
        .order_by(Employee.name)
    )).all()
    employee_ids = [employee.id for employee, _, _ in rows]
    roles: dict[int, set[str]] = {}
    if employee_ids:
        for employee_id, role in (await db.execute(
            select(UserAccount.employee_id, RoleAssignment.role)
            .join(RoleAssignment, RoleAssignment.account_id == UserAccount.id)
            .where(UserAccount.organization_id == organization_id, UserAccount.employee_id.in_(employee_ids))
        )).all():
            roles.setdefault(employee_id, set()).add(role)
    options = []
    for employee, details, department in rows:
        granted = roles.get(employee.id, set())
        top_role = next((role for role in ROLE_ORDER if role in granted), None)
        options.append(RecipientOption(
            employee_id=employee.id,
            name=employee.name,
            telegram_id=str(employee.telegram_id),
            telegram_username=employee.telegram_username,
            job_title=(details.job_title if details and details.job_title else None) or employee.job_title,
            department=department.name if department else None,
            role=ROLE_LABELS.get(top_role) if top_role else None,
        ))
    return options


def _telegram_admin_ids(s: ManagerSettings) -> list[str]:
    """Normalize legacy and new recipients into unique, numeric Telegram IDs."""
    values = list(s.telegram_admin_ids or [])
    if s.telegram_id:
        values.insert(0, s.telegram_id)
    ids: list[str] = []
    for value in values:
        value = str(value).strip()
        if value and value not in ids:
            ids.append(value)
    return ids


def _settings_out(s: ManagerSettings) -> ManagerSettingsOut:
    return ManagerSettingsOut(
        telegram_id=s.telegram_id,
        telegram_username=s.telegram_username,
        telegram_admin_ids=_telegram_admin_ids(s),
        summary_time=str(s.summary_time) if s.summary_time else None,
        weekly_summary_time=str(s.weekly_summary_time) if s.weekly_summary_time else None,
        weekly_summary_day=s.weekly_summary_day,
        alerts_enabled=s.alerts_enabled,
        gamification_enabled=s.gamification_enabled,
        soft_mode_weeks=s.soft_mode_weeks,
        tts_answers_enabled=s.tts_answers_enabled,
        daily_report_reminders_enabled=s.daily_report_reminders_enabled if s.daily_report_reminders_enabled is not None else True,
    )


@router.put("", response_model=ManagerSettingsOut)
async def update_settings(data: ManagerSettingsUpdate, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    s = await _settings_row(db, await _organization_id())
    updates = data.model_dump(exclude_none=True)
    if "telegram_admin_ids" in updates:
        ids: list[str] = []
        for value in updates["telegram_admin_ids"]:
            value = str(value).strip()
            if not value:
                continue
            # Recipients are numeric Telegram user IDs; usernames cannot be
            # messaged by a bot and are no longer accepted.
            if not value.isdigit():
                raise HTTPException(status_code=422, detail={"code": "telegram_id_invalid", "message": f"Telegram ID зөвхөн тооноос бүрдэнэ: {value}"})
            if value not in ids:
                ids.append(value)
        updates["telegram_admin_ids"] = ids
        # Preserve compatibility with existing bot configuration and API clients.
        updates["telegram_id"] = ids[0] if ids else None
        updates["telegram_username"] = None
    if "summary_time" in updates:
        updates["summary_time"] = _parse_time(updates["summary_time"])
    if "weekly_summary_time" in updates:
        updates["weekly_summary_time"] = _parse_time(updates["weekly_summary_time"])
    if "weekly_summary_day" in updates:
        updates["weekly_summary_day"] = int(updates["weekly_summary_day"])
    for k, v in updates.items():
        setattr(s, k, v)
    await db.commit()
    await db.refresh(s)
    return _settings_out(s)
