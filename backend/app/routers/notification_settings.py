"""Notification settings: tenant-wide rules (admin) and personal preferences.

* ``GET/PUT /v1/settings/notifications`` — Settings → Автоматжуулалт ба
  интеграци → «Мэдэгдлийн тохиргоо» (PUT: admin by granted role).
* ``GET/PUT /v1/auth/preferences/notifications`` — Profile → «Мэдэгдлийн
  тохиргоо» for every signed-in user.

Telegram delivery follows the same resolution (see
``services/notification_preferences.py``).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.enterprise_deps import ActorContext, get_account_actor
from app.models.models import Employee, Organization, UserAccount
from app.services import telegram_bots
from app.services.enterprise_events import record_change
from app.services.notification_preferences import (
    CATEGORIES,
    TENANT_KEY,
    merge_user_choices,
    resolve_category,
    tenant_rules,
    user_choices,
    validate_tenant_input,
)

router = APIRouter()


class TenantCategoryInput(BaseModel):
    enabled: bool | None = None
    web: bool | None = None
    telegram: bool | None = None
    user_editable: bool | None = None


class TenantNotificationInput(BaseModel):
    categories: dict[str, TenantCategoryInput] = Field(default_factory=dict, max_length=len(CATEGORIES))


class PersonalCategoryInput(BaseModel):
    web: bool | None = None
    telegram: bool | None = None


class PersonalNotificationInput(BaseModel):
    categories: dict[str, PersonalCategoryInput] = Field(default_factory=dict, max_length=len(CATEGORIES))


def _visible(category, organization: Organization | None) -> bool:
    # The legacy check-in questionnaire exists for the primary tenant only.
    return not category.legacy or bool(organization and organization.is_primary)


def _tenant_out(organization: Organization | None) -> dict:
    rules = tenant_rules(organization.settings if organization else None, legacy_available=bool(organization and organization.is_primary))
    return {"categories": [
        {"key": category.key, "label": category.label, "description": category.description, "legacy": category.legacy, **rules[category.key]}
        for category in CATEGORIES if _visible(category, organization)
    ]}


async def _require_admin(actor: ActorContext = Depends(get_account_actor)) -> ActorContext:
    if "admin" not in actor.granted_roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permission")
    return actor


@router.get("/settings/notifications")
async def get_tenant_notifications(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(_require_admin)):
    return _tenant_out(await db.get(Organization, actor.organization_id))


@router.put("/settings/notifications")
async def update_tenant_notifications(data: TenantNotificationInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(_require_admin)):
    organization = await db.get(Organization, actor.organization_id, with_for_update=True)
    try:
        incoming = validate_tenant_input({key: item.model_dump() for key, item in data.categories.items()})
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    stored = (organization.settings or {}).get(TENANT_KEY) if isinstance((organization.settings or {}).get(TENANT_KEY), dict) else {}
    categories = {**(stored.get("categories") or {})}
    for key, item in incoming["categories"].items():
        categories[key] = {**(categories.get(key) or {}), **item}
    before = _tenant_out(organization)
    organization.settings = {**(organization.settings or {}), TENANT_KEY: {"categories": categories}}
    await record_change(db, actor=actor, topic="settings", aggregate_type="organization_notification_settings", aggregate_id=organization.id, operation="updated", before=before, after={"categories": categories})
    await db.commit()
    return _tenant_out(organization)


async def _personal_out(db: AsyncSession, actor: ActorContext) -> dict:
    organization = await db.get(Organization, actor.organization_id)
    account = await db.get(UserAccount, actor.account_id)
    employee = await db.get(Employee, actor.employee_id) if actor.employee_id else None
    rules = tenant_rules(organization.settings if organization else None, legacy_available=bool(organization and organization.is_primary))
    choices = user_choices(account.preferences if account else None)
    rows = []
    for category in CATEGORIES:
        if not _visible(category, organization):
            continue
        rule = rules[category.key]
        effective = resolve_category(rules, choices, category.key)
        rows.append({
            "key": category.key, "label": category.label, "description": category.description,
            # Switched off for the whole company: shown, but not changeable.
            "available": rule["enabled"], "editable": rule["enabled"] and rule["user_editable"],
            "web": effective.web, "telegram": effective.telegram,
            "default_web": rule["web"], "default_telegram": rule["telegram"],
        })
    return {
        "categories": rows,
        "telegram_linked": bool(employee and employee.telegram_id),
        "telegram_bot_connected": await telegram_bots.organization_has_bot(db, actor.organization_id),
    }


@router.get("/auth/preferences/notifications")
async def get_personal_notifications(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_account_actor)):
    return await _personal_out(db, actor)


@router.put("/auth/preferences/notifications")
async def update_personal_notifications(data: PersonalNotificationInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_account_actor)):
    organization = await db.get(Organization, actor.organization_id)
    account = await db.get(UserAccount, actor.account_id, with_for_update=True)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    rules = tenant_rules(organization.settings if organization else None, legacy_available=bool(organization and organization.is_primary))
    try:
        account.preferences = merge_user_choices(account.preferences, rules, {key: item.model_dump() for key, item in data.categories.items()})
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await db.commit()
    return await _personal_out(db, actor)
