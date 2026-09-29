"""Budgets (Төсөв): scenarios, the period grid, approval workflow, copy, Excel."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.budget.excel import build_budget_workbook, parse_budget_workbook, stamp
from app.budget.schemas import BudgetCreate, BudgetPatch, CopyInput, LineRow, LinesInput, VersionInput
from app.budget.service import (
    BUDGET_RESOURCE,
    KIND_LABELS,
    BudgetError,
    adjusted_amount,
    assert_unique_rows,
    column_label,
    ensure_budget_defaults,
    money,
    next_budget_number,
    period_columns,
    require,
    shift_years,
    sign_ok,
)
from app.budget.settings import audit
from app.core.database import get_db
from app.core.enterprise_deps import ActorContext, get_actor
from app.models.budget import Budget, BudgetAccount, BudgetAccountGroup, BudgetEntry
from app.models.crm import ERPPartyGroup
from app.models.models import Employee, Organization, Project, UserAccount

router = APIRouter()
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
KINDS = ("income", "cogs", "expense", "other")


class PrimaryInput(BaseModel):
    is_primary: bool = True


def iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value else None


async def get_budget(db: AsyncSession, actor: ActorContext, budget_id: int, *, lock: bool = False) -> Budget:
    statement = select(Budget).where(Budget.id == budget_id, Budget.organization_id == actor.organization_id)
    if lock:
        statement = statement.with_for_update()
    row = await db.scalar(statement)
    if not row:
        raise BudgetError(404, "budget_not_found", "Төсөв олдсонгүй")
    return row


def assert_version(row: Budget, expected: int | None) -> None:
    if expected is not None and expected != row.version:
        raise BudgetError(409, "budget_version_conflict", "Төсвийг өөр хэрэглэгч өөрчилсөн байна. Дахин ачаалаад оролдоно уу.", current_version=row.version)


def assert_draft(row: Budget) -> None:
    if row.status != "draft":
        raise BudgetError(409, "budget_not_draft", "Батлагдсан эсвэл архивласан төсвийг засах боломжгүй. Эхлээд ноорог болгоно уу.", status=row.status)


def _columns(row: Budget) -> list[tuple[date, date]]:
    return period_columns(row.period_type, row.start_date, row.end_date)


async def _totals(db: AsyncSession, budget_ids: list[int]) -> dict[int, dict[str, str]]:
    totals: dict[int, dict[str, Decimal]] = {budget_id: {kind: Decimal(0) for kind in KINDS} for budget_id in budget_ids}
    if budget_ids:
        for budget_id, kind, amount in (await db.execute(
            select(BudgetEntry.budget_id, BudgetAccount.kind, func.sum(BudgetEntry.amount))
            .join(BudgetAccount, BudgetAccount.id == BudgetEntry.budget_account_id)
            .where(BudgetEntry.budget_id.in_(budget_ids)).group_by(BudgetEntry.budget_id, BudgetAccount.kind)
        )).all():
            totals[budget_id][kind] = Decimal(amount or 0)
    return {budget_id: {**{kind: str(money(value)) for kind, value in values.items()}, "profit": str(money(sum(values.values(), Decimal(0))))}
            for budget_id, values in totals.items()}


async def budgets_out(db: AsyncSession, rows: list[Budget]) -> list[dict[str, Any]]:
    project_ids = {row.project_id for row in rows if row.project_id}
    projects = {pid: (code, name) for pid, code, name in (await db.execute(select(Project.id, Project.code, Project.name).where(Project.id.in_(project_ids)))).all()} if project_ids else {}
    account_ids = {row.approved_by_account_id for row in rows if row.approved_by_account_id} | {row.created_by_account_id for row in rows if row.created_by_account_id}
    accounts = {account_id: name or email for account_id, email, name in (await db.execute(
        select(UserAccount.id, UserAccount.email, Employee.name).outerjoin(Employee, Employee.id == UserAccount.employee_id).where(UserAccount.id.in_(account_ids))
    )).all()} if account_ids else {}
    totals = await _totals(db, [row.id for row in rows])
    return [{
        "id": row.id, "public_id": str(row.public_id), "number": row.number, "name": row.name, "purpose": row.purpose,
        "scenario": row.scenario, "period_type": row.period_type, "start_date": iso(row.start_date), "end_date": iso(row.end_date),
        "project_id": row.project_id, "project_name": (lambda p: f"{p[0]} · {p[1]}" if p else None)(projects.get(row.project_id)),
        "currency": row.currency, "status": row.status, "is_primary": row.is_primary, "copied_from_id": row.copied_from_id,
        "approved_at": iso(row.approved_at), "approved_by": accounts.get(row.approved_by_account_id), "created_by": accounts.get(row.created_by_account_id),
        "totals": totals.get(row.id), "version": row.version, "created_at": iso(row.created_at), "updated_at": iso(row.updated_at),
    } for row in rows]


async def _account_order(db: AsyncSession, organization_id: int) -> dict[int, tuple[Any, ...]]:
    rows = (await db.execute(
        select(BudgetAccount.id, BudgetAccount.code, BudgetAccount.name, BudgetAccount.kind, BudgetAccountGroup.sort, BudgetAccount.sort)
        .outerjoin(BudgetAccountGroup, BudgetAccountGroup.id == BudgetAccount.group_id)
        .where(BudgetAccount.organization_id == organization_id)
    )).all()
    return {row[0]: (row[4] if row[4] is not None else 100000, row[5], row[1], row[2], row[3]) for row in rows}


async def grid_rows(db: AsyncSession, budget: Budget) -> list[dict[str, Any]]:
    """Entries folded back into editor rows: account × project × customer group."""
    entries = (await db.execute(select(BudgetEntry).where(BudgetEntry.budget_id == budget.id).order_by(BudgetEntry.position, BudgetEntry.id))).scalars().all()
    order = await _account_order(db, budget.organization_id)
    rows: dict[tuple[int, int | None, int | None], dict[str, Any]] = {}
    for entry in entries:
        key = (entry.budget_account_id, entry.project_id, entry.party_group_id)
        row = rows.get(key)
        if row is None:
            meta = order.get(entry.budget_account_id, (100000, 0, "?", "?", "other"))
            row = rows[key] = {"budget_account_id": entry.budget_account_id, "account_code": meta[2], "account_name": meta[3], "kind": meta[4],
                               "project_id": entry.project_id, "party_group_id": entry.party_group_id, "note": entry.note, "amounts": {}, "position": entry.position}
        row["note"] = row["note"] or entry.note
        start = entry.period_start.isoformat()
        row["amounts"][start] = str(money(Decimal(row["amounts"].get(start, 0)) + Decimal(entry.amount)))
    result = list(rows.values())
    for row in result:
        row["total"] = str(money(sum((Decimal(value) for value in row["amounts"].values()), Decimal(0))))
    result.sort(key=lambda row: (row["position"], order.get(row["budget_account_id"], (100000,))[:3], row["project_id"] or 0, row["party_group_id"] or 0))
    return result


async def budget_detail(db: AsyncSession, budget: Budget) -> dict[str, Any]:
    await db.refresh(budget)  # server-side updated_at is expired after a commit
    return {
        **(await budgets_out(db, [budget]))[0],
        "columns": [{"start": start.isoformat(), "end": end.isoformat(), "label": column_label(budget.period_type, start, end)} for start, end in _columns(budget)],
        "rows": await grid_rows(db, budget),
    }


async def _validate_project(db: AsyncSession, organization_id: int, project_id: int | None) -> None:
    if project_id is not None and not await db.scalar(select(Project.id).where(Project.id == project_id, Project.organization_id == organization_id)):
        raise BudgetError(422, "budget_invalid_reference", "Төсөл олдсонгүй", field="project_id")


async def replace_lines(db: AsyncSession, actor: ActorContext, budget: Budget, rows: list[LineRow]) -> None:
    """Validate the whole grid, then swap all entries atomically."""
    org = actor.organization_id
    columns = dict(_columns(budget))
    account_ids = {row.budget_account_id for row in rows}
    accounts = {row.id: row for row in (await db.execute(select(BudgetAccount).where(BudgetAccount.organization_id == org, BudgetAccount.id.in_(account_ids)))).scalars().all()} if account_ids else {}
    if account_ids - set(accounts):
        raise BudgetError(422, "budget_invalid_reference", "Төсөвт данс олдсонгүй", field="budget_account_id", ids=sorted(account_ids - set(accounts)))
    project_ids = {row.project_id for row in rows if row.project_id}
    if project_ids:
        found = set((await db.execute(select(Project.id).where(Project.organization_id == org, Project.id.in_(project_ids)))).scalars().all())
        if project_ids - found:
            raise BudgetError(422, "budget_invalid_reference", "Төсөл олдсонгүй", field="project_id")
    group_ids = {row.party_group_id for row in rows if row.party_group_id}
    if group_ids:
        found = set((await db.execute(select(ERPPartyGroup.id).where(ERPPartyGroup.organization_id == org, ERPPartyGroup.id.in_(group_ids)))).scalars().all())
        if group_ids - found:
            raise BudgetError(422, "budget_invalid_reference", "Харилцагчийн бүлэг олдсонгүй", field="party_group_id")
    if budget.project_id:
        # A project budget is planned for that project only; lines inherit it.
        if any(row.project_id not in (None, budget.project_id) for row in rows):
            raise BudgetError(422, "budget_project_mismatch", "Төслийн төсөвт өөр төслийн мөр оруулах боломжгүй")
        for row in rows:
            row.project_id = None
    assert_unique_rows((row.budget_account_id, row.project_id, row.party_group_id) for row in rows)
    sign_errors: list[dict[str, Any]] = []
    for row in rows:
        unknown = set(row.amounts) - set(columns)
        if unknown:
            raise BudgetError(422, "budget_unknown_period", "Төсвийн хугацаанд хамаарахгүй багана байна", periods=sorted(value.isoformat() for value in unknown))
        account = accounts[row.budget_account_id]
        for start, amount in row.amounts.items():
            if not sign_ok(account.kind, amount):
                sign_errors.append({"account_code": account.code, "account_name": account.name, "kind": account.kind, "period": start.isoformat(), "amount": str(amount)})
    if sign_errors:
        raise BudgetError(422, "budget_sign_mismatch", "Орлогыг эерэг (+), ББӨ болон зардлыг сөрөг (−) утгаар оруулна.", violations=sign_errors[:50])
    await db.execute(delete(BudgetEntry).where(BudgetEntry.budget_id == budget.id))
    first_column = next(iter(columns), None)
    for position, row in enumerate(rows):
        amounts = {start: money(amount) for start, amount in row.amounts.items() if money(amount) != 0}
        if not amounts and first_column is not None:
            amounts = {first_column: Decimal(0)}  # keep an empty planned row visible in the editor
        for start, amount in sorted(amounts.items()):
            db.add(BudgetEntry(organization_id=org, budget_id=budget.id, budget_account_id=row.budget_account_id, project_id=row.project_id,
                               party_group_id=row.party_group_id, period_start=start, period_end=columns[start], amount=amount, note=row.note, position=position))
    budget.version += 1
    budget.updated_at = datetime.now(timezone.utc)
    await db.flush()


# ─── List & CRUD ───────────────────────────────────────────────────────────────

@router.get("/budgets")
async def list_budgets(
    status_filter: Literal["draft", "approved", "archived", "active", "all"] = Query(default="active", alias="status"),
    scenario: str | None = None, project_id: int | None = None, search: str | None = Query(default=None, max_length=120),
    year: int | None = Query(default=None, ge=2000, le=2100),
    db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor),
):
    await require(db, actor, BUDGET_RESOURCE, "view")
    statement = select(Budget).where(Budget.organization_id == actor.organization_id)
    if status_filter == "active":
        statement = statement.where(Budget.status != "archived")
    elif status_filter != "all":
        statement = statement.where(Budget.status == status_filter)
    if scenario:
        statement = statement.where(Budget.scenario == scenario)
    if project_id:
        statement = statement.where(Budget.project_id == project_id)
    if year:
        statement = statement.where(Budget.start_date <= date(year, 12, 31), Budget.end_date >= date(year, 1, 1))
    if search:
        pattern = f"%{search.strip()}%"
        statement = statement.where(or_(Budget.name.ilike(pattern), Budget.number.ilike(pattern), Budget.purpose.ilike(pattern)))
    rows = (await db.execute(statement.order_by(Budget.is_primary.desc(), Budget.start_date.desc(), Budget.id.desc()).limit(500))).scalars().all()
    return {"items": await budgets_out(db, list(rows))}


@router.post("/budgets", status_code=status.HTTP_201_CREATED)
async def create_budget(data: BudgetCreate, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require(db, actor, BUDGET_RESOURCE, "create")
    await _validate_project(db, actor.organization_id, data.project_id)
    await ensure_budget_defaults(db, actor.organization_id)
    organization = await db.get(Organization, actor.organization_id)
    row = Budget(organization_id=actor.organization_id, number=await next_budget_number(db, actor.organization_id), created_by_account_id=actor.account_id,
                 currency=(organization.base_currency if organization else "MNT"), **data.model_dump())
    db.add(row)
    await db.flush()
    await audit(db, actor, "budget", row.id, "created", data.model_dump(mode="json"))
    await db.commit()
    return await budget_detail(db, row)


@router.get("/budgets/{budget_id}")
async def get_budget_detail(budget_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require(db, actor, BUDGET_RESOURCE, "view")
    return await budget_detail(db, await get_budget(db, actor, budget_id))


@router.patch("/budgets/{budget_id}")
async def update_budget(budget_id: int, data: BudgetPatch, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require(db, actor, BUDGET_RESOURCE, "edit")
    row = await get_budget(db, actor, budget_id, lock=True)
    assert_version(row, data.version)
    assert_draft(row)
    changes = data.model_dump(exclude_unset=True, exclude={"version"})
    for field in ("name", "scenario", "period_type", "start_date", "end_date"):
        if field in changes and changes[field] is None:
            changes.pop(field)
    start, end = changes.get("start_date", row.start_date), changes.get("end_date", row.end_date)
    if start > end:
        raise BudgetError(422, "budget_invalid_period", "Эхлэх огноо дуусах огнооноос өмнө байх ёстой")
    if "project_id" in changes:
        await _validate_project(db, actor.organization_id, changes["project_id"])
    period_changed = any(field in changes and changes[field] != getattr(row, field) for field in ("period_type", "start_date", "end_date"))
    if period_changed:
        new_columns = dict(period_columns(changes.get("period_type", row.period_type), start, end))
        entries = (await db.execute(select(BudgetEntry.period_start, BudgetEntry.period_end).where(BudgetEntry.budget_id == row.id).distinct())).all()
        if any(new_columns.get(entry_start) != entry_end for entry_start, entry_end in entries):
            raise BudgetError(409, "budget_period_locked", "Дүн оруулсан төсвийн хугацаа, задаргааг өөрчлөх боломжгүй. Хувилж шинэ хугацаагаар үүсгэнэ үү.")
    for field, value in changes.items():
        setattr(row, field, value)
    row.version += 1
    await audit(db, actor, "budget", row.id, "updated", {key: (value.isoformat() if isinstance(value, date) else value) for key, value in changes.items()})
    await db.commit()
    return await budget_detail(db, row)


@router.put("/budgets/{budget_id}/lines")
async def save_lines(budget_id: int, data: LinesInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require(db, actor, BUDGET_RESOURCE, "edit")
    row = await get_budget(db, actor, budget_id, lock=True)
    assert_version(row, data.version)
    assert_draft(row)
    await replace_lines(db, actor, row, data.rows)
    totals = (await _totals(db, [row.id]))[row.id]
    await audit(db, actor, "budget", row.id, "lines_saved", {"rows": len(data.rows), "totals": totals})
    await db.commit()
    return await budget_detail(db, row)


@router.delete("/budgets/{budget_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_budget(budget_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require(db, actor, BUDGET_RESOURCE, "archive")
    row = await get_budget(db, actor, budget_id, lock=True)
    if row.status == "approved":
        raise BudgetError(409, "budget_approved_delete", "Батлагдсан төсвийг устгах боломжгүй. Архивлана уу.")
    await audit(db, actor, "budget", row.id, "deleted", {"number": row.number, "name": row.name})
    await db.delete(row)
    await db.commit()


# ─── Workflow: Төлөвлөх → Батлах → … ───────────────────────────────────────────

async def _transition(db: AsyncSession, actor: ActorContext, budget_id: int, version: int | None) -> Budget:
    row = await get_budget(db, actor, budget_id, lock=True)
    assert_version(row, version)
    return row


@router.post("/budgets/{budget_id}/approve")
async def approve_budget(budget_id: int, data: VersionInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require(db, actor, BUDGET_RESOURCE, "approve")
    row = await _transition(db, actor, budget_id, data.version)
    assert_draft(row)
    if not await db.scalar(select(BudgetEntry.id).where(BudgetEntry.budget_id == row.id, BudgetEntry.amount != 0).limit(1)):
        raise BudgetError(422, "budget_empty", "Дүн оруулаагүй төсвийг батлах боломжгүй")
    row.status, row.approved_at, row.approved_by_account_id = "approved", datetime.now(timezone.utc), actor.account_id
    row.version += 1
    await audit(db, actor, "budget", row.id, "approved", {"totals": (await _totals(db, [row.id]))[row.id]})
    await db.commit()
    return await budget_detail(db, row)


@router.post("/budgets/{budget_id}/reopen")
async def reopen_budget(budget_id: int, data: VersionInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    """d161 cycle: “Шаардлагатай бол төлөвлөгөөг шинэчлэх” — back to draft."""
    await require(db, actor, BUDGET_RESOURCE, "approve")
    row = await _transition(db, actor, budget_id, data.version)
    if row.status != "approved":
        raise BudgetError(409, "budget_not_approved", "Зөвхөн батлагдсан төсвийг ноорог болгоно")
    row.status, row.is_primary, row.approved_at, row.approved_by_account_id = "draft", False, None, None
    row.version += 1
    await audit(db, actor, "budget", row.id, "reopened")
    await db.commit()
    return await budget_detail(db, row)


@router.post("/budgets/{budget_id}/archive")
async def archive_budget(budget_id: int, data: VersionInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require(db, actor, BUDGET_RESOURCE, "archive")
    row = await _transition(db, actor, budget_id, data.version)
    if row.status == "archived":
        return await budget_detail(db, row)
    row.status, row.is_primary = "archived", False
    row.version += 1
    await audit(db, actor, "budget", row.id, "archived")
    await db.commit()
    return await budget_detail(db, row)


@router.post("/budgets/{budget_id}/restore")
async def restore_budget(budget_id: int, data: VersionInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require(db, actor, BUDGET_RESOURCE, "archive")
    row = await _transition(db, actor, budget_id, data.version)
    if row.status != "archived":
        raise BudgetError(409, "budget_not_archived", "Архивласан төсөв биш байна")
    row.status, row.approved_at, row.approved_by_account_id = "draft", None, None
    row.version += 1
    await audit(db, actor, "budget", row.id, "restored")
    await db.commit()
    return await budget_detail(db, row)


@router.post("/budgets/{budget_id}/primary")
async def set_primary(budget_id: int, data: PrimaryInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    """Хүчин төгөлдөр төсөв — one per overlapping period and project (d161 ⚠️4)."""
    await require(db, actor, BUDGET_RESOURCE, "approve")
    row = await get_budget(db, actor, budget_id, lock=True)
    if data.is_primary:
        if row.status != "approved":
            raise BudgetError(409, "budget_not_approved", "Зөвхөн батлагдсан төсвийг хүчин төгөлдөр болгоно")
        others = (await db.execute(select(Budget).where(
            Budget.organization_id == actor.organization_id, Budget.id != row.id, Budget.is_primary.is_(True),
            Budget.start_date <= row.end_date, Budget.end_date >= row.start_date,
            Budget.project_id.is_(None) if row.project_id is None else Budget.project_id == row.project_id,
        ).with_for_update())).scalars().all()
        for other in others:
            other.is_primary = False
            other.version += 1
    row.is_primary = data.is_primary
    row.version += 1
    await audit(db, actor, "budget", row.id, "primary_set" if data.is_primary else "primary_cleared")
    await db.commit()
    return await budget_detail(db, row)


@router.post("/budgets/{budget_id}/copy", status_code=status.HTTP_201_CREATED)
async def copy_budget(budget_id: int, data: CopyInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    """Хувилах — a new draft scenario, optionally shifted by years and scaled by ±%."""
    await require(db, actor, BUDGET_RESOURCE, "create")
    source = await get_budget(db, actor, budget_id)
    copy = Budget(organization_id=actor.organization_id, number=await next_budget_number(db, actor.organization_id), name=data.name,
                  purpose=data.purpose if data.purpose is not None else source.purpose, scenario=data.scenario, period_type=source.period_type,
                  start_date=shift_years(source.start_date, data.shift_years), end_date=shift_years(source.end_date, data.shift_years),
                  project_id=source.project_id, currency=source.currency, copied_from_id=source.id, created_by_account_id=actor.account_id)
    db.add(copy)
    await db.flush()
    columns = dict(_columns(copy))
    # Re-key onto the new calendar: a shifted period lands on the column that contains its start.
    grouped: dict[tuple[Any, ...], Decimal] = defaultdict(Decimal)
    notes: dict[tuple[Any, ...], str | None] = {}
    for entry in (await db.execute(select(BudgetEntry).where(BudgetEntry.budget_id == source.id))).scalars().all():
        shifted = shift_years(entry.period_start, data.shift_years)
        target = next((start for start, end in columns.items() if start <= shifted <= end), None)
        if target is None:
            continue
        key = (entry.position, entry.budget_account_id, entry.project_id, entry.party_group_id, target)
        grouped[key] += adjusted_amount(entry.amount, data.adjust_pct)
        notes.setdefault(key, entry.note)
    for key, amount in grouped.items():
        position, account_id, project_id, group_id, start = key
        db.add(BudgetEntry(organization_id=actor.organization_id, budget_id=copy.id, budget_account_id=account_id, project_id=project_id,
                           party_group_id=group_id, period_start=start, period_end=columns[start], amount=money(amount), note=notes[key], position=position))
    await db.flush()
    await audit(db, actor, "budget", copy.id, "copied", {"from": source.number, "shift_years": data.shift_years, "adjust_pct": str(data.adjust_pct)})
    await db.commit()
    return await budget_detail(db, copy)


# ─── Excel ─────────────────────────────────────────────────────────────────────

@router.get("/budgets/{budget_id}/export")
async def export_budget(budget_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require(db, actor, BUDGET_RESOURCE, "export")
    budget = await get_budget(db, actor, budget_id)
    rows = await grid_rows(db, budget)
    projects = dict((await db.execute(select(Project.id, Project.code).where(Project.organization_id == actor.organization_id))).all())
    groups = dict((await db.execute(select(ERPPartyGroup.id, ERPPartyGroup.code).where(ERPPartyGroup.organization_id == actor.organization_id))).all())
    columns = [{"start": start, "label": column_label(budget.period_type, start, end)} for start, end in _columns(budget)]
    content = build_budget_workbook(
        title=f"{budget.number} · {budget.name} ({budget.start_date.isoformat()} – {budget.end_date.isoformat()})",
        columns=columns,
        rows=[{"account_code": row["account_code"], "account_name": f"{row['account_name']} ({KIND_LABELS.get(row['kind'], row['kind'])})",
               "project_code": projects.get(row["project_id"]), "party_group_code": groups.get(row["party_group_id"]), "note": row["note"],
               "amounts": {date.fromisoformat(key): Decimal(value) for key, value in row["amounts"].items()}} for row in rows],
    )
    await audit(db, actor, "budget", budget.id, "exported")
    await db.commit()
    return Response(content=content, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{budget.number}-{stamp()}.xlsx"'})


@router.post("/budgets/{budget_id}/import")
async def import_budget(budget_id: int, file: UploadFile = File(...), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    """Replace the draft grid from an exported workbook; nothing is saved if any row fails."""
    await require(db, actor, BUDGET_RESOURCE, "edit")
    budget = await get_budget(db, actor, budget_id, lock=True)
    assert_draft(budget)
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise BudgetError(413, "budget_import_too_large", "Файлын хэмжээ 5MB-аас хэтэрсэн байна")
    try:
        parsed = parse_budget_workbook(content, [start for start, _ in _columns(budget)])
    except ValueError as exc:
        raise BudgetError(422, "budget_import_invalid", str(exc)) from exc
    org = actor.organization_id
    accounts = dict((await db.execute(select(BudgetAccount.code, BudgetAccount.id).where(BudgetAccount.organization_id == org))).all())
    projects = dict((await db.execute(select(Project.code, Project.id).where(Project.organization_id == org))).all())
    groups = dict((await db.execute(select(ERPPartyGroup.code, ERPPartyGroup.id).where(ERPPartyGroup.organization_id == org))).all())
    errors = list(parsed.errors)
    rows: list[LineRow] = []
    for item in parsed.rows:
        problems = []
        if item.account_code not in accounts:
            problems.append(f"“{item.account_code}” төсөвт данс олдсонгүй")
        if item.project_code and item.project_code not in projects:
            problems.append(f"“{item.project_code}” төсөл олдсонгүй")
        if item.party_group_code and item.party_group_code not in groups:
            problems.append(f"“{item.party_group_code}” харилцагчийн бүлэг олдсонгүй")
        if problems:
            errors.extend({"row": item.row_number, "message": problem} for problem in problems)
            continue
        rows.append(LineRow(budget_account_id=accounts[item.account_code], project_id=projects.get(item.project_code) if item.project_code else None,
                            party_group_id=groups.get(item.party_group_code) if item.party_group_code else None, note=item.note, amounts=item.amounts))
    if errors:
        raise BudgetError(422, "budget_import_invalid", "Файлд алдаа байна. Засаад дахин оролдоно уу.", errors=errors[:100])
    try:
        await replace_lines(db, actor, budget, rows)
    except BudgetError as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        if detail.get("code") == "budget_sign_mismatch":
            detail["errors"] = [{"row": None, "message": f"{item['account_code']} · {item['period']}: {item['amount']}"} for item in detail.get("violations", [])]
        raise
    await audit(db, actor, "budget", budget.id, "imported", {"rows": len(rows), "filename": file.filename})
    await db.commit()
    return {"imported_rows": len(rows), "budget": await budget_detail(db, budget)}
