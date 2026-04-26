from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import Question

router = APIRouter()


class QuestionCreate(BaseModel):
    text: str
    answer_type: str
    options: list[Any] = []
    is_required: bool = True
    sort_order: int = 0


class QuestionUpdate(BaseModel):
    text: Optional[str] = None
    answer_type: Optional[str] = None
    options: Optional[list[Any]] = None
    is_required: Optional[bool] = None
    sort_order: Optional[int] = None


class QuestionOut(BaseModel):
    id: int
    text: str
    answer_type: str
    options: list[Any]
    is_required: bool
    sort_order: int

    model_config = {"from_attributes": True}


class ReorderRequest(BaseModel):
    ids: list[int]


@router.get("", response_model=list[QuestionOut])
async def list_questions(db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    result = await db.execute(select(Question).order_by(Question.sort_order))
    return result.scalars().all()


@router.post("", response_model=QuestionOut, status_code=status.HTTP_201_CREATED)
async def create_question(data: QuestionCreate, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    q = Question(**data.model_dump())
    db.add(q)
    await db.commit()
    await db.refresh(q)
    return q


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
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(q, k, v)
    await db.commit()
    await db.refresh(q)
    return q


@router.delete("/{question_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_question(question_id: int, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    result = await db.execute(select(Question).where(Question.id == question_id))
    q = result.scalar_one_or_none()
    if not q:
        raise HTTPException(status_code=404, detail="Not found")
    await db.delete(q)
    await db.commit()
