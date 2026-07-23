"""Admin review endpoints for unclassified OYUNS requests."""

from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import CompanyKnowledge, UnknownAssistantRequest

router = APIRouter()


class UnknownRequestOut(BaseModel):
    id: int
    text: str
    language: str
    channel: str
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
