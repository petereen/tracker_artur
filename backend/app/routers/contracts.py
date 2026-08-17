from __future__ import annotations

import hashlib
import json
import mimetypes
import uuid
from datetime import date, datetime, timezone
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.enterprise_deps import ActorContext, get_actor
from app.models.contracts import ContractComment, ContractDocument, ContractFile, ContractReview, ContractRevision
from app.models.models import AuditLog, Employee, Project, Task, UserAccount, UserNotification
from app.services.attachment_storage import delete_attachment, get_attachment, put_attachment
from app.services.enterprise_events import record_change
from app.services.malware_scanner import MalwareDetected, scan_upload
from app.services.user_notifications import create_notifications


router = APIRouter()
MANAGEMENT_ROLES = ("admin", "manager", "team_lead")
BODY_NODE_TYPES = {"doc", "paragraph", "heading", "bulletList", "orderedList", "listItem", "blockquote", "hardBreak", "text", "table", "tableRow", "tableCell", "tableHeader", "horizontalRule"}
BODY_MARK_TYPES = {"bold", "italic", "underline", "link"}
SUPPORTING_TYPES = {"application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "image/jpeg", "image/png", "image/tiff"}
FINAL_TYPES = {"application/pdf", "image/jpeg", "image/png", "image/tiff"}


class ContractBody(BaseModel):
    type: str = "doc"
    content: list[dict[str, Any]] = Field(default_factory=list)


class ContractCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    document_type: Literal["contract", "agreement", "official_letter", "other"]
    body_json: dict[str, Any]
    reviewer_account_ids: list[int] = Field(default_factory=list)
    project_id: int | None = None
    task_id: int | None = None
    effective_start_on: date | None = None
    effective_end_on: date | None = None

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Title is required")
        return value


class ContractPatch(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    document_type: Literal["contract", "agreement", "official_letter", "other"] | None = None
    body_json: dict[str, Any] | None = None
    reviewer_account_ids: list[int] | None = None
    project_id: int | None = None
    task_id: int | None = None
    effective_start_on: date | None = None
    effective_end_on: date | None = None


class ReviewInput(BaseModel):
    remark: str | None = Field(default=None, max_length=5000)


class CommentInput(BaseModel):
    body: str = Field(min_length=1, max_length=10000)
    revision_id: int
    parent_id: int | None = None
    anchor: dict[str, Any] | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_node(node: Any) -> dict[str, Any]:
    if not isinstance(node, dict) or node.get("type") not in BODY_NODE_TYPES:
        return {"type": "paragraph", "content": []}
    output: dict[str, Any] = {"type": node["type"]}
    attrs = node.get("attrs")
    if isinstance(attrs, dict) and node["type"] == "heading" and isinstance(attrs.get("level"), int) and 1 <= attrs["level"] <= 4:
        output["attrs"] = {"level": attrs["level"]}
    if isinstance(attrs, dict) and node["type"] == "link" and isinstance(attrs.get("href"), str):
        output["attrs"] = {"href": attrs["href"][:1000]}
    if node["type"] == "text":
        output["text"] = str(node.get("text", ""))[:10000]
        marks = []
        for mark in node.get("marks", []):
            if isinstance(mark, dict) and mark.get("type") in BODY_MARK_TYPES:
                if mark["type"] == "link" and isinstance(mark.get("attrs"), dict):
                    marks.append({"type": "link", "attrs": {"href": str(mark["attrs"].get("href", ""))[:1000]}})
                else:
                    marks.append({"type": mark["type"]})
        if marks:
            output["marks"] = marks
    children = node.get("content")
    if isinstance(children, list) and node["type"] != "text":
        output["content"] = [_normalize_node(child) for child in children[:2000]]
    return output


def _normalize_body(value: dict[str, Any]) -> dict[str, Any]:
    root = _normalize_node(value)
    if root["type"] != "doc":
        root = {"type": "doc", "content": [root]}
    root.setdefault("content", [])
    return root


def _plain_text(value: Any) -> str:
    if isinstance(value, dict):
        parts = []
        if isinstance(value.get("text"), str):
            parts.append(value["text"])
        for child in value.get("content", []) or []:
            parts.append(_plain_text(child))
        return " ".join(part for part in parts if part).strip()
    if isinstance(value, list):
        return " ".join(_plain_text(item) for item in value).strip()
    return ""


def _checksum(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


async def _candidate_accounts(db: AsyncSession, organization_id: int, account_ids: list[int]) -> list[tuple[UserAccount, Employee]]:
    if not account_ids:
        return []
    rows = (await db.execute(
        select(UserAccount, Employee)
        .join(Employee, Employee.id == UserAccount.employee_id)
        .where(UserAccount.organization_id == organization_id, UserAccount.id.in_(set(account_ids)), UserAccount.status == "active", Employee.is_active.is_(True))
    )).all()
    by_id = {account.id: (account, employee) for account, employee in rows}
    if set(by_id) != set(account_ids):
        raise HTTPException(status_code=422, detail="All reviewers must be active employees in this organization")
    return [by_id[account_id] for account_id in dict.fromkeys(account_ids)]


async def _get_contract(db: AsyncSession, public_id: UUID, actor: ActorContext, *, lock: bool = False) -> ContractDocument:
    query = select(ContractDocument).where(ContractDocument.public_id == public_id, ContractDocument.organization_id == actor.organization_id)
    if lock:
        query = query.with_for_update()
    contract = await db.scalar(query)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    if actor.has_any_role("admin"):
        return contract
    participant = await db.scalar(select(ContractReview.id).where(ContractReview.contract_id == contract.id, ContractReview.reviewer_account_id == actor.account_id).limit(1))
    if contract.author_account_id != actor.account_id and not participant:
        raise HTTPException(status_code=404, detail="Contract not found")
    return contract


def _can_edit(contract: ContractDocument, actor: ActorContext) -> bool:
    return contract.author_account_id == actor.account_id and contract.status in {"DRAFT", "CHANGES_REQUESTED"}


async def _assert_links(db: AsyncSession, actor: ActorContext, project_id: int | None, task_id: int | None) -> None:
    project = await db.get(Project, project_id) if project_id else None
    task = await db.get(Task, task_id) if task_id else None
    if project_id and (not project or project.organization_id != actor.organization_id):
        raise HTTPException(status_code=422, detail="Project not found in this organization")
    if task_id and (not task or task.organization_id != actor.organization_id):
        raise HTTPException(status_code=422, detail="Task not found in this organization")
    if task and project_id and task.project_id != project_id:
        raise HTTPException(status_code=422, detail="Task does not belong to the selected project")


def _validate_dates(start: date | None, end: date | None) -> None:
    if start and end and end < start:
        raise HTTPException(status_code=422, detail="Effective end date must not precede the start date")


async def _new_revision(db: AsyncSession, contract: ContractDocument, *, title: str, document_type: str, body_json: dict[str, Any], project_id: int | None, task_id: int | None, effective_start_on: date | None, effective_end_on: date | None, actor: ActorContext) -> ContractRevision:
    body = _normalize_body(body_json)
    plain = _plain_text(body)
    if not plain:
        raise HTTPException(status_code=422, detail="Document body is required")
    _validate_dates(effective_start_on, effective_end_on)
    previous = await db.scalar(select(ContractRevision.revision_number).where(ContractRevision.contract_id == contract.id).order_by(ContractRevision.revision_number.desc()).limit(1))
    revision = ContractRevision(contract_id=contract.id, revision_number=(previous or 0) + 1, title=title.strip(), document_type=document_type, body_json=body, plain_text=plain, project_id=project_id, task_id=task_id, effective_start_on=effective_start_on, effective_end_on=effective_end_on, checksum=_checksum(body), author_account_id=actor.account_id)
    db.add(revision)
    await db.flush()
    contract.title = revision.title
    contract.document_type = revision.document_type
    contract.project_id = project_id
    contract.task_id = task_id
    contract.effective_start_on = effective_start_on
    contract.effective_end_on = effective_end_on
    contract.current_revision_id = revision.id
    contract.version += 1
    return revision


def _contract_summary(contract: ContractDocument, revision: ContractRevision | None, *, author_name: str | None = None) -> dict[str, Any]:
    return {
        "id": contract.id,
        "public_id": str(contract.public_id),
        "title": contract.title,
        "document_type": contract.document_type,
        "status": contract.status,
        "author_account_id": contract.author_account_id,
        "author_name": author_name,
        "project_id": contract.project_id,
        "task_id": contract.task_id,
        "effective_start_on": contract.effective_start_on,
        "effective_end_on": contract.effective_end_on,
        "submission_round": contract.submission_round,
        "version": contract.version,
        "current_revision_id": contract.current_revision_id,
        "approved_revision_id": contract.approved_revision_id,
        "approved_at": contract.approved_at,
        "signed_at": contract.signed_at,
        "updated_at": contract.updated_at,
        "created_at": contract.created_at,
        "excerpt": (revision.plain_text[:220] if revision else ""),
    }


async def _notify_submit(db: AsyncSession, actor: ActorContext, contract: ContractDocument, event_id: int, reviewer_ids: list[int], author_name: str) -> None:
    await create_notifications(db, organization_id=actor.organization_id, account_ids=reviewer_ids, kind="contract_submitted", title="Шинэ гэрээ хянахаар ирлээ", body=f"{author_name} танд шинэ гэрээ/баримт бичиг хянахаар илгээлээ.", target_url=f"/contracts/{contract.public_id}", payload={"contract_id": contract.id, "public_id": str(contract.public_id)}, source_event_id=event_id, dedup_key=f"contract-submit:{contract.id}:round:{contract.submission_round}")


async def _participant_account_ids(db: AsyncSession, contract_id: int, author_account_id: int) -> list[int]:
    reviewer_ids = (await db.execute(select(ContractReview.reviewer_account_id).where(ContractReview.contract_id == contract_id))).scalars().all()
    return list(dict.fromkeys([author_account_id, *reviewer_ids]))


@router.get("/contracts/reviewer-candidates")
async def reviewer_candidates(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    rows = (await db.execute(select(UserAccount, Employee).join(Employee, Employee.id == UserAccount.employee_id).where(UserAccount.organization_id == actor.organization_id, UserAccount.status == "active", Employee.is_active.is_(True)).order_by(Employee.name))).all()
    return [{"account_id": account.id, "employee_id": employee.id, "name": employee.name, "job_title": employee.job_title} for account, employee in rows]


@router.get("/contracts")
async def list_contracts(view: Literal["all", "drafts", "pending_my_approval", "submitted_by_me", "approved", "signed", "returned"] = "all", search: str | None = None, document_type: str | None = None, project_id: int | None = None, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    participant = exists(select(ContractReview.id).where(ContractReview.contract_id == ContractDocument.id, ContractReview.reviewer_account_id == actor.account_id))
    query = select(ContractDocument, ContractRevision, Employee.name).outerjoin(ContractRevision, ContractRevision.id == ContractDocument.current_revision_id).outerjoin(Employee, Employee.id == ContractDocument.author_employee_id).where(ContractDocument.organization_id == actor.organization_id)
    if not actor.has_any_role("admin"):
        query = query.where(or_(ContractDocument.author_account_id == actor.account_id, participant))
    if search:
        query = query.where(ContractDocument.title.ilike(f"%{search.strip()}%"))
    if document_type:
        query = query.where(ContractDocument.document_type == document_type)
    if project_id:
        query = query.where(ContractDocument.project_id == project_id)
    rows = (await db.execute(query.order_by(ContractDocument.updated_at.desc(), ContractDocument.id.desc()).limit(500))).all()
    pending_ids = set((await db.execute(select(ContractReview.contract_id).where(ContractReview.reviewer_account_id == actor.account_id, ContractReview.decision == "pending", ContractReview.round_number == ContractDocument.submission_round).join(ContractDocument, ContractDocument.id == ContractReview.contract_id, isouter=False))).scalars().all())
    def matches(key: str, contract: ContractDocument) -> bool:
        return key == "all" or (key == "drafts" and contract.author_account_id == actor.account_id and contract.status == "DRAFT") or (key == "pending_my_approval" and contract.status == "PENDING_REVIEW" and contract.id in pending_ids) or (key == "submitted_by_me" and contract.author_account_id == actor.account_id and contract.status == "PENDING_REVIEW") or (key == "approved" and contract.status == "APPROVED") or (key == "signed" and contract.status == "SIGNED_AND_STAMPED") or (key == "returned" and contract.status in ("CHANGES_REQUESTED", "REJECTED"))
    counts = {key: sum(1 for contract, _, _ in rows if matches(key, contract)) for key in ("all", "drafts", "pending_my_approval", "submitted_by_me", "approved", "signed", "returned")}
    visible = [row for row in rows if matches(view, row[0])]
    return {"items": [_contract_summary(contract, revision, author_name) for contract, revision, author_name in visible], "counts": counts}


@router.post("/contracts", status_code=status.HTTP_201_CREATED)
async def create_contract(data: ContractCreate, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    if actor.employee_id is None:
        raise HTTPException(status_code=403, detail="An employee-linked account is required to draft contracts")
    await _assert_links(db, actor, data.project_id, data.task_id)
    reviewers = await _candidate_accounts(db, actor.organization_id, data.reviewer_account_ids)
    if actor.account_id in {account.id for account, _ in reviewers}:
        raise HTTPException(status_code=422, detail="The author cannot be their own reviewer")
    _validate_dates(data.effective_start_on, data.effective_end_on)
    contract = ContractDocument(organization_id=actor.organization_id, author_account_id=actor.account_id, author_employee_id=actor.employee_id, title=data.title.strip(), document_type=data.document_type, project_id=data.project_id, task_id=data.task_id, effective_start_on=data.effective_start_on, effective_end_on=data.effective_end_on, reviewer_account_ids=[account.id for account, _ in reviewers])
    db.add(contract)
    await db.flush()
    revision = await _new_revision(db, contract, title=data.title, document_type=data.document_type, body_json=data.body_json, project_id=data.project_id, task_id=data.task_id, effective_start_on=data.effective_start_on, effective_end_on=data.effective_end_on, actor=actor)
    event = await record_change(db, actor=actor, topic="contracts", aggregate_type="contract_document", aggregate_id=contract.id, operation="draft_created", version=contract.version, after={"status": contract.status, "revision_id": revision.id})
    await db.commit()
    return _contract_summary(contract, revision)


@router.get("/contracts/{public_id}")
async def get_contract(public_id: UUID, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    contract = await _get_contract(db, public_id, actor)
    revision = await db.get(ContractRevision, contract.current_revision_id) if contract.current_revision_id else None
    approved_revision = await db.get(ContractRevision, contract.approved_revision_id) if contract.approved_revision_id else None
    revisions = (await db.execute(select(ContractRevision).where(ContractRevision.contract_id == contract.id).order_by(ContractRevision.revision_number))).scalars().all()
    reviews = (await db.execute(select(ContractReview).where(ContractReview.contract_id == contract.id).order_by(ContractReview.round_number, ContractReview.id))).scalars().all()
    comments = (await db.execute(select(ContractComment).where(ContractComment.contract_id == contract.id).order_by(ContractComment.created_at))).scalars().all()
    files = (await db.execute(select(ContractFile).where(ContractFile.contract_id == contract.id).order_by(ContractFile.created_at))).scalars().all()
    events = (await db.execute(select(AuditLog).where(AuditLog.organization_id == actor.organization_id, AuditLog.entity_id == contract.id, AuditLog.entity_type == "contract_document").order_by(AuditLog.created_at))).scalars().all()
    return {**_contract_summary(contract, revision), "body_json": revision.body_json if revision else None, "approved_body_json": approved_revision.body_json if approved_revision else None, "reviewer_account_ids": contract.reviewer_account_ids or [], "revisions": [{"id": row.id, "revision_number": row.revision_number, "title": row.title, "body_json": row.body_json, "plain_text": row.plain_text, "checksum": row.checksum, "created_at": row.created_at, "author_account_id": row.author_account_id} for row in revisions], "reviews": [{"id": row.id, "round_number": row.round_number, "reviewer_account_id": row.reviewer_account_id, "reviewer_employee_id": row.reviewer_employee_id, "reviewer_name": row.reviewer_name_snapshot, "decision": row.decision, "remark": row.remark, "acted_at": row.acted_at} for row in reviews], "comments": [{"id": row.id, "revision_id": row.revision_id, "parent_id": row.parent_id, "author_account_id": row.author_account_id, "body": row.body, "anchor": row.anchor, "is_resolved": row.is_resolved, "created_at": row.created_at} for row in comments], "files": [{"id": row.id, "purpose": row.purpose, "filename": row.filename, "content_type": row.content_type, "size": row.size, "checksum": row.checksum, "scan_status": row.scan_status, "confirmed_at": row.confirmed_at, "created_at": row.created_at} for row in files], "timeline": [{"id": row.id, "operation": row.action, "actor_account_id": row.actor_account_id, "before": row.before_data, "after": row.after_data, "created_at": row.created_at} for row in events]}


@router.patch("/contracts/{public_id}")
async def update_contract(public_id: UUID, data: ContractPatch, if_match: str | None = Header(default=None, alias="If-Match"), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    contract = await _get_contract(db, public_id, actor, lock=True)
    if if_match and if_match.strip('W/"') != str(contract.version):
        raise HTTPException(status_code=409, detail={"message": "Contract changed", "latest_version": contract.version})
    if not _can_edit(contract, actor):
        raise HTTPException(status_code=409, detail="Only draft or changes-requested contracts can be edited by the author")
    current = await db.get(ContractRevision, contract.current_revision_id)
    if not current:
        raise HTTPException(status_code=409, detail="Contract has no current revision")
    values = data.model_dump(exclude_unset=True)
    await _assert_links(db, actor, values.get("project_id", contract.project_id), values.get("task_id", contract.task_id))
    reviewers = await _candidate_accounts(db, actor.organization_id, values.get("reviewer_account_ids", contract.reviewer_account_ids or []))
    if actor.account_id in {account.id for account, _ in reviewers}:
        raise HTTPException(status_code=422, detail="The author cannot be their own reviewer")
    title = values.get("title", current.title)
    document_type = values.get("document_type", current.document_type)
    body = values.get("body_json", current.body_json)
    project_id = values.get("project_id", current.project_id)
    task_id = values.get("task_id", current.task_id)
    start = values.get("effective_start_on", current.effective_start_on)
    end = values.get("effective_end_on", current.effective_end_on)
    contract.reviewer_account_ids = [account.id for account, _ in reviewers]
    revision = await _new_revision(db, contract, title=title, document_type=document_type, body_json=body, project_id=project_id, task_id=task_id, effective_start_on=start, effective_end_on=end, actor=actor)
    await record_change(db, actor=actor, topic="contracts", aggregate_type="contract_document", aggregate_id=contract.id, operation="draft_saved", version=contract.version, after={"revision_id": revision.id, "status": contract.status})
    await db.commit()
    return _contract_summary(contract, revision)


@router.delete("/contracts/{public_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contract(public_id: UUID, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    contract = await _get_contract(db, public_id, actor, lock=True)
    if contract.author_account_id != actor.account_id or contract.status not in {"DRAFT", "CHANGES_REQUESTED"}:
        raise HTTPException(status_code=409, detail="Only the author can delete an editable contract")
    files = (await db.execute(select(ContractFile).where(ContractFile.contract_id == contract.id))).scalars().all()
    keys = [row.storage_key for row in files]
    await db.delete(contract)
    await db.commit()
    for key in keys:
        await delete_attachment(key)


@router.post("/contracts/{public_id}/duplicate", status_code=status.HTTP_201_CREATED)
async def duplicate_contract(public_id: UUID, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    source = await _get_contract(db, public_id, actor)
    if source.status != "REJECTED":
        raise HTTPException(status_code=409, detail="Only rejected contracts can be duplicated")
    source_revision = await db.get(ContractRevision, source.current_revision_id)
    if not source_revision:
        raise HTTPException(status_code=409, detail="Rejected contract has no revision")
    duplicate = ContractDocument(organization_id=actor.organization_id, author_account_id=actor.account_id, author_employee_id=actor.employee_id, title=f"{source.title} (Хуулбар)", document_type=source.document_type, project_id=source.project_id, task_id=source.task_id, effective_start_on=source.effective_start_on, effective_end_on=source.effective_end_on, reviewer_account_ids=source.reviewer_account_ids or [])
    db.add(duplicate)
    await db.flush()
    revision = await _new_revision(db, duplicate, title=duplicate.title, document_type=duplicate.document_type, body_json=source_revision.body_json, project_id=duplicate.project_id, task_id=duplicate.task_id, effective_start_on=duplicate.effective_start_on, effective_end_on=duplicate.effective_end_on, actor=actor)
    await record_change(db, actor=actor, topic="contracts", aggregate_type="contract_document", aggregate_id=duplicate.id, operation="duplicated", version=duplicate.version, after={"source_id": source.id, "revision_id": revision.id})
    await db.commit()
    return _contract_summary(duplicate, revision)


async def _submit(public_id: UUID, db: AsyncSession, actor: ActorContext, *, resubmit: bool):
    contract = await _get_contract(db, public_id, actor, lock=True)
    expected = "CHANGES_REQUESTED" if resubmit else "DRAFT"
    if contract.author_account_id != actor.account_id or contract.status != expected:
        raise HTTPException(status_code=409, detail=f"Contract must be in {expected} and owned by the author")
    reviewer_ids = [int(value) for value in contract.reviewer_account_ids or []]
    reviewers = await _candidate_accounts(db, actor.organization_id, reviewer_ids)
    if not reviewers:
        raise HTTPException(status_code=422, detail="Select at least one reviewer before submitting")
    if contract.current_revision_id is None:
        raise HTTPException(status_code=409, detail="Contract has no current revision")
    contract.submission_round += 1
    contract.status = "PENDING_REVIEW"
    contract.version += 1
    current_revision = await db.get(ContractRevision, contract.current_revision_id)
    for account, employee in reviewers:
        db.add(ContractReview(contract_id=contract.id, round_number=contract.submission_round, revision_id=current_revision.id, reviewer_account_id=account.id, reviewer_employee_id=employee.id, reviewer_name_snapshot=employee.name))
    operation = "resubmitted" if resubmit else "submitted"
    event = await record_change(db, actor=actor, topic="contracts", aggregate_type="contract_document", aggregate_id=contract.id, operation=operation, version=contract.version, after={"status": contract.status, "round": contract.submission_round, "revision_id": current_revision.id})
    author = await db.get(Employee, actor.employee_id) if actor.employee_id else None
    await _notify_submit(db, actor, contract, event.id, reviewer_ids, author.name if author else actor.email)
    await db.commit()
    return {"id": contract.id, "public_id": str(contract.public_id), "status": contract.status, "submission_round": contract.submission_round, "version": contract.version}


@router.post("/contracts/{public_id}/submit")
async def submit_contract(public_id: UUID, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    return await _submit(public_id, db, actor, resubmit=False)


@router.post("/contracts/{public_id}/resubmit")
async def resubmit_contract(public_id: UUID, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    return await _submit(public_id, db, actor, resubmit=True)


@router.post("/contracts/{public_id}/recall")
async def recall_contract(public_id: UUID, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    contract = await _get_contract(db, public_id, actor, lock=True)
    if contract.author_account_id != actor.account_id or contract.status != "PENDING_REVIEW":
        raise HTTPException(status_code=409, detail="Only a pending submission can be recalled")
    acted = await db.scalar(select(ContractReview.id).where(ContractReview.contract_id == contract.id, ContractReview.round_number == contract.submission_round, ContractReview.decision != "pending").limit(1))
    if acted:
        raise HTTPException(status_code=409, detail="A reviewer has already acted on this submission")
    reviewer_ids = (await db.execute(select(ContractReview.reviewer_account_id).where(ContractReview.contract_id == contract.id, ContractReview.round_number == contract.submission_round))).scalars().all()
    stale_notifications = (await db.execute(select(UserNotification).where(UserNotification.recipient_account_id.in_(reviewer_ids), UserNotification.kind == "contract_submitted", UserNotification.read_at.is_(None)))).scalars().all()
    for notification in stale_notifications:
        if isinstance(notification.payload, dict) and notification.payload.get("contract_id") == contract.id:
            notification.read_at = _now()
    contract.status = "DRAFT"
    contract.version += 1
    await record_change(db, actor=actor, topic="contracts", aggregate_type="contract_document", aggregate_id=contract.id, operation="recalled", version=contract.version, after={"status": contract.status})
    await db.commit()
    return {"id": contract.id, "status": contract.status, "version": contract.version}


async def _review(public_id: UUID, data: ReviewInput, action: Literal["approve", "request-changes", "reject"], db: AsyncSession, actor: ActorContext):
    contract = await _get_contract(db, public_id, actor, lock=True)
    if contract.status != "PENDING_REVIEW":
        raise HTTPException(status_code=409, detail="Only pending contracts can be reviewed")
    review = await db.scalar(select(ContractReview).where(ContractReview.contract_id == contract.id, ContractReview.round_number == contract.submission_round, ContractReview.reviewer_account_id == actor.account_id).with_for_update())
    if not review:
        raise HTTPException(status_code=403, detail="You are not assigned to this review round")
    if review.decision != "pending":
        raise HTTPException(status_code=409, detail="You have already acted on this review")
    remark = (data.remark or "").strip() or None
    if action in {"request-changes", "reject"} and not remark:
        raise HTTPException(status_code=422, detail="A mandatory reviewer reason is required")
    review.decision = {"approve": "approved", "request-changes": "changes_requested", "reject": "rejected"}[action]
    review.remark = remark
    review.acted_at = _now()
    contract.version += 1
    final_approval = False
    if action == "request-changes":
        contract.status = "CHANGES_REQUESTED"
    elif action == "reject":
        contract.status = "REJECTED"
    else:
        remaining = await db.scalar(select(ContractReview.id).where(ContractReview.contract_id == contract.id, ContractReview.round_number == contract.submission_round, ContractReview.decision != "approved").limit(1))
        if not remaining:
            contract.status = "APPROVED"
            contract.approved_revision_id = contract.current_revision_id
            contract.approved_at = _now()
            final_approval = True
    operation = {"approve": "review_approved", "request-changes": "changes_requested", "reject": "rejected"}[action]
    event = await record_change(db, actor=actor, topic="contracts", aggregate_type="contract_document", aggregate_id=contract.id, operation=operation, version=contract.version, after={"status": contract.status, "review_id": review.id, "remark": remark})
    if action == "request-changes":
        await create_notifications(db, organization_id=actor.organization_id, account_ids=[contract.author_account_id], kind="contract_changes_requested", title="Гэрээнд засвар шаардлагатай", body=f"{review.reviewer_name_snapshot} таны баримтад засвар хийх санал илгээлээ.", target_url=f"/contracts/{contract.public_id}", payload={"contract_id": contract.id}, source_event_id=event.id, dedup_key=f"contract-changes:{contract.id}:v{contract.version}")
    elif action == "reject":
        await create_notifications(db, organization_id=actor.organization_id, account_ids=[contract.author_account_id], kind="contract_rejected", title="Баримт буцаагдлаа", body=f"Таны илгээсэн {contract.title} буцаагдлаа.", target_url=f"/contracts/{contract.public_id}", payload={"contract_id": contract.id}, source_event_id=event.id, dedup_key=f"contract-rejected:{contract.id}:v{contract.version}")
    elif final_approval:
        await create_notifications(db, organization_id=actor.organization_id, account_ids=[contract.author_account_id], kind="contract_approved", title="Гэрээ батлагдлаа", body=f"Таны илгээсэн {contract.title} батлагдлаа. Баримтыг хэвлэж, тамга гарын үсэг зурж баталгаажуулна уу.", target_url=f"/contracts/{contract.public_id}?approved=1", payload={"contract_id": contract.id, "approved": True}, source_event_id=event.id, dedup_key=f"contract-approved:{contract.id}:v{contract.version}")
    await db.commit()
    return {"id": contract.id, "status": contract.status, "version": contract.version, "final_approval": final_approval}


@router.post("/contracts/{public_id}/approve")
async def approve_contract(public_id: UUID, data: ReviewInput = ReviewInput(), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    return await _review(public_id, data, "approve", db, actor)


@router.post("/contracts/{public_id}/request-changes")
async def request_contract_changes(public_id: UUID, data: ReviewInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    return await _review(public_id, data, "request-changes", db, actor)


@router.post("/contracts/{public_id}/reject")
async def reject_contract(public_id: UUID, data: ReviewInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    return await _review(public_id, data, "reject", db, actor)


@router.post("/contracts/{public_id}/comments", status_code=status.HTTP_201_CREATED)
async def add_contract_comment(public_id: UUID, data: CommentInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    contract = await _get_contract(db, public_id, actor)
    if contract.status not in {"PENDING_REVIEW", "CHANGES_REQUESTED"}:
        raise HTTPException(status_code=409, detail="Comments are locked after the review decision")
    revision = await db.get(ContractRevision, data.revision_id)
    if not revision or revision.contract_id != contract.id:
        raise HTTPException(status_code=404, detail="Revision not found")
    if data.parent_id:
        parent = await db.get(ContractComment, data.parent_id)
        if not parent or parent.contract_id != contract.id:
            raise HTTPException(status_code=404, detail="Parent comment not found")
    comment = ContractComment(contract_id=contract.id, revision_id=data.revision_id, parent_id=data.parent_id, author_account_id=actor.account_id, anchor=data.anchor, body=data.body.strip())
    db.add(comment)
    await db.flush()
    await record_change(db, actor=actor, topic="contracts", aggregate_type="contract_document", aggregate_id=contract.id, operation="comment_added", version=contract.version, after={"comment_id": comment.id, "revision_id": revision.id})
    await db.commit()
    return {"id": comment.id, "revision_id": comment.revision_id, "parent_id": comment.parent_id, "body": comment.body, "anchor": comment.anchor, "author_account_id": comment.author_account_id, "is_resolved": comment.is_resolved, "created_at": comment.created_at}


@router.patch("/contracts/{public_id}/comments/{comment_id}")
async def resolve_contract_comment(public_id: UUID, comment_id: int, is_resolved: bool, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    contract = await _get_contract(db, public_id, actor)
    if contract.status not in {"PENDING_REVIEW", "CHANGES_REQUESTED"}:
        raise HTTPException(status_code=409, detail="Comments are locked after the review decision")
    comment = await db.get(ContractComment, comment_id)
    if not comment or comment.contract_id != contract.id:
        raise HTTPException(status_code=404, detail="Comment not found")
    comment.is_resolved = is_resolved
    await record_change(db, actor=actor, topic="contracts", aggregate_type="contract_document", aggregate_id=contract.id, operation="comment_resolved" if is_resolved else "comment_reopened", version=contract.version, after={"comment_id": comment.id})
    await db.commit()
    return {"id": comment.id, "is_resolved": comment.is_resolved}


async def _contract_file_access(db: AsyncSession, public_id: UUID, actor: ActorContext, purpose: str, *, write: bool = False) -> ContractDocument:
    contract = await _get_contract(db, public_id, actor)
    is_author = contract.author_account_id == actor.account_id
    reviewer = bool(await db.scalar(select(ContractReview.id).where(ContractReview.contract_id == contract.id, ContractReview.reviewer_account_id == actor.account_id)))
    if purpose == "supporting" and (not write or not (is_author and contract.status in {"DRAFT", "CHANGES_REQUESTED"})):
        if write:
            raise HTTPException(status_code=409, detail="Supporting files are locked")
    if purpose == "signed_final" and write and not ((is_author or reviewer) and contract.status == "APPROVED"):
        raise HTTPException(status_code=409, detail="Final execution files are available only to participants after approval")
    return contract


@router.post("/contracts/{public_id}/files", status_code=status.HTTP_201_CREATED)
async def upload_contract_file(public_id: UUID, purpose: Literal["supporting", "signed_final"], file: UploadFile = File(...), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    contract = await _contract_file_access(db, public_id, actor, purpose, write=True)
    content = await file.read(settings.ATTACHMENT_MAX_BYTES + 1)
    if not content:
        raise HTTPException(status_code=400, detail="Attachment is empty")
    if len(content) > settings.ATTACHMENT_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Attachment exceeds configured size limit")
    filename = (file.filename or "attachment").replace("\\", "/").split("/")[-1].strip()[:240] or "attachment"
    content_type = file.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    allowed = FINAL_TYPES if purpose == "signed_final" else SUPPORTING_TYPES
    if content_type not in allowed:
        raise HTTPException(status_code=415, detail="Unsupported contract attachment type")
    try:
        scan_status = await scan_upload(content)
    except MalwareDetected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if purpose == "signed_final":
        old = (await db.execute(select(ContractFile).where(ContractFile.contract_id == contract.id, ContractFile.purpose == "signed_final", ContractFile.confirmed_at.is_(None)))).scalars().all()
        old_keys = [row.storage_key for row in old]
        for row in old:
            await db.delete(row)
        await db.flush()
    else:
        old_keys = []
    storage_key = f"{actor.organization_id}/contracts/{contract.id}/{uuid.uuid4().hex}"
    checksum = hashlib.sha256(content).hexdigest()
    await put_attachment(storage_key, content, content_type)
    uploaded = ContractFile(contract_id=contract.id, purpose=purpose, storage_key=storage_key, filename=filename, content_type=content_type, size=len(content), checksum=checksum, scan_status=scan_status, uploaded_by_account_id=actor.account_id)
    db.add(uploaded)
    try:
        await db.flush()
        await record_change(db, actor=actor, topic="contracts", aggregate_type="contract_document", aggregate_id=contract.id, operation="file_uploaded", version=contract.version, after={"file_id": uploaded.id, "purpose": purpose, "filename": filename})
        await db.commit()
    except Exception:
        await delete_attachment(storage_key)
        raise
    for key in old_keys:
        await delete_attachment(key)
    return {"id": uploaded.id, "purpose": purpose, "filename": uploaded.filename, "content_type": uploaded.content_type, "size": uploaded.size, "checksum": uploaded.checksum, "scan_status": uploaded.scan_status, "confirmed_at": uploaded.confirmed_at}


@router.get("/contracts/{public_id}/files/{file_id}/download")
async def download_contract_file(public_id: UUID, file_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    contract = await _get_contract(db, public_id, actor)
    item = await db.get(ContractFile, file_id)
    if not item or item.contract_id != contract.id:
        raise HTTPException(status_code=404, detail="Contract file not found")
    content = await get_attachment(item.storage_key)
    return Response(content, media_type=item.content_type, headers={"Content-Disposition": f'attachment; filename="{item.filename.replace(chr(34), "")}"', "X-Content-Type-Options": "nosniff"})


@router.delete("/contracts/{public_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contract_file(public_id: UUID, file_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    contract = await _get_contract(db, public_id, actor, lock=True)
    item = await db.get(ContractFile, file_id, with_for_update=True)
    if not item or item.contract_id != contract.id:
        raise HTTPException(status_code=404, detail="Contract file not found")
    is_reviewer = bool(await db.scalar(select(ContractReview.id).where(ContractReview.contract_id == contract.id, ContractReview.reviewer_account_id == actor.account_id)))
    permitted = (item.purpose == "supporting" and contract.author_account_id == actor.account_id and contract.status in {"DRAFT", "CHANGES_REQUESTED"}) or (item.purpose == "signed_final" and not item.confirmed_at and (contract.author_account_id == actor.account_id or is_reviewer) and contract.status == "APPROVED")
    if not permitted:
        raise HTTPException(status_code=409, detail="This contract file is immutable")
    key = item.storage_key
    await db.delete(item)
    await db.commit()
    await delete_attachment(key)


@router.post("/contracts/{public_id}/mark-printed")
async def mark_contract_printed(public_id: UUID, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    contract = await _get_contract(db, public_id, actor, lock=True)
    if contract.status != "APPROVED":
        raise HTTPException(status_code=409, detail="Only approved contracts can be printed")
    contract.printed_at = _now()
    contract.printed_by_account_id = actor.account_id
    await record_change(db, actor=actor, topic="contracts", aggregate_type="contract_document", aggregate_id=contract.id, operation="printed", version=contract.version, after={"printed_at": contract.printed_at})
    await db.commit()
    return {"id": contract.id, "printed_at": contract.printed_at}


@router.post("/contracts/{public_id}/confirm-final")
async def confirm_contract_final(public_id: UUID, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    contract = await _get_contract(db, public_id, actor, lock=True)
    if contract.status != "APPROVED":
        raise HTTPException(status_code=409, detail="Only approved contracts can be archived")
    is_reviewer = bool(await db.scalar(select(ContractReview.id).where(ContractReview.contract_id == contract.id, ContractReview.reviewer_account_id == actor.account_id)))
    if contract.author_account_id != actor.account_id and not is_reviewer:
        raise HTTPException(status_code=403, detail="Only the author or a reviewer can archive this contract")
    item = await db.scalar(select(ContractFile).where(ContractFile.contract_id == contract.id, ContractFile.purpose == "signed_final", ContractFile.confirmed_at.is_(None)).order_by(ContractFile.created_at.desc()).with_for_update())
    if not item:
        raise HTTPException(status_code=422, detail="Upload a signed and stamped final copy first")
    if item.scan_status not in {"accepted", "disabled"}:
        raise HTTPException(status_code=422, detail="The final copy must pass malware scanning before archival")
    item.confirmed_at = _now()
    contract.signed_final_file_id = item.id
    contract.signed_at = item.confirmed_at
    contract.status = "SIGNED_AND_STAMPED"
    contract.version += 1
    event = await record_change(db, actor=actor, topic="contracts", aggregate_type="contract_document", aggregate_id=contract.id, operation="signed_and_archived", version=contract.version, after={"status": contract.status, "file_id": item.id})
    participants = await _participant_account_ids(db, contract.id, contract.author_account_id)
    await create_notifications(db, organization_id=actor.organization_id, account_ids=participants, exclude_employee_id=actor.employee_id, kind="contract_signed", title="Гэрээ архивлагдлаа", body=f"{contract.title} гарын үсэг, тамгатайгаар архивлагдлаа.", target_url=f"/contracts/{contract.public_id}", payload={"contract_id": contract.id}, source_event_id=event.id, dedup_key=f"contract-signed:{contract.id}:v{contract.version}")
    await db.commit()
    return {"id": contract.id, "status": contract.status, "signed_at": contract.signed_at, "file_id": item.id}
