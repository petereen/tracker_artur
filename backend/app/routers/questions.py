from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import Employee, EmployeeQuestion, Question

router = APIRouter()


class QuestionCreate(BaseModel):
    text: str
    answer_type: str
    options: list[Any] = Field(default_factory=list)
    is_required: bool = True
    sort_order: int = 0
    employee_ids: list[int] = Field(default_factory=list)


class QuestionUpdate(BaseModel):
    text: Optional[str] = None
    answer_type: Optional[str] = None
    options: Optional[list[Any]] = None
    is_required: Optional[bool] = None
    sort_order: Optional[int] = None
    employee_ids: Optional[list[int]] = None


class QuestionOut(BaseModel):
    id: int
    text: str
    answer_type: str
    options: list[Any]
    is_required: bool
    sort_order: int
    employee_ids: list[int] = Field(default_factory=list)

    model_config = {"from_attributes": True}

    # Defense-in-depth (same class as Sentry #28): these columns had only
    # client-side defaults and no server_default, so a raw/legacy row could be
    # NULL and crash serialization of these required fields.
    @field_validator("options", mode="before")
    @classmethod
    def _default_options(cls, v):
        return [] if v is None else v

    @field_validator("is_required", mode="before")
    @classmethod
    def _default_is_required(cls, v):
        return True if v is None else v

    @field_validator("sort_order", mode="before")
    @classmethod
    def _default_sort_order(cls, v):
        return 0 if v is None else v


class ReorderRequest(BaseModel):
    ids: list[int]


@router.get("", response_model=list[QuestionOut])
async def list_questions(db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    questions = (await db.execute(select(Question).order_by(Question.sort_order))).scalars().all()
    assignments = (await db.execute(select(EmployeeQuestion))).scalars().all()
    assigned_by_question: dict[int, list[int]] = {}
    for assignment in assignments:
        assigned_by_question.setdefault(assignment.question_id, []).append(assignment.employee_id)
    return [
        {**{column.name: getattr(question, column.name) for column in Question.__table__.columns},
         "employee_ids": assigned_by_question.get(question.id, [])}
        for question in questions
    ]


@router.post("", response_model=QuestionOut, status_code=status.HTTP_201_CREATED)
async def create_question(data: QuestionCreate, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    employee_ids = data.employee_ids
    if employee_ids:
        existing_ids = set((await db.execute(select(Employee.id).where(Employee.id.in_(employee_ids)))).scalars().all())
        missing_ids = set(employee_ids) - existing_ids
        if missing_ids:
            raise HTTPException(status_code=400, detail="One or more workers were not found")
    q = Question(**data.model_dump(exclude={"employee_ids"}))
    db.add(q)
    await db.flush()
    for employee_id in dict.fromkeys(employee_ids):
        db.add(EmployeeQuestion(employee_id=employee_id, question_id=q.id))
    await db.commit()
    await db.refresh(q)
    return {**{column.name: getattr(q, column.name) for column in Question.__table__.columns}, "employee_ids": employee_ids}


@router.put("/reorder", status_code=status.HTTP_200_OK)
async def reorder_questions(data: ReorderRequest, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    for idx, qid in enumerate(data.ids):
        result = await db.execute(select(Question).where(Question.id == qid))
        q = result.scalar_one_or_none()
        if q:
            q.sort_order = idx
    await db.commit()
    return {"ok": True}


@router.put("/{question_id}", response_model=QuestionOut)
async def update_question(question_id: int, data: QuestionUpdate, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    result = await db.execute(select(Question).where(Question.id == question_id))
    q = result.scalar_one_or_none()
    if not q:
        raise HTTPException(status_code=404, detail="Not found")
    employee_ids = data.employee_ids
    if employee_ids is not None:
        existing_ids = set((await db.execute(select(Employee.id).where(Employee.id.in_(employee_ids)))).scalars().all()) if employee_ids else set()
        if set(employee_ids) - existing_ids:
            raise HTTPException(status_code=400, detail="One or more workers were not found")
        await db.execute(EmployeeQuestion.__table__.delete().where(EmployeeQuestion.question_id == question_id))
        for employee_id in dict.fromkeys(employee_ids):
            db.add(EmployeeQuestion(employee_id=employee_id, question_id=question_id))
    for k, v in data.model_dump(exclude_none=True, exclude={"employee_ids"}).items():
        setattr(q, k, v)
    await db.commit()
    await db.refresh(q)
    return {**{column.name: getattr(q, column.name) for column in Question.__table__.columns}, "employee_ids": employee_ids if employee_ids is not None else [row.employee_id for row in (await db.execute(select(EmployeeQuestion).where(EmployeeQuestion.question_id == question_id))).scalars().all()]}


@router.delete("/{question_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_question(question_id: int, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    result = await db.execute(select(Question).where(Question.id == question_id))
    q = result.scalar_one_or_none()
    if not q:
        raise HTTPException(status_code=404, detail="Not found")
    await db.delete(q)
    await db.commit()
