"""REST API задач: admin (JWT) и Mini App (Telegram initData)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.telegram_auth import verify_init_data
from app.models.models import DEFAULT_REMINDER_INTERVALS_MIN, Employee, ManagerSettings, Task, TaskComment

router = APIRouter()          # admin, mount /tasks
miniapp_router = APIRouter()  # Mini App, mount /miniapp

ACTIVE_STATUSES = ("open", "in_progress", "overdue")
VALID_STATUSES = ("open", "in_progress", "done", "overdue", "cancelled")


# ─── схемы ────────────────────────────────────────────────────────────────────

class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    assignee_id: Optional[int] = None
    deadline_at: Optional[datetime] = None
    priority: int = 2


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    assignee_id: Optional[int] = None
    deadline_at: Optional[datetime] = None
    priority: Optional[int] = None
    status: Optional[str] = None


class CommentCreate(BaseModel):
    text: str


class TaskOut(BaseModel):
    id: int
    title: str
    description: Optional[str]
    status: str
    priority: int
    deadline_at: Optional[datetime]
    created_at: Optional[datetime]
    completed_at: Optional[datetime]
    assignee_id: Optional[int]
    assignee_name: Optional[str]
    created_by_id: Optional[int]
    created_by_tg: Optional[str]
    creator_name: Optional[str]
    reminder_intervals_min: list[int]


# ─── сериализация ────────────────────────────────────────────────────────────

async def _serialize(db: AsyncSession, task: Task) -> TaskOut:
    assignee = await db.get(Employee, task.assignee_id) if task.assignee_id else None
    creator = await db.get(Employee, task.created_by_id) if task.created_by_id else None
    return TaskOut(
        id=task.id, title=task.title, description=task.description, status=task.status,
        priority=task.priority, deadline_at=task.deadline_at, created_at=task.created_at,
        completed_at=task.completed_at, assignee_id=task.assignee_id,
        assignee_name=assignee.name if assignee else None,
        created_by_id=task.created_by_id, created_by_tg=task.created_by_tg,
        creator_name=creator.name if creator else None,
        reminder_intervals_min=list(task.reminder_intervals_min or []),
    )


async def _apply_update(task: Task, data: TaskUpdate) -> None:
    if data.status is not None:
        if data.status not in VALID_STATUSES:
            raise HTTPException(status_code=400, detail="invalid status")
        task.status = data.status
        if data.status == "done" and not task.completed_at:
            task.completed_at = datetime.now(timezone.utc)
    for field in ("title", "description", "assignee_id", "deadline_at", "priority"):
        val = getattr(data, field)
        if val is not None:
            setattr(task, field, val)


# ─── ADMIN (JWT) ────────────────────────────────────────────────────────────────

@router.get("", response_model=list[TaskOut])
async def list_tasks(
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
    status_: Optional[str] = Query(None, alias="status"),
    assignee_id: Optional[int] = None,
    created_by_id: Optional[int] = None,
    active: bool = False,
):
    q = select(Task)
    if status_:
        q = q.where(Task.status == status_)
    if active:
        q = q.where(Task.status.in_(ACTIVE_STATUSES))
    if assignee_id is not None:
        q = q.where(Task.assignee_id == assignee_id)
    if created_by_id is not None:
        q = q.where(Task.created_by_id == created_by_id)
    q = q.order_by(Task.deadline_at.asc().nullslast(), Task.priority.asc(), Task.id.desc())
    rows = (await db.execute(q)).scalars().all()
    return [await _serialize(db, t) for t in rows]


@router.post("", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def create_task(data: TaskCreate, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    task = Task(
        title=data.title, description=data.description, assignee_id=data.assignee_id,
        deadline_at=data.deadline_at, priority=data.priority, status="open",
        reminder_intervals_min=list(DEFAULT_REMINDER_INTERVALS_MIN),
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return await _serialize(db, task)


@router.get("/{task_id}", response_model=TaskOut)
async def get_task(task_id: int, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="not found")
    return await _serialize(db, task)


@router.patch("/{task_id}", response_model=TaskOut)
async def update_task(task_id: int, data: TaskUpdate, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="not found")
    await _apply_update(task, data)
    await db.commit()
    await db.refresh(task)
    return await _serialize(db, task)


@router.get("/{task_id}/comments")
async def list_comments(task_id: int, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    rows = (await db.execute(
        select(TaskComment).where(TaskComment.task_id == task_id).order_by(TaskComment.created_at)
    )).scalars().all()
    return [{"id": c.id, "text": c.text, "author_id": c.author_id, "author_tg": c.author_tg, "created_at": c.created_at} for c in rows]


@router.post("/{task_id}/comments", status_code=status.HTTP_201_CREATED)
async def add_comment(task_id: int, data: CommentCreate, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="not found")
    c = TaskComment(task_id=task_id, text=data.text)
    db.add(c)
    await db.commit()
    return {"ok": True}


# ─── MINI APP (Telegram initData) ────────────────────────────────────────────────

async def _miniapp_actor(db: AsyncSession, init_data: Optional[str]) -> tuple[Employee, bool]:
    tg_user = verify_init_data(init_data or "")
    if not tg_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid initData")
    tg_id = str(tg_user.get("id"))
    emp = (await db.execute(select(Employee).where(Employee.telegram_id == tg_id))).scalar_one_or_none()
    is_manager = tg_id == str(settings.MANAGER_TG_ID)
    if not is_manager:
        ms = (await db.execute(select(ManagerSettings))).scalars().first()
        is_manager = bool(ms and ms.telegram_id and str(ms.telegram_id) == tg_id)
    if not emp and not is_manager:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not registered")
    return emp, is_manager


@miniapp_router.get("/me")
async def miniapp_me(db: AsyncSession = Depends(get_db), x_telegram_init_data: Optional[str] = Header(None)):
    emp, is_manager = await _miniapp_actor(db, x_telegram_init_data)
    return {
        "employee_id": emp.id if emp else None,
        "name": emp.name if emp else "Руководитель",
        "is_manager": is_manager,
    }


@miniapp_router.get("/tasks", response_model=list[TaskOut])
async def miniapp_tasks(
    db: AsyncSession = Depends(get_db),
    x_telegram_init_data: Optional[str] = Header(None),
    scope: str = Query("mine", pattern="^(mine|assigned|created|all)$"),
):
    emp, is_manager = await _miniapp_actor(db, x_telegram_init_data)
    q = select(Task).where(Task.status.in_(ACTIVE_STATUSES))
    if scope == "all" and is_manager:
        pass
    elif scope == "assigned" and emp:
        q = q.where(Task.assignee_id == emp.id)
    elif scope == "created" and emp:
        q = q.where(Task.created_by_id == emp.id)
    else:  # mine
        if emp:
            q = q.where(or_(Task.assignee_id == emp.id, Task.created_by_id == emp.id))
        elif not is_manager:
            return []
    q = q.order_by(Task.deadline_at.asc().nullslast(), Task.priority.asc(), Task.id.desc())
    rows = (await db.execute(q)).scalars().all()
    return [await _serialize(db, t) for t in rows]


@miniapp_router.post("/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def miniapp_create(
    data: TaskCreate, db: AsyncSession = Depends(get_db), x_telegram_init_data: Optional[str] = Header(None)
):
    emp, is_manager = await _miniapp_actor(db, x_telegram_init_data)
    assignee_id = data.assignee_id
    if assignee_id and assignee_id != (emp.id if emp else None) and not is_manager:
        raise HTTPException(status_code=403, detail="only manager can assign to others")
    if not assignee_id:
        assignee_id = emp.id if emp else None
    task = Task(
        title=data.title, description=data.description, assignee_id=assignee_id,
        created_by_id=emp.id if emp else None,
        deadline_at=data.deadline_at, priority=data.priority, status="open",
        reminder_intervals_min=list(DEFAULT_REMINDER_INTERVALS_MIN),
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return await _serialize(db, task)


@miniapp_router.patch("/tasks/{task_id}", response_model=TaskOut)
async def miniapp_update(
    task_id: int, data: TaskUpdate, db: AsyncSession = Depends(get_db), x_telegram_init_data: Optional[str] = Header(None)
):
    emp, is_manager = await _miniapp_actor(db, x_telegram_init_data)
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="not found")
    allowed = is_manager or (emp and task.assignee_id == emp.id) or (emp and task.created_by_id == emp.id)
    if not allowed:
        raise HTTPException(status_code=403, detail="forbidden")
    await _apply_update(task, data)
    await db.commit()
    await db.refresh(task)
    return await _serialize(db, task)
