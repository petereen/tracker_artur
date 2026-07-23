"""Admin CRUD for curated company knowledge used by the OYUNS assistant."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import CompanyKnowledge

router = APIRouter()


class KnowledgeCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    category: Optional[str] = Field(default=None, max_length=80)
    content: str = Field(min_length=1, max_length=20_000)
    is_active: bool = True

    @field_validator("title", "content")
    @classmethod
    def _required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("category")
    @classmethod
    def _optional_text(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() or None if value else None


class KnowledgeUpdate(KnowledgeCreate):
    """PUT uses a complete representation, including the active state."""


class KnowledgeOut(BaseModel):
    id: int
    title: str
    category: Optional[str]
    content: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


@router.get("", response_model=list[KnowledgeOut])
async def list_knowledge(
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    rows = (
        await db.execute(
            select(CompanyKnowledge).order_by(
                CompanyKnowledge.is_active.desc(),
                CompanyKnowledge.updated_at.desc(),
                CompanyKnowledge.id.desc(),
            )
        )
    ).scalars().all()
    return rows


@router.post("", response_model=KnowledgeOut, status_code=status.HTTP_201_CREATED)
async def create_knowledge(
    data: KnowledgeCreate,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    entry = CompanyKnowledge(**data.model_dump())
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


@router.put("/{entry_id}", response_model=KnowledgeOut)
async def update_knowledge(
    entry_id: int,
    data: KnowledgeUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    entry = await db.get(CompanyKnowledge, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="knowledge entry not found")
    for key, value in data.model_dump().items():
        setattr(entry, key, value)
    await db.commit()
    await db.refresh(entry)
    return entry


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_knowledge(
    entry_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    entry = await db.get(CompanyKnowledge, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="knowledge entry not found")
    await db.delete(entry)
    await db.commit()
