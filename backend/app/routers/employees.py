from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import Employee, Schedule, Streak

router = APIRouter()


class EmployeeCreate(BaseModel):
    name: str
    telegram_id: str
    telegram_username: Optional[str] = None
    timezone: str = "Europe/Moscow"


class EmployeeUpdate(BaseModel):
    name: Optional[str] = None
    telegram_username: Optional[str] = None
    timezone: Optional[str] = None
    is_active: Optional[bool] = None


class EmployeeOut(BaseModel):
    id: int
    name: str
    telegram_id: str
    telegram_username: Optional[str]
    timezone: str
    is_active: bool

    model_config = {"from_attributes": True}


@router.get("", response_model=list[EmployeeOut])
async def list_employees(db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    result = await db.execute(select(Employee).order_by(Employee.id))
    return result.scalars().all()


@router.post("", response_model=EmployeeOut, status_code=status.HTTP_201_CREATED)
async def create_employee(data: EmployeeCreate, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    emp = Employee(**data.model_dump())
    db.add(emp)
    await db.flush()
    db.add(Schedule(employee_id=emp.id))
    db.add(Streak(employee_id=emp.id))
    await db.commit()
    await db.refresh(emp)
    return emp


@router.put("/{employee_id}", response_model=EmployeeOut)
async def update_employee(employee_id: int, data: EmployeeUpdate, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    result = await db.execute(select(Employee).where(Employee.id == employee_id))
    emp = result.scalar_one_or_none()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(emp, k, v)
    await db.commit()
    await db.refresh(emp)
    return emp


@router.delete("/{employee_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_employee(employee_id: int, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    result = await db.execute(select(Employee).where(Employee.id == employee_id))
    emp = result.scalar_one_or_none()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    await db.delete(emp)
    await db.commit()
