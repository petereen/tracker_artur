"""Төсөв анализ — planned vs “should be by now” vs actual, with drill-down.

* Төсөвлөсөн (budgeted): entries pro-rated by day into the selected window.
* Байх ёстой (expected): the same, but only up to the as-of date.
* Бодит (actual): posted general-ledger lines on the linked ledger accounts,
  ``credit − debit`` so income is positive and spending negative — the same
  sign convention as the budget itself.

Budget and actual are aggregated independently on the same keys, so a line
planned per project and the company-wide total never double count.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import Date, DateTime, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.budget.budgets import XLSX, budgets_out, get_budget
from app.budget.excel import build_analysis_workbook, stamp
from app.budget.service import (
    BUDGET_RESOURCE,
    KIND_LABELS,
    BudgetError,
    bucket_key,
    column_label,
    local_today,
    measures,
    prorate,
    require,
    split_by_bucket,
)
from app.budget.settings import audit
from app.core.database import get_db
from app.core.enterprise_deps import ActorContext, get_actor
from app.models.budget import Budget, BudgetAccount, BudgetAccountGroup, BudgetAccountLink, BudgetEntry
from app.models.crm import ERPPartyGroup
from app.models.models import ERPAccount, ERPDocument, ERPGeneralLedgerEntry, ERPParty, Organization, Project

router = APIRouter()

DIMENSIONS = ("account", "group", "kind", "project", "party_group", "month", "quarter", "year")
TIME_DIMENSIONS = ("month", "quarter", "year")
DIMENSION_LABELS = {"account": "Төсөвт данс", "group": "Дансны бүлэг", "kind": "Төрөл", "project": "Төсөл", "party_group": "Харилцагчийн бүлэг",
                    "month": "Сар", "quarter": "Улирал", "year": "Жил"}
NONE_KEY = 0  # “no project” / “no customer group” in keys and drill-down filters
KIND_ORDER = {"income": 0, "cogs": 1, "expense": 2, "other": 3}


def parse_group_by(value: str) -> list[str]:
    dims = [part.strip() for part in value.split(",") if part.strip()]
    if not dims or len(dims) > 2 or len(set(dims)) != len(dims) or any(dim not in DIMENSIONS for dim in dims):
        raise BudgetError(422, "budget_invalid_group_by", "Бүлэглэлт буруу байна", allowed=list(DIMENSIONS))
    if sum(dim in TIME_DIMENSIONS for dim in dims) > 1:
        raise BudgetError(422, "budget_invalid_group_by", "Хугацааны нэг л задаргаа сонгоно")
    return dims


async def resolve_budget(db: AsyncSession, actor: ActorContext, budget_id: int | None, today: date) -> Budget:
    if budget_id:
        return await get_budget(db, actor, budget_id)
    base = select(Budget).where(Budget.organization_id == actor.organization_id, Budget.status != "archived")
    for statement in (
        base.where(Budget.is_primary.is_(True), Budget.start_date <= today, Budget.end_date >= today, Budget.project_id.is_(None)),
        base.where(Budget.is_primary.is_(True)),
        base.where(Budget.status == "approved"),
        base,
    ):
        row = await db.scalar(statement.order_by(Budget.start_date.desc(), Budget.id.desc()).limit(1))
        if row:
            return row
    raise BudgetError(404, "budget_none", "Төсөв үүсгээгүй байна")


class Scope:
    """Filters shared by the analysis, drill-down and export endpoints."""

    def __init__(self, budget: Budget, *, date_from: date, date_to: date, as_of: date, project_id: int | None, party_group_id: int | None,
                 budget_group_id: int | None, kind: str | None, budget_account_id: int | None = None) -> None:
        self.budget = budget
        self.date_from, self.date_to, self.as_of = date_from, date_to, as_of
        # A project budget always measures that project's transactions.
        self.project_id = budget.project_id or project_id
        self.party_group_id = party_group_id
        self.budget_group_id = budget_group_id
        self.kind = kind
        self.budget_account_id = budget_account_id

    def account_filters(self) -> list[Any]:
        filters: list[Any] = []
        if self.budget_group_id is not None:
            filters.append(BudgetAccount.group_id.is_(None) if self.budget_group_id == NONE_KEY else BudgetAccount.group_id == self.budget_group_id)
        if self.kind:
            filters.append(BudgetAccount.kind == self.kind)
        if self.budget_account_id:
            filters.append(BudgetAccount.id == self.budget_account_id)
        return filters


async def build_scope(db: AsyncSession, actor: ActorContext, *, budget_id: int | None, date_from: date | None, date_to: date | None, as_of: date | None,
                      project_id: int | None, party_group_id: int | None, budget_group_id: int | None, kind: str | None,
                      budget_account_id: int | None = None) -> Scope:
    organization = await db.get(Organization, actor.organization_id)
    today = local_today(organization.timezone if organization else None)
    budget = await resolve_budget(db, actor, budget_id, today)
    start, end = date_from or budget.start_date, date_to or budget.end_date
    if start > end:
        raise BudgetError(422, "budget_invalid_period", "Эхлэх огноо дуусах огнооноос өмнө байх ёстой")
    if (end - start).days > 366 * 5:
        raise BudgetError(422, "budget_invalid_period", "Анализын хугацаа 5 жилээс хэтрэхгүй")
    as_of_date = min(as_of or today, end)
    return Scope(budget, date_from=start, date_to=end, as_of=as_of_date, project_id=project_id, party_group_id=party_group_id,
                 budget_group_id=budget_group_id, kind=kind, budget_account_id=budget_account_id)


def _time_key(dim: str, value: date) -> str:
    return bucket_key(value, dim)[0].isoformat()


async def _budget_cells(db: AsyncSession, scope: Scope, dims: list[str]) -> dict[tuple[Any, ...], dict[str, Decimal]]:
    """Budget facts keyed by (account, project, party_group, time bucket)."""
    time_dim = next((dim for dim in dims if dim in TIME_DIMENSIONS), None)
    statement = select(BudgetEntry).join(BudgetAccount, BudgetAccount.id == BudgetEntry.budget_account_id).where(
        BudgetEntry.budget_id == scope.budget.id, BudgetEntry.period_start <= scope.date_to, BudgetEntry.period_end >= scope.date_from, *scope.account_filters())
    if scope.project_id and not scope.budget.project_id:
        statement = statement.where(BudgetEntry.project_id.is_(None) if scope.project_id == NONE_KEY else BudgetEntry.project_id == scope.project_id)
    if scope.party_group_id is not None:
        statement = statement.where(BudgetEntry.party_group_id.is_(None) if scope.party_group_id == NONE_KEY else BudgetEntry.party_group_id == scope.party_group_id)
    cells: dict[tuple[Any, ...], dict[str, Decimal]] = defaultdict(lambda: {"budgeted": Decimal(0), "expected": Decimal(0), "actual": Decimal(0)})
    project = scope.budget.project_id
    for entry in (await db.execute(statement)).scalars().all():
        base = (entry.budget_account_id, project or entry.project_id, entry.party_group_id)
        amount = Decimal(entry.amount)
        if time_dim:
            for (bucket_start, _), value in split_by_bucket(amount, entry.period_start, entry.period_end, scope.date_from, scope.date_to, time_dim):
                cells[(*base, bucket_start.isoformat())]["budgeted"] += value
            for (bucket_start, _), value in split_by_bucket(amount, entry.period_start, entry.period_end, scope.date_from, scope.as_of, time_dim):
                cells[(*base, bucket_start.isoformat())]["expected"] += value
        else:
            cell = cells[(*base, None)]
            cell["budgeted"] += prorate(amount, entry.period_start, entry.period_end, scope.date_from, scope.date_to)
            if scope.as_of >= scope.date_from:
                cell["expected"] += prorate(amount, entry.period_start, entry.period_end, scope.date_from, scope.as_of)
    return cells


def _actual_filters(scope: Scope, organization_id: int) -> list[Any]:
    party_group = ERPParty.group_id
    filters: list[Any] = [
        ERPGeneralLedgerEntry.organization_id == organization_id,
        ERPGeneralLedgerEntry.posting_date >= scope.date_from,
        ERPGeneralLedgerEntry.posting_date <= scope.as_of,
        *scope.account_filters(),
    ]
    if scope.project_id:
        filters.append(ERPDocument.project_id.is_(None) if scope.project_id == NONE_KEY else ERPDocument.project_id == scope.project_id)
    if scope.party_group_id is not None:
        filters.append(party_group.is_(None) if scope.party_group_id == NONE_KEY else party_group == scope.party_group_id)
    return filters


def _actual_base(*columns: Any) -> Any:
    return (select(*columns)
            .select_from(ERPGeneralLedgerEntry)
            .join(BudgetAccountLink, BudgetAccountLink.erp_account_id == ERPGeneralLedgerEntry.account_id)
            .join(BudgetAccount, BudgetAccount.id == BudgetAccountLink.budget_account_id)
            .join(ERPDocument, ERPDocument.id == ERPGeneralLedgerEntry.document_id)
            .outerjoin(ERPParty, ERPParty.id == func.coalesce(ERPGeneralLedgerEntry.party_id, ERPDocument.party_id)))


async def _actual_cells(db: AsyncSession, scope: Scope, dims: list[str], cells: dict[tuple[Any, ...], dict[str, Decimal]]) -> None:
    if scope.as_of < scope.date_from:
        return
    time_dim = next((dim for dim in dims if dim in TIME_DIMENSIONS), None)
    # Truncate a naive timestamp: date_trunc on a date yields timestamptz, which shifts the day in UTC.
    month = cast(func.date_trunc("month", cast(ERPGeneralLedgerEntry.posting_date, DateTime())), Date)
    amount = func.sum(ERPGeneralLedgerEntry.credit - ERPGeneralLedgerEntry.debit)
    statement = (_actual_base(BudgetAccount.id, ERPDocument.project_id, ERPParty.group_id, month, amount)
                 .where(*_actual_filters(scope, scope.budget.organization_id))
                 .group_by(BudgetAccount.id, ERPDocument.project_id, ERPParty.group_id, month))
    for account_id, project_id, group_id, month_start, value in (await db.execute(statement)).all():
        bucket = _time_key(time_dim, month_start) if time_dim else None
        cells[(account_id, project_id, group_id, bucket)]["actual"] += Decimal(value or 0)


async def _unmapped(db: AsyncSession, scope: Scope) -> list[dict[str, Any]]:
    """Income/expense ledger activity not linked to any budget account (d161 checklist)."""
    if scope.as_of < scope.date_from or scope.budget_account_id or scope.budget_group_id is not None or scope.kind:
        return []
    amount = func.sum(ERPGeneralLedgerEntry.credit - ERPGeneralLedgerEntry.debit)
    statement = (select(ERPAccount.id, ERPAccount.code, ERPAccount.name, ERPAccount.classification, amount)
                 .select_from(ERPGeneralLedgerEntry)
                 .join(ERPAccount, ERPAccount.id == ERPGeneralLedgerEntry.account_id)
                 .join(ERPDocument, ERPDocument.id == ERPGeneralLedgerEntry.document_id)
                 .outerjoin(BudgetAccountLink, BudgetAccountLink.erp_account_id == ERPAccount.id)
                 .outerjoin(ERPParty, ERPParty.id == func.coalesce(ERPGeneralLedgerEntry.party_id, ERPDocument.party_id))
                 .where(BudgetAccountLink.id.is_(None), ERPAccount.classification.in_(("income", "expense")), *_actual_filters(scope, scope.budget.organization_id))
                 .group_by(ERPAccount.id, ERPAccount.code, ERPAccount.name, ERPAccount.classification)
                 .order_by(ERPAccount.code))
    return [{"erp_account_id": aid, "code": code, "name": name, "classification": classification, "actual": str(Decimal(value or 0).quantize(Decimal("0.01")))}
            for aid, code, name, classification, value in (await db.execute(statement)).all() if value]


async def _labels(db: AsyncSession, organization_id: int) -> dict[str, Any]:
    accounts = {row.id: row for row in (await db.execute(select(BudgetAccount).where(BudgetAccount.organization_id == organization_id))).scalars().all()}
    groups = {row.id: row for row in (await db.execute(select(BudgetAccountGroup).where(BudgetAccountGroup.organization_id == organization_id))).scalars().all()}
    projects = {pid: f"{code} · {name}" for pid, code, name in (await db.execute(select(Project.id, Project.code, Project.name).where(Project.organization_id == organization_id))).all()}
    party_groups = dict((await db.execute(select(ERPPartyGroup.id, ERPPartyGroup.name).where(ERPPartyGroup.organization_id == organization_id))).all())
    return {"accounts": accounts, "groups": groups, "projects": projects, "party_groups": party_groups}


def _dim_value(dim: str, cell_key: tuple[Any, ...], lookups: dict[str, Any]) -> tuple[Any, str, tuple[Any, ...]]:
    """(key, label, sort key) of one dimension for one fact cell."""
    account_id, project_id, group_id, bucket = cell_key
    account = lookups["accounts"].get(account_id)
    if dim == "account":
        group = lookups["groups"].get(account.group_id) if account else None
        return account_id, f"{account.code} · {account.name}" if account else "?", (group.sort if group else 100000, KIND_ORDER.get(account.kind if account else "other", 9), account.sort if account else 0, account.code if account else "")
    if dim == "group":
        group_id_value = account.group_id if account else None
        group = lookups["groups"].get(group_id_value)
        return group_id_value or NONE_KEY, group.name if group else "Бүлэггүй", (group.sort if group else 100000, group.code if group else "")
    if dim == "kind":
        kind = account.kind if account else "other"
        return kind, KIND_LABELS.get(kind, kind), (KIND_ORDER.get(kind, 9),)
    if dim == "project":
        return project_id or NONE_KEY, lookups["projects"].get(project_id, "Төсөлгүй") if project_id else "Төсөлгүй", (0 if project_id else 1, lookups["projects"].get(project_id, ""))
    if dim == "party_group":
        return group_id or NONE_KEY, lookups["party_groups"].get(group_id, "Бүлэггүй") if group_id else "Бүлэггүй", (0 if group_id else 1, lookups["party_groups"].get(group_id, ""))
    start = date.fromisoformat(bucket)
    return bucket, column_label(dim, *bucket_key(start, dim)), (bucket,)


def _row_kind(dims: list[str], cell_key: tuple[Any, ...], lookups: dict[str, Any]) -> str | None:
    if not {"account", "kind", "group"} & set(dims):
        return None
    account = lookups["accounts"].get(cell_key[0])
    if "group" in dims and "account" not in dims and "kind" not in dims:
        group = lookups["groups"].get(account.group_id) if account else None
        return group.kind if group else None
    return account.kind if account else None


async def compute_analysis(db: AsyncSession, scope: Scope, dims: list[str]) -> dict[str, Any]:
    cells = await _budget_cells(db, scope, dims)
    await _actual_cells(db, scope, dims, cells)
    lookups = await _labels(db, scope.budget.organization_id)
    grouped: dict[tuple[Any, ...], dict[str, Any]] = {}
    kind_totals: dict[str, dict[str, Decimal]] = {kind: {"budgeted": Decimal(0), "expected": Decimal(0), "actual": Decimal(0)} for kind in KIND_ORDER}
    for cell_key, values in cells.items():
        if not any(values.values()):
            continue
        parts = [_dim_value(dim, cell_key, lookups) for dim in dims]
        key = tuple(part[0] for part in parts)
        row = grouped.get(key)
        if row is None:
            row = grouped[key] = {"key": {dim: part[0] for dim, part in zip(dims, parts)}, "labels": {dim: part[1] for dim, part in zip(dims, parts)},
                                  "sort": tuple(part[2] for part in parts), "kind": _row_kind(dims, cell_key, lookups),
                                  "values": {"budgeted": Decimal(0), "expected": Decimal(0), "actual": Decimal(0)}}
        for measure, value in values.items():
            row["values"][measure] += value
        account = lookups["accounts"].get(cell_key[0])
        for measure, value in values.items():
            kind_totals[account.kind if account else "other"][measure] += value
    rows = sorted(grouped.values(), key=lambda row: row["sort"])
    profit = {measure: sum((totals[measure] for totals in kind_totals.values()), Decimal(0)) for measure in ("budgeted", "expected", "actual")}
    elapsed = (scope.as_of - scope.date_from).days + 1
    span = (scope.date_to - scope.date_from).days + 1
    return {
        "budget": (await budgets_out(db, [scope.budget]))[0],
        "window": {"date_from": scope.date_from.isoformat(), "date_to": scope.date_to.isoformat(), "as_of": scope.as_of.isoformat(),
                   "elapsed_pct": str(max(0, min(100, round(100 * elapsed / span, 1)))) if span > 0 else "0"},
        "group_by": dims,
        "dimension_labels": {dim: DIMENSION_LABELS[dim] for dim in dims},
        "rows": [{"key": row["key"], "labels": row["labels"], "kind": row["kind"],
                  **measures(row["values"]["budgeted"], row["values"]["expected"], row["values"]["actual"])} for row in rows],
        "totals": {**{kind: measures(values["budgeted"], values["expected"], values["actual"]) for kind, values in kind_totals.items()},
                   "profit": measures(profit["budgeted"], profit["expected"], profit["actual"])},
        "unmapped": await _unmapped(db, scope),
    }


def _query_params(
    budget_id: int | None = None, date_from: date | None = None, date_to: date | None = None, as_of: date | None = None,
    project_id: int | None = Query(default=None, ge=0), party_group_id: int | None = Query(default=None, ge=0),
    budget_group_id: int | None = Query(default=None, ge=0), kind: Literal["income", "cogs", "expense", "other"] | None = None,
) -> dict[str, Any]:
    return {"budget_id": budget_id, "date_from": date_from, "date_to": date_to, "as_of": as_of, "project_id": project_id,
            "party_group_id": party_group_id, "budget_group_id": budget_group_id, "kind": kind}


@router.get("/analysis")
async def analysis(group_by: str = Query(default="account", max_length=60), params: dict[str, Any] = Depends(_query_params),
                   db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require(db, actor, BUDGET_RESOURCE, "view")
    dims = parse_group_by(group_by)
    scope = await build_scope(db, actor, **params)
    return await compute_analysis(db, scope, dims)


@router.get("/analysis/transactions")
async def analysis_transactions(
    budget_account_id: int | None = None, period_start: date | None = None, period_end: date | None = None,
    limit: int = Query(default=200, ge=1, le=1000), params: dict[str, Any] = Depends(_query_params),
    db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor),
):
    """Drill down: the ledger lines behind an actual figure (d161 “Гүйлгээний жагсаалт руу шилжих”)."""
    await require(db, actor, BUDGET_RESOURCE, "view")
    scope = await build_scope(db, actor, budget_account_id=budget_account_id, **params)
    if period_start or period_end:
        scope.date_from = max(scope.date_from, period_start or scope.date_from)
        scope.as_of = min(scope.as_of, period_end or scope.as_of)
    filters = _actual_filters(scope, actor.organization_id)
    amount = ERPGeneralLedgerEntry.credit - ERPGeneralLedgerEntry.debit
    summary = (await db.execute(_actual_base(func.count(ERPGeneralLedgerEntry.id), func.coalesce(func.sum(amount), 0)).where(*filters))).one()
    statement = (_actual_base(ERPGeneralLedgerEntry, ERPDocument.document_type, ERPDocument.number, ERPDocument.project_id,
                              ERPAccount.code, ERPAccount.name, BudgetAccount.code, BudgetAccount.name, ERPParty.name)
                 .join(ERPAccount, ERPAccount.id == ERPGeneralLedgerEntry.account_id)
                 .where(*filters)
                 .order_by(ERPGeneralLedgerEntry.posting_date.desc(), ERPGeneralLedgerEntry.id.desc()).limit(limit))
    projects = dict((await db.execute(select(Project.id, Project.name).where(Project.organization_id == actor.organization_id))).all())
    items = []
    for entry, document_type, number, project_id, account_code, account_name, budget_code, budget_name, party_name in (await db.execute(statement)).all():
        items.append({
            "id": entry.id, "posting_date": entry.posting_date.isoformat(), "document_id": entry.document_id, "document_type": document_type, "document_number": number,
            "account_code": account_code, "account_name": account_name, "budget_account_code": budget_code, "budget_account_name": budget_name,
            "party_name": party_name, "project_name": projects.get(project_id), "memo": entry.memo,
            "debit": str(entry.debit), "credit": str(entry.credit), "amount": str(Decimal(entry.credit) - Decimal(entry.debit)),
        })
    return {"total_count": int(summary[0] or 0), "total_amount": str(Decimal(summary[1] or 0).quantize(Decimal("0.01"))), "items": items,
            "window": {"date_from": scope.date_from.isoformat(), "as_of": scope.as_of.isoformat()}}


@router.get("/analysis/export")
async def export_analysis(group_by: str = Query(default="account", max_length=60), params: dict[str, Any] = Depends(_query_params),
                          db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require(db, actor, BUDGET_RESOURCE, "export")
    dims = parse_group_by(group_by)
    scope = await build_scope(db, actor, **params)
    result = await compute_analysis(db, scope, dims)
    status_labels = {"favorable": "Давсан / хэмнэсэн", "on_track": "Төлөвлөгөөний дагуу", "unfavorable": "Хоцорсон / хэтэрсэн", "unplanned": "Төлөвлөөгүй", "no_activity": "—"}
    headers = [*(DIMENSION_LABELS[dim] for dim in dims), "Төсөвлөсөн", "Байх ёстой", "Бодит", "Зөрүү", "Гүйцэтгэл %", "Төлөв"]
    money_columns = set(range(len(dims) + 1, len(dims) + 5))

    def line(labels: list[str], values: dict[str, Any]) -> list[Any]:
        pct = values["performance_pct"]
        return [*labels, float(values["budgeted"]), float(values["expected"]), float(values["actual"]), float(values["variance"]),
                float(pct) if pct is not None else None, status_labels.get(values["status"], values["status"])]

    rows = [line([row["labels"][dim] for dim in dims], row) for row in result["rows"]]
    rows.append([])
    for kind in ("income", "cogs", "expense", "other"):
        rows.append(line([f"Нийт {KIND_LABELS[kind]}", *[""] * (len(dims) - 1)], result["totals"][kind]))
    rows.append(line(["Ашиг (Орлого + Зардал)", *[""] * (len(dims) - 1)], result["totals"]["profit"]))
    budget = scope.budget
    content = build_analysis_workbook(
        title=f"Төсөв анализ · {budget.number} {budget.name}",
        subtitle=f"{scope.date_from.isoformat()} – {scope.date_to.isoformat()} · байх ёстой: {scope.as_of.isoformat()} хүртэл",
        headers=headers, rows=rows, money_columns=money_columns,
    )
    await audit(db, actor, "budget", budget.id, "analysis_exported", {"group_by": dims})
    await db.commit()
    return Response(content=content, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="budget-analysis-{budget.number}-{stamp()}.xlsx"'})
