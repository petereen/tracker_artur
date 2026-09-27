"""Serializers and request helpers shared by the CRM routers."""

from __future__ import annotations

import hashlib
import mimetypes
import uuid
from datetime import date, datetime
from typing import Any

from fastapi import HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.enterprise_deps import ActorContext
from app.crm.service import activity_is_open, activity_is_overdue, overdue_days
from app.models.contracts import ContractDocument
from app.models.crm import CRMActivity, CRMActivityType, ERPPartyBankAccount, ERPPartyContact, ERPPartyGroup, ERPPaymentTerm, ERPStatus
from app.models.models import Attachment, Employee, ERPAccount, ERPParty, ERPPriceList, Organization, Project, Task
from app.services.attachment_storage import delete_attachment, get_attachment, put_attachment
from app.services.enterprise_events import record_change
from app.services.malware_scanner import MalwareDetected, MalwareScanUnavailable, scan_upload

ATTACHMENT_OBJECT_TYPES = {"party": "erp_party", "activity": "crm_activity"}


def crm_error(status_code: int, code: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message, **extra})


def assert_version(row: Any, expected: int | None) -> None:
    if expected is not None and expected != row.version:
        raise crm_error(409, "crm_version_conflict", "Бүртгэлийг өөр хэрэглэгч өөрчилсөн байна. Дахин ачаалаад оролдоно уу.", current_version=row.version)


def iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value else None


def money(value: Any) -> str | None:
    return None if value is None else str(value)


async def organization_timezone(db: AsyncSession, organization_id: int) -> str:
    organization = await db.get(Organization, organization_id)
    return (organization.timezone if organization else None) or "Asia/Ulaanbaatar"


async def get_party(db: AsyncSession, actor: ActorContext, party_id: int) -> ERPParty:
    party = await db.scalar(select(ERPParty).where(ERPParty.id == party_id, ERPParty.organization_id == actor.organization_id))
    if not party:
        raise crm_error(404, "crm_party_not_found", "Харилцагч олдсонгүй")
    return party


async def get_activity(db: AsyncSession, actor: ActorContext, activity_id: int) -> CRMActivity:
    activity = await db.scalar(select(CRMActivity).where(CRMActivity.id == activity_id, CRMActivity.organization_id == actor.organization_id))
    if not activity:
        raise crm_error(404, "crm_activity_not_found", "Харилцаа холбооны бүртгэл олдсонгүй")
    return activity


_REFERENCE_LABELS = {
    "group_id": (ERPPartyGroup, "Харилцагчийн бүлэг"),
    "payment_term_id": (ERPPaymentTerm, "Төлбөрийн нөхцөл"),
    "price_list_id": (ERPPriceList, "Үнийн жагсаалт"),
    "settlement_account_id": (ERPAccount, "Тооцооны данс"),
    "parent_party_id": (ERPParty, "Толгой харилцагч"),
    "party_id": (ERPParty, "Харилцагч"),
    "type_id": (CRMActivityType, "Төрөл"),
    "contract_id": (ContractDocument, "Гэрээ"),
    "project_id": (Project, "Төсөл / ажил"),
    "default_settlement_account_id": (ERPAccount, "Тооцооны данс"),
    "default_price_list_id": (ERPPriceList, "Үнийн жагсаалт"),
    "parent_id": (ERPPartyGroup, "Харьяа бүлэг"),
}
_EMPLOYEE_FIELDS = {"responsible_employee_id": "Хариуцагч", "reviewed_by_employee_id": "Хянасан ажилтан"}


async def validate_references(db: AsyncSession, organization_id: int, values: dict[str, Any]) -> None:
    """Reject ids that do not exist inside the actor's organization."""
    for field, value in values.items():
        if value is None:
            continue
        if field in _EMPLOYEE_FIELDS:
            exists = await db.scalar(select(Employee.id).where(Employee.id == value, Employee.organization_id == organization_id, Employee.deleted_at.is_(None)))
            label = _EMPLOYEE_FIELDS[field]
        elif field in _REFERENCE_LABELS:
            model, label = _REFERENCE_LABELS[field]
            exists = await db.scalar(select(model.id).where(model.id == value, model.organization_id == organization_id))
        else:
            continue
        if not exists:
            raise crm_error(422, "crm_invalid_reference", f"{label} олдсонгүй", field=field)


async def validate_status(db: AsyncSession, organization_id: int, status_id: int | None, register: str) -> ERPStatus | None:
    if status_id is None:
        return None
    status = await db.scalar(select(ERPStatus).where(ERPStatus.id == status_id, ERPStatus.organization_id == organization_id, ERPStatus.register == register))
    if not status:
        raise crm_error(422, "crm_invalid_reference", "Төлөв олдсонгүй", field="status_id")
    return status


async def validate_contact(db: AsyncSession, organization_id: int, contact_id: int | None, party_id: int | None) -> ERPPartyContact | None:
    if contact_id is None:
        return None
    contact = await db.scalar(select(ERPPartyContact).where(ERPPartyContact.id == contact_id, ERPPartyContact.organization_id == organization_id))
    if not contact or (party_id is not None and contact.party_id != party_id):
        raise crm_error(422, "crm_invalid_reference", "Холбоо барих хүн тухайн харилцагчид хамаарахгүй байна", field="contact_id")
    return contact


# ─── Party serialization ──────────────────────────────────────────────────────

async def _names(db: AsyncSession, model: Any, ids: set[int], label: str = "name") -> dict[int, Any]:
    ids = {value for value in ids if value}
    if not ids:
        return {}
    column = getattr(model, label)
    return dict((await db.execute(select(model.id, column).where(model.id.in_(ids)))).all())


async def party_context(db: AsyncSession, rows: list[ERPParty]) -> dict[str, dict[int, Any]]:
    return {
        "employees": await _names(db, Employee, {row.responsible_employee_id for row in rows}),
        "groups": await _names(db, ERPPartyGroup, {row.group_id for row in rows}),
        "terms": await _names(db, ERPPaymentTerm, {row.payment_term_id for row in rows}),
        "parents": await _names(db, ERPParty, {row.parent_party_id for row in rows}),
        "price_lists": await _names(db, ERPPriceList, {row.price_list_id for row in rows}),
        "accounts": await _names(db, ERPAccount, {row.settlement_account_id for row in rows}),
    }


def party_out(row: ERPParty, ctx: dict[str, dict[int, Any]] | None = None) -> dict[str, Any]:
    ctx = ctx or {}
    return {
        "id": row.id, "public_id": str(row.public_id), "code": row.code, "name": row.name, "name_en": row.name_en,
        "business_name": row.business_name, "party_type": row.party_type, "registry_no": row.registry_no, "tax_id": row.tax_id,
        "is_customer": row.is_customer, "is_supplier": row.is_supplier, "is_individual": row.is_individual, "is_foreign": row.is_foreign,
        "vat_payer": row.vat_payer, "city_tax_payer": row.city_tax_payer, "tax_status_checked_at": iso(row.tax_status_checked_at),
        "email": row.email, "phone": row.phone, "website": row.website, "legal_address": row.legal_address,
        "location": row.location, "informal_address": row.informal_address, "tags": list(row.tags or []),
        "group_id": row.group_id, "group_name": ctx.get("groups", {}).get(row.group_id),
        "responsible_employee_id": row.responsible_employee_id, "responsible_name": ctx.get("employees", {}).get(row.responsible_employee_id),
        "parent_party_id": row.parent_party_id, "parent_name": ctx.get("parents", {}).get(row.parent_party_id), "settle_via_parent": row.settle_via_parent,
        "customer_since": iso(row.customer_since), "inactive_since": iso(row.inactive_since),
        "payment_term_id": row.payment_term_id, "payment_term_name": ctx.get("terms", {}).get(row.payment_term_id),
        "price_list_id": row.price_list_id, "price_list_name": ctx.get("price_lists", {}).get(row.price_list_id),
        "settlement_account_id": row.settlement_account_id, "settlement_account_name": ctx.get("accounts", {}).get(row.settlement_account_id),
        "credit_limit": money(row.credit_limit), "currency": row.currency,
        "sales_discount_pct": money(row.sales_discount_pct), "sales_note": row.sales_note, "sales_lead_days": row.sales_lead_days,
        "purchase_discount_pct": money(row.purchase_discount_pct), "purchase_note": row.purchase_note, "purchase_lead_days": row.purchase_lead_days,
        "delivery_terms": row.delivery_terms, "links": list(row.links or []), "custom": row.custom or {},
        "is_active": row.status == "active", "status": row.status, "version": row.version,
        "created_at": iso(row.created_at), "updated_at": iso(row.updated_at),
    }


def contact_out(row: ERPPartyContact) -> dict[str, Any]:
    return {"id": row.id, "party_id": row.party_id, "name": row.name, "nickname": row.nickname, "position": row.position, "phone": row.phone,
            "email": row.email, "address": row.address, "note": row.note, "is_default": row.is_default, "is_active": row.is_active}


def bank_account_out(row: ERPPartyBankAccount) -> dict[str, Any]:
    return {"id": row.id, "party_id": row.party_id, "bank_name": row.bank_name, "currency": row.currency, "iban_prefix": row.iban_prefix,
            "account_no": row.account_no, "account_name": row.account_name, "note": row.note, "is_default": row.is_default, "is_active": row.is_active}


# ─── Activity serialization ───────────────────────────────────────────────────

async def activity_context(db: AsyncSession, rows: list[CRMActivity]) -> dict[str, dict[int, Any]]:
    status_ids = {row.status_id for row in rows if row.status_id}
    statuses = {}
    if status_ids:
        statuses = {row.id: row for row in (await db.execute(select(ERPStatus).where(ERPStatus.id.in_(status_ids)))).scalars().all()}
    party_ids = {row.party_id for row in rows if row.party_id}
    parties = {}
    if party_ids:
        parties = {row.id: (row.code, row.name) for row in (await db.execute(select(ERPParty).where(ERPParty.id.in_(party_ids)))).scalars().all()}
    return {
        "statuses": statuses,
        "parties": parties,
        "types": await _names(db, CRMActivityType, {row.type_id for row in rows}),
        "employees": await _names(db, Employee, {row.responsible_employee_id for row in rows} | {row.reviewed_by_employee_id for row in rows} | {row.created_by_employee_id for row in rows}),
        "contracts": await _names(db, ContractDocument, {row.contract_id for row in rows}, "title"),
        "projects": await _names(db, Project, {row.project_id for row in rows}),
        "tasks": await _names(db, Task, {row.task_id for row in rows}, "title"),
    }


def activity_out(row: CRMActivity, ctx: dict[str, dict[int, Any]], *, today: date, now: datetime) -> dict[str, Any]:
    status = ctx.get("statuses", {}).get(row.status_id)
    category = status.category if status else None
    party = ctx.get("parties", {}).get(row.party_id)
    employees = ctx.get("employees", {})
    return {
        "id": row.id, "public_id": str(row.public_id), "number": row.number,
        "party_id": row.party_id, "party_code": party[0] if party else None, "party_name": party[1] if party else None,
        "contact_id": row.contact_id, "contact_name": row.contact_name, "contact_phone": row.contact_phone, "contact_email": row.contact_email,
        "activity_at": iso(row.activity_at), "subject": row.subject, "body": row.body,
        "type_id": row.type_id, "type_name": ctx.get("types", {}).get(row.type_id), "is_important": row.is_important,
        "due_at": iso(row.due_at), "duration_minutes": row.duration_minutes,
        "responsible_employee_id": row.responsible_employee_id, "responsible_name": employees.get(row.responsible_employee_id),
        "status_id": row.status_id,
        "status": {"id": status.id, "name": status.name, "color": status.color, "category": status.category} if status else None,
        "completed_at": iso(row.completed_at), "completion_note": row.completion_note,
        "reference": row.reference, "contract_id": row.contract_id, "contract_title": ctx.get("contracts", {}).get(row.contract_id),
        "project_id": row.project_id, "project_name": ctx.get("projects", {}).get(row.project_id),
        "task_id": row.task_id, "task_title": ctx.get("tasks", {}).get(row.task_id),
        "is_closed": row.is_closed, "closed_at": iso(row.closed_at),
        "reviewed_by_employee_id": row.reviewed_by_employee_id, "reviewed_by_name": employees.get(row.reviewed_by_employee_id), "reviewed_at": iso(row.reviewed_at),
        "expected_revenue": money(row.expected_revenue), "currency": row.currency,
        "overdue_days": overdue_days(row.due_at, row.completed_at, today),
        "is_open": activity_is_open(is_closed=row.is_closed, completed_at=row.completed_at, status_category=category),
        "is_overdue": activity_is_overdue(is_closed=row.is_closed, completed_at=row.completed_at, status_category=category, due_at=row.due_at, now=now),
        "is_active": row.is_active, "custom": row.custom or {},
        "created_by_employee_id": row.created_by_employee_id, "created_by_name": employees.get(row.created_by_employee_id),
        "version": row.version, "created_at": iso(row.created_at), "updated_at": iso(row.updated_at),
    }


# ─── Attachments (Линк / файл) ────────────────────────────────────────────────

def attachment_out(row: Attachment) -> dict[str, Any]:
    return {"id": row.id, "filename": row.filename, "content_type": row.content_type, "size": row.size, "checksum": row.checksum,
            "scan_status": row.scan_status, "created_at": iso(row.created_at)}


async def list_object_attachments(db: AsyncSession, actor: ActorContext, object_type: str, object_id: int) -> list[dict[str, Any]]:
    rows = (await db.execute(select(Attachment).where(
        Attachment.organization_id == actor.organization_id, Attachment.object_type == object_type, Attachment.object_id == object_id,
    ).order_by(Attachment.created_at))).scalars().all()
    return [attachment_out(row) for row in rows]


async def store_object_attachment(db: AsyncSession, actor: ActorContext, object_type: str, object_id: int, file: UploadFile) -> dict[str, Any]:
    content = await file.read(settings.ATTACHMENT_MAX_BYTES + 1)
    if len(content) > settings.ATTACHMENT_MAX_BYTES:
        raise crm_error(413, "crm_attachment_too_large", "Файлын хэмжээ хэтэрсэн байна")
    if not content:
        raise crm_error(400, "crm_attachment_empty", "Файл хоосон байна")
    filename = (file.filename or "attachment").replace("\\", "/").split("/")[-1].strip()[:240] or "attachment"
    content_type = file.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    if content_type in {"application/x-msdownload", "application/x-sh", "application/x-executable"} or filename.lower().endswith((".exe", ".dll", ".bat", ".cmd", ".sh")):
        raise crm_error(415, "crm_attachment_blocked", "Гүйцэтгэх файл хавсаргах боломжгүй")
    try:
        scan_status = await scan_upload(content)
    except MalwareDetected as exc:
        raise crm_error(422, "crm_attachment_malware", str(exc)) from exc
    except MalwareScanUnavailable as exc:
        raise crm_error(503, "crm_attachment_scan_unavailable", str(exc)) from exc
    storage_key = f"{actor.organization_id}/{object_type}/{object_id}/{uuid.uuid4().hex}"
    checksum = hashlib.sha256(content).hexdigest()
    await put_attachment(storage_key, content, content_type)
    attachment = Attachment(organization_id=actor.organization_id, object_type=object_type, object_id=object_id, storage_key=storage_key,
                            filename=filename, content_type=content_type, size=len(content), checksum=checksum,
                            uploaded_by_account_id=actor.account_id, scan_status=scan_status)
    db.add(attachment)
    try:
        await db.flush()
        await record_change(db, actor=actor, topic="crm", aggregate_type="attachment", aggregate_id=attachment.id, operation="created",
                            after={"object_type": object_type, "object_id": object_id, "filename": filename, "size": len(content), "checksum": checksum})
        await db.commit()
    except Exception:
        await delete_attachment(storage_key)
        raise
    return attachment_out(attachment)


async def get_crm_attachment(db: AsyncSession, actor: ActorContext, attachment_id: int) -> Attachment:
    row = await db.get(Attachment, attachment_id)
    if not row or row.organization_id != actor.organization_id or row.object_type not in ATTACHMENT_OBJECT_TYPES.values():
        raise crm_error(404, "crm_attachment_not_found", "Файл олдсонгүй")
    return row


async def download_response(row: Attachment) -> Response:
    content = await get_attachment(row.storage_key)
    safe_name = row.filename.replace('"', "")
    return Response(content, media_type=row.content_type, headers={"Content-Disposition": f'attachment; filename="{safe_name}"', "X-Content-Type-Options": "nosniff"})
