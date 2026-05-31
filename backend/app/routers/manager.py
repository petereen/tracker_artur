from datetime import time
from typing import Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import ManagerSettings


def _parse_time(v: str | None) -> time | None:
    if not v:
        return None
    parts = v.split(":")
    return time(int(parts[0]), int(parts[1]))

router = APIRouter()


class ManagerSettingsOut(BaseModel):
    telegram_id: Optional[str]
    telegram_username: Optional[str]
    summary_time: Optional[str]
    weekly_summary_time: Optional[str]
    weekly_summary_day: int
    alerts_enabled: bool
    gamification_enabled: bool
    soft_mode_weeks: int

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


class ManagerSettingsUpdate(BaseModel):
    telegram_id: Optional[str] = None
    telegram_username: Optional[str] = None
    summary_time: Optional[str] = None
    weekly_summary_time: Optional[str] = None
    weekly_summary_day: Optional[int] = None
    alerts_enabled: Optional[bool] = None
    gamification_enabled: Optional[bool] = None
    soft_mode_weeks: Optional[int] = None


@router.get("", response_model=ManagerSettingsOut)
async def get_settings(db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    result = await db.execute(select(ManagerSettings))
    s = result.scalar_one_or_none()
    if not s:
        s = ManagerSettings()
        db.add(s)
        await db.commit()
        await db.refresh(s)
    return ManagerSettingsOut(
        telegram_id=s.telegram_id,
        telegram_username=s.telegram_username,
        summary_time=str(s.summary_time) if s.summary_time else None,
        weekly_summary_time=str(s.weekly_summary_time) if s.weekly_summary_time else None,
        weekly_summary_day=s.weekly_summary_day,
        alerts_enabled=s.alerts_enabled,
        gamification_enabled=s.gamification_enabled,
        soft_mode_weeks=s.soft_mode_weeks,
    )


@router.put("", response_model=ManagerSettingsOut)
async def update_settings(data: ManagerSettingsUpdate, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    result = await db.execute(select(ManagerSettings))
    s = result.scalar_one_or_none()
    if not s:
        s = ManagerSettings()
        db.add(s)
    updates = data.model_dump(exclude_none=True)
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
    return ManagerSettingsOut(
        telegram_id=s.telegram_id,
        telegram_username=s.telegram_username,
        summary_time=str(s.summary_time) if s.summary_time else None,
        weekly_summary_time=str(s.weekly_summary_time) if s.weekly_summary_time else None,
        weekly_summary_day=s.weekly_summary_day,
        alerts_enabled=s.alerts_enabled,
        gamification_enabled=s.gamification_enabled,
        soft_mode_weeks=s.soft_mode_weeks,
    )
