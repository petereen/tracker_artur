"""CRM reference data, capabilities, form lookups, and shared file access."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.enterprise_deps import ActorContext, get_actor
from app.crm.common import crm_error, download_response, get_crm_attachment, validate_references
from app.crm.schemas import (
    ActivityTypeInput,
    ActivityTypePatch,
    PartyGroupInput,
    PartyGroupPatch,
    PaymentTermInput,
    PaymentTermPatch,
    StatusInput,
    StatusPatch,
)
from app.crm.service import (
    ACTIVITY_RESOURCE,
    PARTY_RESOURCE,
    SETTINGS_RESOURCE,
    STATUS_REGISTERS,
    assert_group_is_not_descendant,
    capability_matrix,
    crm_module_enabled,
    ensure_crm_defaults,
    has_capability,
    next_simple_code,
)
from app.erp.service import require_capability
from app.models.contracts import ContractDocument
from app.models.crm import CRMActivity, CRMActivityType, ERPPartyGroup, ERPPaymentTerm, ERPStatus
from app.models.models import Attachment, Employee, ERPAccount, ERPParty, ERPPriceList, Project
from app.services.attachment_storage import delete_attachment
from app.services.enterprise_events import record_change

router = APIRouter()


@router.get("/capabilities")
async def crm_capabilities(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    """What the current user may do; the frontend uses this for nav and buttons."""
    matrix = await capability_matrix(db, actor)
    return {
        "module_enabled": await crm_module_enabled(db, actor.organization_id),
        "employee_id": actor.employee_id,
        "parties": matrix[PARTY_RESOURCE],
        "activities": matrix[ACTIVITY_RESOURCE],
        "settings": matrix[SETTINGS_RESOURCE],
    }


@router.get("/lookups")
async def crm_lookups(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    """Everything the CRM forms need for their pickers, in one request."""
    if not (await has_capability(db, actor, PARTY_RESOURCE, "view") or await has_capability(db, actor, ACTIVITY_RESOURCE, "view")):
        raise crm_error(403, "crm_forbidden", "CRM-д хандах эрхгүй байна")
    await ensure_crm_defaults(db, actor.organization_id)
    await db.commit()
    org = actor.organization_id
    employees = (await db.execute(select(Employee.id, Employee.name, Employee.job_title).where(
        Employee.organization_id == org, Employee.is_active.is_(True), Employee.deleted_at.is_(None)).order_by(Employee.name))).all()
    statuses = (await db.execute(select(ERPStatus).where(ERPStatus.organization_id == org, ERPStatus.register == "crm_activity").order_by(ERPStatus.sort, ERPStatus.id))).scalars().all()
    types = (await db.execute(select(CRMActivityType).where(CRMActivityType.organization_id == org).order_by(CRMActivityType.sort, CRMActivityType.id))).scalars().all()
    groups = (await db.execute(select(ERPPartyGroup).where(ERPPartyGroup.organization_id == org).order_by(ERPPartyGroup.name))).scalars().all()
    terms = (await db.execute(select(ERPPaymentTerm).where(ERPPaymentTerm.organization_id == org).order_by(ERPPaymentTerm.code))).scalars().all()
    contracts = (await db.execute(select(ContractDocument.id, ContractDocument.title, ContractDocument.status).where(ContractDocument.organization_id == org)
                                  .order_by(ContractDocument.updated_at.desc()).limit(500))).all()
    projects = (await db.execute(select(Project.id, Project.code, Project.name).where(Project.organization_id == org, Project.archived_at.is_(None)).order_by(Project.name))).all()
    price_lists = (await db.execute(select(ERPPriceList.id, ERPPriceList.code, ERPPriceList.name).where(ERPPriceList.organization_id == org, ERPPriceList.is_active.is_(True)).order_by(ERPPriceList.name))).all()
    accounts = (await db.execute(select(ERPAccount.id, ERPAccount.code, ERPAccount.name).where(
        ERPAccount.organization_id == org, ERPAccount.is_group.is_(False), ERPAccount.account_type.in_(("receivable", "payable"))).order_by(ERPAccount.code))).all()
    return {
        "employees": [{"id": eid, "name": name, "job_title": title} for eid, name, title in employees],
        "statuses": [status_out(row) for row in statuses],
        "activity_types": [type_out(row) for row in types],
        "party_groups": [group_out(row) for row in groups],
        "payment_terms": [term_out(row) for row in terms],
        "contracts": [{"id": cid, "title": title, "status": state} for cid, title, state in contracts],
        "projects": [{"id": pid, "code": code, "name": name} for pid, code, name in projects],
        "price_lists": [{"id": pid, "code": code, "name": name} for pid, code, name in price_lists],
        "settlement_accounts": [{"id": aid, "code": code, "name": name} for aid, code, name in accounts],
    }


def status_out(row: ERPStatus) -> dict[str, Any]:
    return {"id": row.id, "register": row.register, "code": row.code, "name": row.name, "sort": row.sort, "color": row.color, "category": row.category, "is_active": row.is_active}


def type_out(row: CRMActivityType) -> dict[str, Any]:
    return {"id": row.id, "code": row.code, "name": row.name, "sort": row.sort, "is_active": row.is_active}


def group_out(row: ERPPartyGroup) -> dict[str, Any]:
    return {"id": row.id, "code": row.code, "name": row.name, "parent_id": row.parent_id, "is_default": row.is_default, "is_foreign": row.is_foreign,
            "default_settlement_account_id": row.default_settlement_account_id, "default_price_list_id": row.default_price_list_id, "is_active": row.is_active}


def term_out(row: ERPPaymentTerm) -> dict[str, Any]:
    return {"id": row.id, "code": row.code, "name": row.name, "days": row.days, "period_unit": row.period_unit, "period_value": row.period_value, "is_active": row.is_active}


async def _settings_row(db: AsyncSession, model: Any, actor: ActorContext, row_id: int) -> Any:
    row = await db.scalar(select(model).where(model.id == row_id, model.organization_id == actor.organization_id))
    if not row:
        raise crm_error(404, "crm_setting_not_found", "Тохиргооны бүртгэл олдсонгүй")
    return row


async def _assert_code_free(db: AsyncSession, model: Any, organization_id: int, code: str, *, exclude_id: int | None = None, extra: Any = None) -> None:
    statement = select(model.id).where(model.organization_id == organization_id, model.code == code)
    if exclude_id is not None:
        statement = statement.where(model.id != exclude_id)
    if extra is not None:
        statement = statement.where(extra)
    if await db.scalar(statement):
        raise crm_error(409, "crm_code_taken", f"“{code}” код давхардсан байна")


def _apply_patch(row: Any, changes: dict[str, Any], *, required: set[str]) -> None:
    for field, value in changes.items():
        if field in required and value is None:
            continue
        setattr(row, field, value)


async def _audit(db: AsyncSession, actor: ActorContext, aggregate: str, row_id: int, operation: str, after: dict[str, Any] | None = None) -> None:
    await record_change(db, actor=actor, topic="crm", aggregate_type=aggregate, aggregate_id=row_id, operation=operation, after=after or {})


# ─── Statuses (Төлөв) ──────────────────────────────────────────────────────────

def _register(register: str) -> str:
    if register not in STATUS_REGISTERS:
        raise crm_error(422, "crm_unknown_register", "Тухайн бүртгэлд төлөв тохируулах боломжгүй")
    return register


@router.get("/settings/statuses")
async def list_statuses(register: str = Query(default="crm_activity"), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, ACTIVITY_RESOURCE, "view")
    await ensure_crm_defaults(db, actor.organization_id)
    await db.commit()
    rows = (await db.execute(select(ERPStatus).where(ERPStatus.organization_id == actor.organization_id, ERPStatus.register == _register(register))
                             .order_by(ERPStatus.sort, ERPStatus.id))).scalars().all()
    return [status_out(row) for row in rows]


@router.post("/settings/statuses", status_code=status.HTTP_201_CREATED)
async def create_status(data: StatusInput, register: str = Query(default="crm_activity"), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, SETTINGS_RESOURCE, "edit")
    register = _register(register)
    code = data.code or await next_simple_code(db, ERPStatus, actor.organization_id, "S", extra_filter=ERPStatus.register == register)
    await _assert_code_free(db, ERPStatus, actor.organization_id, code, extra=ERPStatus.register == register)
    row = ERPStatus(organization_id=actor.organization_id, register=register, **{**data.model_dump(), "code": code})
    db.add(row)
    await db.flush()
    await _audit(db, actor, "erp_status", row.id, "created", status_out(row))
    await db.commit()
    return status_out(row)


@router.patch("/settings/statuses/{status_id}")
async def update_status(status_id: int, data: StatusPatch, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, SETTINGS_RESOURCE, "edit")
    row = await _settings_row(db, ERPStatus, actor, status_id)
    changes = data.model_dump(exclude_unset=True)
    if changes.get("code"):
        await _assert_code_free(db, ERPStatus, actor.organization_id, changes["code"], exclude_id=row.id, extra=ERPStatus.register == row.register)
    _apply_patch(row, changes, required={"code", "name", "sort", "color", "category", "is_active"})
    await _audit(db, actor, "erp_status", row.id, "updated", status_out(row))
    await db.commit()
    return status_out(row)


@router.delete("/settings/statuses/{status_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_status(status_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, SETTINGS_RESOURCE, "edit")
    row = await _settings_row(db, ERPStatus, actor, status_id)
    if await db.scalar(select(CRMActivity.id).where(CRMActivity.status_id == row.id).limit(1)):
        raise crm_error(409, "crm_setting_in_use", "Ашиглагдаж буй төлөвийг устгахын оронд идэвхгүй болгоно уу")
    await db.delete(row)
    await _audit(db, actor, "erp_status", status_id, "deleted", {"code": row.code})
    await db.commit()


# ─── Activity types ───────────────────────────────────────────────────────────

@router.post("/settings/activity-types", status_code=status.HTTP_201_CREATED)
async def create_activity_type(data: ActivityTypeInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, SETTINGS_RESOURCE, "edit")
    code = data.code or await next_simple_code(db, CRMActivityType, actor.organization_id, "T")
    await _assert_code_free(db, CRMActivityType, actor.organization_id, code)
    row = CRMActivityType(organization_id=actor.organization_id, **{**data.model_dump(), "code": code})
    db.add(row)
    await db.flush()
    await _audit(db, actor, "crm_activity_type", row.id, "created", type_out(row))
    await db.commit()
    return type_out(row)


@router.patch("/settings/activity-types/{type_id}")
async def update_activity_type(type_id: int, data: ActivityTypePatch, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, SETTINGS_RESOURCE, "edit")
    row = await _settings_row(db, CRMActivityType, actor, type_id)
    changes = data.model_dump(exclude_unset=True)
    if changes.get("code"):
        await _assert_code_free(db, CRMActivityType, actor.organization_id, changes["code"], exclude_id=row.id)
    _apply_patch(row, changes, required={"code", "name", "sort", "is_active"})
    await _audit(db, actor, "crm_activity_type", row.id, "updated", type_out(row))
    await db.commit()
    return type_out(row)


@router.delete("/settings/activity-types/{type_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_activity_type(type_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, SETTINGS_RESOURCE, "edit")
    row = await _settings_row(db, CRMActivityType, actor, type_id)
    if await db.scalar(select(CRMActivity.id).where(CRMActivity.type_id == row.id).limit(1)):
        raise crm_error(409, "crm_setting_in_use", "Ашиглагдаж буй төрлийг устгахын оронд идэвхгүй болгоно уу")
    await db.delete(row)
    await _audit(db, actor, "crm_activity_type", type_id, "deleted", {"code": row.code})
    await db.commit()


# ─── Party groups (Харилцагчийн бүлэг) ─────────────────────────────────────────

async def _unset_other_default_groups(db: AsyncSession, organization_id: int, keep_id: int) -> None:
    for row in (await db.execute(select(ERPPartyGroup).where(ERPPartyGroup.organization_id == organization_id, ERPPartyGroup.is_default.is_(True), ERPPartyGroup.id != keep_id))).scalars().all():
        row.is_default = False


@router.post("/settings/party-groups", status_code=status.HTTP_201_CREATED)
async def create_party_group(data: PartyGroupInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, SETTINGS_RESOURCE, "edit")
    values = data.model_dump()
    await validate_references(db, actor.organization_id, {key: values[key] for key in ("parent_id", "default_settlement_account_id", "default_price_list_id")})
    code = data.code or await next_simple_code(db, ERPPartyGroup, actor.organization_id, "G")
    await _assert_code_free(db, ERPPartyGroup, actor.organization_id, code)
    row = ERPPartyGroup(organization_id=actor.organization_id, **{**values, "code": code})
    db.add(row)
    await db.flush()
    if row.is_default:
        await _unset_other_default_groups(db, actor.organization_id, row.id)
    await _audit(db, actor, "erp_party_group", row.id, "created", group_out(row))
    await db.commit()
    return group_out(row)


@router.patch("/settings/party-groups/{group_id}")
async def update_party_group(group_id: int, data: PartyGroupPatch, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, SETTINGS_RESOURCE, "edit")
    row = await _settings_row(db, ERPPartyGroup, actor, group_id)
    changes = data.model_dump(exclude_unset=True)
    await validate_references(db, actor.organization_id, {key: changes.get(key) for key in ("parent_id", "default_settlement_account_id", "default_price_list_id") if key in changes})
    if "parent_id" in changes:
        await assert_group_is_not_descendant(db, actor.organization_id, row.id, changes["parent_id"])
    if changes.get("code"):
        await _assert_code_free(db, ERPPartyGroup, actor.organization_id, changes["code"], exclude_id=row.id)
    _apply_patch(row, changes, required={"code", "name", "is_default", "is_foreign", "is_active"})
    if row.is_default:
        await _unset_other_default_groups(db, actor.organization_id, row.id)
    await _audit(db, actor, "erp_party_group", row.id, "updated", group_out(row))
    await db.commit()
    return group_out(row)


@router.delete("/settings/party-groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_party_group(group_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, SETTINGS_RESOURCE, "edit")
    row = await _settings_row(db, ERPPartyGroup, actor, group_id)
    in_use = await db.scalar(select(func.count(ERPParty.id)).where(ERPParty.group_id == row.id))
    has_children = await db.scalar(select(ERPPartyGroup.id).where(ERPPartyGroup.parent_id == row.id).limit(1))
    if in_use or has_children:
        raise crm_error(409, "crm_setting_in_use", "Харилцагч эсвэл дэд бүлэгтэй бүлгийг устгах боломжгүй. Идэвхгүй болгоно уу.")
    await db.delete(row)
    await _audit(db, actor, "erp_party_group", group_id, "deleted", {"code": row.code})
    await db.commit()


# ─── Payment terms (Төлбөрийн нөхцөл) ──────────────────────────────────────────

@router.post("/settings/payment-terms", status_code=status.HTTP_201_CREATED)
async def create_payment_term(data: PaymentTermInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, SETTINGS_RESOURCE, "edit")
    code = data.code or await next_simple_code(db, ERPPaymentTerm, actor.organization_id, "P")
    await _assert_code_free(db, ERPPaymentTerm, actor.organization_id, code)
    row = ERPPaymentTerm(organization_id=actor.organization_id, **{**data.model_dump(), "code": code})
    db.add(row)
    await db.flush()
    await _audit(db, actor, "erp_payment_term", row.id, "created", term_out(row))
    await db.commit()
    return term_out(row)


@router.patch("/settings/payment-terms/{term_id}")
async def update_payment_term(term_id: int, data: PaymentTermPatch, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, SETTINGS_RESOURCE, "edit")
    row = await _settings_row(db, ERPPaymentTerm, actor, term_id)
    changes = data.model_dump(exclude_unset=True)
    if changes.get("code"):
        await _assert_code_free(db, ERPPaymentTerm, actor.organization_id, changes["code"], exclude_id=row.id)
    _apply_patch(row, changes, required={"code", "name", "days", "period_unit", "period_value", "is_active"})
    await _audit(db, actor, "erp_payment_term", row.id, "updated", term_out(row))
    await db.commit()
    return term_out(row)


@router.delete("/settings/payment-terms/{term_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_payment_term(term_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, SETTINGS_RESOURCE, "edit")
    row = await _settings_row(db, ERPPaymentTerm, actor, term_id)
    if await db.scalar(select(ERPParty.id).where(ERPParty.payment_term_id == row.id).limit(1)):
        raise crm_error(409, "crm_setting_in_use", "Харилцагчид ашиглагдаж буй нөхцөлийг идэвхгүй болгоно уу")
    await db.delete(row)
    await _audit(db, actor, "erp_payment_term", term_id, "deleted", {"code": row.code})
    await db.commit()


# ─── Files shared by parties and activities ───────────────────────────────────

async def _authorize_file(db: AsyncSession, actor: ActorContext, row: Attachment, action: str) -> None:
    resource = PARTY_RESOURCE if row.object_type == "erp_party" else ACTIVITY_RESOURCE
    await require_capability(db, actor, resource, action)


@router.get("/files/{attachment_id}/download")
async def download_crm_file(attachment_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    row = await get_crm_attachment(db, actor, attachment_id)
    await _authorize_file(db, actor, row, "view")
    return await download_response(row)


@router.delete("/files/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_crm_file(attachment_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    row = await get_crm_attachment(db, actor, attachment_id)
    await _authorize_file(db, actor, row, "edit")
    storage_key = row.storage_key
    await db.delete(row)
    await _audit(db, actor, "attachment", attachment_id, "deleted", {"object_type": row.object_type, "object_id": row.object_id, "filename": row.filename})
    await db.commit()
    await delete_attachment(storage_key)
