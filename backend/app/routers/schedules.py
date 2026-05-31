from datetime import time
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import Schedule


def _t(v: str | None) -> time | None:
    if not v:
        return None
    parts = v.split(":")
    return time(int(parts[0]), int(parts[1]))

router = APIRouter()


class ScheduleOut(BaseModel):
    employee_id: int
    variant: str
    evening_time: Optional[str]
    morning_time: Optional[str]
    weekdays: list[int]
    deadline_time: Optional[str]
    reminder_intervals: list[int]

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_custom(cls, s: Schedule):
        return cls(
            employee_id=s.employee_id,
            variant=s.variant or "A",
            evening_time=str(s.evening_time) if s.evening_time else None,
            morning_time=str(s.morning_time) if s.morning_time else None,
            weekdays=s.weekdays or [],
            deadline_time=str(s.deadline_time) if s.deadline_time else None,
            reminder_intervals=s.reminder_intervals or [],
        )


class ScheduleUpdate(BaseModel):
    variant: Optional[str] = None
    evening_time: Optional[str] = None
    morning_time: Optional[str] = None
    weekdays: Optional[list[int]] = None
    deadline_time: Optional[str] = None
    reminder_intervals: Optional[list[int]] = None


@router.get("", response_model=list[ScheduleOut])
async def list_schedules(db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    result = await db.execute(select(Schedule))
    return [ScheduleOut.from_orm_custom(s) for s in result.scalars().all()]


@router.put("/{employee_id}", response_model=ScheduleOut)
async def update_schedule(employee_id: int, data: ScheduleUpdate, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    result = await db.execute(select(Schedule).where(Schedule.employee_id == employee_id))
    sch = result.scalar_one_or_none()
    if not sch:
        raise HTTPException(status_code=404, detail="Schedule not found")
    updates = data.model_dump(exclude_none=True)
    for tf in ("evening_time", "morning_time", "deadline_time"):
        if tf in updates:
            updates[tf] = _t(updates[tf])
    for k, v in updates.items():
        setattr(sch, k, v)
    await db.commit()
    await db.refresh(sch)
    return ScheduleOut.from_orm_custom(sch)
