"""Admin review endpoints for unclassified OYUNS requests."""

import hashlib
import re
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import AssistantContextExample, CompanyKnowledge, UnknownAssistantRequest

router = APIRouter()


class UnknownRequestOut(BaseModel):
    id: int
    text: str
    language: str
    channel: str
    terms: list[str]
    reason: str
    occurrence_count: int
    status: str
    created_at: datetime
    last_seen_at: datetime

    model_config = {"from_attributes": True}


class UnknownRequestStatusUpdate(BaseModel):
    status: Literal["pending", "reviewed", "dismissed"]


class PromoteUnknownRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    category: Optional[str] = Field(default=None, max_length=80)
    content: str = Field(min_length=1, max_length=20_000)


ContextIntent = Literal["create_task_draft", "get_user_tasks", "search_company_knowledge"]


class ContextExampleInput(BaseModel):
    phrase: str = Field(min_length=1, max_length=500)
    intent: ContextIntent
    meaning: str = Field(min_length=1, max_length=1_000)
    is_active: bool = True

    @staticmethod
    def _normalized_phrase(value: str) -> str:
        return re.sub(r"\s+", " ", value.strip())

    @field_validator("phrase")
    @classmethod
    def _clean_phrase(cls, value: str) -> str:
        value = cls._normalized_phrase(value)
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("meaning")
    @classmethod
    def _clean_meaning(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class ContextExampleCreate(ContextExampleInput):
    pass


class ContextExampleUpdate(ContextExampleInput):
    pass


class ContextExampleOut(ContextExampleInput):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PromoteUnknownToContext(BaseModel):
    intent: ContextIntent
    meaning: str = Field(min_length=1, max_length=1_000)
    phrase: Optional[str] = Field(default=None, max_length=500)
    is_active: bool = True

    @field_validator("meaning")
    @classmethod
    def _clean_meaning(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


def _phrase_hash(phrase: str) -> str:
    normalized = re.sub(r"\s+", " ", phrase.strip()).casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@router.get("/unknown", response_model=list[UnknownRequestOut])
async def list_unknown_requests(
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    return (
        await db.execute(
            select(UnknownAssistantRequest).order_by(
                UnknownAssistantRequest.status.asc(),
                UnknownAssistantRequest.occurrence_count.desc(),
                UnknownAssistantRequest.last_seen_at.desc(),
            )
        )
    ).scalars().all()


@router.put("/unknown/{request_id}", response_model=UnknownRequestOut)
async def update_unknown_request(
    request_id: int,
    data: UnknownRequestStatusUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    request = await db.get(UnknownAssistantRequest, request_id)
    if not request:
        raise HTTPException(status_code=404, detail="unknown request not found")
    request.status = data.status
    await db.commit()
    await db.refresh(request)
    return request


@router.post("/unknown/{request_id}/promote", response_model=UnknownRequestOut)
async def promote_unknown_request(
    request_id: int,
    data: PromoteUnknownRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Turn a reviewed request into active curated company knowledge."""
    request = await db.get(UnknownAssistantRequest, request_id)
    if not request:
        raise HTTPException(status_code=404, detail="unknown request not found")
    db.add(
        CompanyKnowledge(
            title=data.title.strip(),
            category=data.category.strip() if data.category else None,
            content=data.content.strip(),
            is_active=True,
        )
    )
    request.status = "reviewed"
    await db.commit()
    await db.refresh(request)
    return request


@router.post("/unknown/{request_id}/promote-context", response_model=ContextExampleOut)
async def promote_unknown_to_context(
    request_id: int,
    data: PromoteUnknownToContext,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Approve an unknown phrase as intent guidance for the next router calls."""
    request = await db.get(UnknownAssistantRequest, request_id)
    if not request:
        raise HTTPException(status_code=404, detail="unknown request not found")
    phrase = re.sub(r"\s+", " ", (data.phrase or request.text).strip())
    if not phrase:
        raise HTTPException(status_code=422, detail="phrase must not be blank")
    entry = AssistantContextExample(
        phrase=phrase,
        phrase_hash=_phrase_hash(phrase),
        intent=data.intent,
        meaning=data.meaning,
        is_active=data.is_active,
    )
    db.add(entry)
    request.status = "reviewed"
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=409, detail="context phrase already exists") from None
    await db.refresh(entry)
    return entry


@router.get("/contexts", response_model=list[ContextExampleOut])
async def list_context_examples(
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    return (
        await db.execute(
            select(AssistantContextExample).order_by(
                AssistantContextExample.is_active.desc(),
                AssistantContextExample.updated_at.desc(),
                AssistantContextExample.id.desc(),
            )
        )
    ).scalars().all()


@router.post("/contexts", response_model=ContextExampleOut)
async def create_context_example(
    data: ContextExampleCreate,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    phrase = re.sub(r"\s+", " ", data.phrase.strip())
    if not phrase:
        raise HTTPException(status_code=422, detail="phrase must not be blank")
    entry = AssistantContextExample(
        phrase=phrase,
        phrase_hash=_phrase_hash(phrase),
        intent=data.intent,
        meaning=data.meaning.strip(),
        is_active=data.is_active,
    )
    db.add(entry)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=409, detail="context phrase already exists") from None
    await db.refresh(entry)
    return entry


@router.put("/contexts/{context_id}", response_model=ContextExampleOut)
async def update_context_example(
    context_id: int,
    data: ContextExampleUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    entry = await db.get(AssistantContextExample, context_id)
    if not entry:
        raise HTTPException(status_code=404, detail="context example not found")
    phrase = re.sub(r"\s+", " ", data.phrase.strip())
    if not phrase:
        raise HTTPException(status_code=422, detail="phrase must not be blank")
    entry.phrase = phrase
    entry.phrase_hash = _phrase_hash(phrase)
    entry.intent = data.intent
    entry.meaning = data.meaning.strip()
    entry.is_active = data.is_active
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=409, detail="context phrase already exists") from None
    await db.refresh(entry)
    return entry


@router.delete("/contexts/{context_id}", status_code=204)
async def delete_context_example(
    context_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    entry = await db.get(AssistantContextExample, context_id)
    if not entry:
        raise HTTPException(status_code=404, detail="context example not found")
    await db.delete(entry)
    await db.commit()
