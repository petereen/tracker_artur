import hashlib
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.enterprise_deps import ActorContext, get_actor
from app.models.models import MobilePushRegistration
from app.services.secret_box import encrypt_secret


router = APIRouter()


class PushRegistrationInput(BaseModel):
    platform: Literal["ios", "android"]
    provider: Literal["apns", "fcm"]
    token: str = Field(min_length=16, max_length=4096)

    @model_validator(mode="after")
    def validate_platform_provider(self):
        expected = "apns" if self.platform == "ios" else "fcm"
        if self.provider != expected:
            raise ValueError(f"{self.platform} registrations must use {expected}")
        self.token = self.token.strip()
        if len(self.token) < 16:
            raise ValueError("Push token is invalid")
        return self


class PushRegistrationOut(BaseModel):
    status: Literal["registered", "revoked", "not_found"]
    platform: Literal["ios", "android"]
    provider: Literal["apns", "fcm"]


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@router.put("/push-registration", response_model=PushRegistrationOut)
async def upsert_push_registration(
    data: PushRegistrationInput,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    now = datetime.now(timezone.utc)
    token_hash = _token_hash(data.token)
    encrypted_token = encrypt_secret(data.token)
    statement = postgres_insert(MobilePushRegistration).values(
        organization_id=actor.organization_id,
        account_id=actor.account_id,
        platform=data.platform,
        provider=data.provider,
        token_hash=token_hash,
        encrypted_token=encrypted_token,
        is_active=True,
        revoked_at=None,
        last_registered_at=now,
    ).on_conflict_do_update(
        index_elements=[MobilePushRegistration.token_hash],
        set_={
            "organization_id": actor.organization_id,
            "account_id": actor.account_id,
            "platform": data.platform,
            "provider": data.provider,
            "encrypted_token": encrypted_token,
            "is_active": True,
            "revoked_at": None,
            "last_registered_at": now,
            "updated_at": now,
        },
    )
    await db.execute(statement)
    await db.commit()
    return PushRegistrationOut(status="registered", platform=data.platform, provider=data.provider)


@router.delete("/push-registration", response_model=PushRegistrationOut)
async def revoke_push_registration(
    data: PushRegistrationInput,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    registration = (
        await db.execute(
            select(MobilePushRegistration)
            .where(
                MobilePushRegistration.token_hash == _token_hash(data.token),
                MobilePushRegistration.organization_id == actor.organization_id,
                MobilePushRegistration.account_id == actor.account_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if registration is None:
        return PushRegistrationOut(status="not_found", platform=data.platform, provider=data.provider)

    registration.is_active = False
    registration.revoked_at = datetime.now(timezone.utc)
    await db.commit()
    return PushRegistrationOut(status="revoked", platform=data.platform, provider=data.provider)
