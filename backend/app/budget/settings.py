"""Budget capabilities, lookups, account groups (Төсөвт данс бүлэг) and budget accounts (Төсөвт данс)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.budget.schemas import AccountInput, AccountPatch, GenerateAccountsInput, GroupInput, GroupPatch
from app.budget.service import (
    BUDGET_RESOURCE,
    CLASSIFICATION_KINDS,
    SETTINGS_RESOURCE,
    BudgetError,
    budget_module_enabled,
    capability_matrix,
    ensure_budget_defaults,
    has_capability,
    require,
)
from app.core.database import get_db
from app.core.enterprise_deps import ActorContext, get_actor
from app.models.budget import BudgetAccount, BudgetAccountGroup, BudgetAccountLink, BudgetEntry
from app.models.crm import ERPPartyGroup
from app.models.models import ERPAccount, Organization, Project
from app.services.enterprise_events import record_change

router = APIRouter()


async def audit(db: AsyncSession, actor: ActorContext, aggregate: str, row_id: int, operation: str, after: dict[str, Any] | None = None) -> None:
    await record_change(db, actor=actor, topic="budget", aggregate_type=aggregate, aggregate_id=row_id, operation=operation, after=after or {})


async def require_any_view(db: AsyncSession, actor: ActorContext) -> None:
    if not (await has_capability(db, actor, BUDGET_RESOURCE, "view") or await has_capability(db, actor, SETTINGS_RESOURCE, "view")):
        raise BudgetError(403, "budget_forbidden", "Төсөв модульд хандах эрхгүй байна")


def group_out(row: BudgetAccountGroup) -> dict[str, Any]:
    return {"id": row.id, "code": row.code, "name": row.name, "kind": row.kind, "parent_id": row.parent_id, "sort": row.sort, "is_active": row.is_active}


async def accounts_out(db: AsyncSession, rows: list[BudgetAccount]) -> list[dict[str, Any]]:
    ids = [row.id for row in rows]
    links: dict[int, list[dict[str, Any]]] = {row_id: [] for row_id in ids}
    in_use: set[int] = set()
    groups: dict[int, str] = {}
    if ids:
        for budget_account_id, account_id, code, name, classification in (await db.execute(
            select(BudgetAccountLink.budget_account_id, ERPAccount.id, ERPAccount.code, ERPAccount.name, ERPAccount.classification)
            .join(ERPAccount, ERPAccount.id == BudgetAccountLink.erp_account_id)
            .where(BudgetAccountLink.budget_account_id.in_(ids)).order_by(ERPAccount.code)
        )).all():
            links[budget_account_id].append({"id": account_id, "code": code, "name": name, "classification": classification})
        in_use = set((await db.execute(select(BudgetEntry.budget_account_id).where(BudgetEntry.budget_account_id.in_(ids)).distinct())).scalars().all())
        group_ids = {row.group_id for row in rows if row.group_id}
        if group_ids:
            groups = dict((await db.execute(select(BudgetAccountGroup.id, BudgetAccountGroup.name).where(BudgetAccountGroup.id.in_(group_ids)))).all())
    return [{
        "id": row.id, "code": row.code, "name": row.name, "kind": row.kind, "group_id": row.group_id, "group_name": groups.get(row.group_id),
        "note": row.note, "sort": row.sort, "is_active": row.is_active, "erp_accounts": links.get(row.id, []), "in_use": row.id in in_use,
    } for row in rows]


async def _ordered_accounts(db: AsyncSession, organization_id: int) -> list[BudgetAccount]:
    return list((await db.execute(
        select(BudgetAccount).outerjoin(BudgetAccountGroup, BudgetAccountGroup.id == BudgetAccount.group_id)
        .where(BudgetAccount.organization_id == organization_id)
        .order_by(func.coalesce(BudgetAccountGroup.sort, 100000), BudgetAccount.sort, BudgetAccount.code)
    )).scalars().all())


@router.get("/capabilities")
async def budget_capabilities(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    """What the current user may do; the frontend uses this for nav and buttons."""
    return {"module_enabled": await budget_module_enabled(db, actor.organization_id), **await capability_matrix(db, actor)}


@router.get("/lookups")
async def budget_lookups(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    """Everything the budget screens need for their pickers, in one request."""
    await require_any_view(db, actor)
    org = actor.organization_id
    await ensure_budget_defaults(db, org)
    await db.commit()
    organization = await db.get(Organization, org)
    groups = (await db.execute(select(BudgetAccountGroup).where(BudgetAccountGroup.organization_id == org).order_by(BudgetAccountGroup.sort, BudgetAccountGroup.code))).scalars().all()
    linked = dict((await db.execute(select(BudgetAccountLink.erp_account_id, BudgetAccountLink.budget_account_id).where(BudgetAccountLink.organization_id == org))).all())
    erp_accounts = (await db.execute(select(ERPAccount).where(ERPAccount.organization_id == org, ERPAccount.is_group.is_(False)).order_by(ERPAccount.code))).scalars().all()
    projects = (await db.execute(select(Project.id, Project.code, Project.name).where(Project.organization_id == org, Project.archived_at.is_(None)).order_by(Project.name))).all()
    party_groups = (await db.execute(select(ERPPartyGroup.id, ERPPartyGroup.code, ERPPartyGroup.name).where(ERPPartyGroup.organization_id == org).order_by(ERPPartyGroup.name))).all()
    return {
        "currency": organization.base_currency if organization else "MNT",
        "groups": [group_out(row) for row in groups],
        "accounts": await accounts_out(db, await _ordered_accounts(db, org)),
        "erp_accounts": [{"id": row.id, "code": row.code, "name": row.name, "classification": row.classification, "is_active": row.is_active,
                          "budget_account_id": linked.get(row.id)} for row in erp_accounts],
        "projects": [{"id": pid, "code": code, "name": name} for pid, code, name in projects],
        "party_groups": [{"id": gid, "code": code, "name": name} for gid, code, name in party_groups],
    }


# ─── Groups ────────────────────────────────────────────────────────────────────

async def _group(db: AsyncSession, actor: ActorContext, group_id: int) -> BudgetAccountGroup:
    row = await db.scalar(select(BudgetAccountGroup).where(BudgetAccountGroup.id == group_id, BudgetAccountGroup.organization_id == actor.organization_id))
    if not row:
        raise BudgetError(404, "budget_group_not_found", "Төсөвт дансны бүлэг олдсонгүй")
    return row


async def _assert_code_free(db: AsyncSession, model: Any, organization_id: int, code: str, exclude_id: int | None = None) -> None:
    statement = select(model.id).where(model.organization_id == organization_id, model.code == code)
    if exclude_id is not None:
        statement = statement.where(model.id != exclude_id)
    if await db.scalar(statement):
        raise BudgetError(409, "budget_code_taken", f"“{code}” код давхардсан байна")


async def _assert_group_parent(db: AsyncSession, actor: ActorContext, group_id: int | None, parent_id: int | None) -> None:
    if parent_id is None:
        return
    await _group(db, actor, parent_id)
    current: int | None = parent_id
    seen: set[int] = set()
    while current is not None and current not in seen:
        if current == group_id:
            raise BudgetError(422, "budget_group_parent_cycle", "Бүлэг өөрийн дэд бүлэгт харьяалагдаж болохгүй")
        seen.add(current)
        current = await db.scalar(select(BudgetAccountGroup.parent_id).where(BudgetAccountGroup.id == current))


@router.post("/groups", status_code=status.HTTP_201_CREATED)
async def create_group(data: GroupInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require(db, actor, SETTINGS_RESOURCE, "create")
    await _assert_code_free(db, BudgetAccountGroup, actor.organization_id, data.code)
    await _assert_group_parent(db, actor, None, data.parent_id)
    row = BudgetAccountGroup(organization_id=actor.organization_id, **data.model_dump())
    db.add(row)
    await db.flush()
    await audit(db, actor, "budget_account_group", row.id, "created", group_out(row))
    await db.commit()
    return group_out(row)


@router.patch("/groups/{group_id}")
async def update_group(group_id: int, data: GroupPatch, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require(db, actor, SETTINGS_RESOURCE, "edit")
    row = await _group(db, actor, group_id)
    changes = data.model_dump(exclude_unset=True)
    if changes.get("code"):
        await _assert_code_free(db, BudgetAccountGroup, actor.organization_id, changes["code"], exclude_id=row.id)
    if "parent_id" in changes:
        await _assert_group_parent(db, actor, row.id, changes["parent_id"])
    for field, value in changes.items():
        if value is None and field in {"code", "name", "kind", "sort", "is_active"}:
            continue
        setattr(row, field, value)
    await audit(db, actor, "budget_account_group", row.id, "updated", changes)
    await db.commit()
    return group_out(row)


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(group_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require(db, actor, SETTINGS_RESOURCE, "archive")
    row = await _group(db, actor, group_id)
    accounts = int(await db.scalar(select(func.count(BudgetAccount.id)).where(BudgetAccount.group_id == row.id)) or 0)
    children = int(await db.scalar(select(func.count(BudgetAccountGroup.id)).where(BudgetAccountGroup.parent_id == row.id)) or 0)
    if accounts or children:
        raise BudgetError(409, "budget_group_in_use", "Бүлэгт данс эсвэл дэд бүлэг байгаа тул устгах боломжгүй. Идэвхгүй болгоно уу.", accounts=accounts, children=children)
    await audit(db, actor, "budget_account_group", row.id, "deleted", group_out(row))
    await db.delete(row)
    await db.commit()


# ─── Budget accounts ───────────────────────────────────────────────────────────

async def _account(db: AsyncSession, actor: ActorContext, account_id: int) -> BudgetAccount:
    row = await db.scalar(select(BudgetAccount).where(BudgetAccount.id == account_id, BudgetAccount.organization_id == actor.organization_id))
    if not row:
        raise BudgetError(404, "budget_account_not_found", "Төсөвт данс олдсонгүй")
    return row


async def _set_links(db: AsyncSession, actor: ActorContext, account: BudgetAccount, erp_account_ids: list[int]) -> None:
    """Replace the ledger accounts behind a budget account (one owner per ledger account)."""
    wanted = set(erp_account_ids)
    if wanted:
        valid = set((await db.execute(select(ERPAccount.id).where(ERPAccount.organization_id == actor.organization_id, ERPAccount.id.in_(wanted), ERPAccount.is_group.is_(False)))).scalars().all())
        if valid != wanted:
            raise BudgetError(422, "budget_invalid_erp_account", "Санхүүгийн данс олдсонгүй эсвэл бүлэг данс байна", erp_account_ids=sorted(wanted - valid))
        taken = (await db.execute(
            select(ERPAccount.code, BudgetAccount.code, BudgetAccount.name)
            .join(BudgetAccountLink, BudgetAccountLink.erp_account_id == ERPAccount.id)
            .join(BudgetAccount, BudgetAccount.id == BudgetAccountLink.budget_account_id)
            .where(BudgetAccountLink.organization_id == actor.organization_id, BudgetAccountLink.erp_account_id.in_(wanted), BudgetAccountLink.budget_account_id != account.id)
        )).all()
        if taken:
            erp_code, owner_code, owner_name = taken[0]
            raise BudgetError(409, "budget_account_link_taken", f"{erp_code} санхүүгийн данс “{owner_code} {owner_name}” төсөвт дансанд холбогдсон байна. Нэг данс зөвхөн нэг төсөвт дансанд хамаарна.",
                              conflicts=[{"erp_account_code": row[0], "budget_account_code": row[1]} for row in taken])
    await db.execute(delete(BudgetAccountLink).where(BudgetAccountLink.budget_account_id == account.id))
    db.add_all([BudgetAccountLink(organization_id=actor.organization_id, budget_account_id=account.id, erp_account_id=erp_id) for erp_id in sorted(wanted)])
    await db.flush()


async def _account_response(db: AsyncSession, row: BudgetAccount) -> dict[str, Any]:
    return (await accounts_out(db, [row]))[0]


@router.post("/accounts", status_code=status.HTTP_201_CREATED)
async def create_account(data: AccountInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require(db, actor, SETTINGS_RESOURCE, "create")
    await _assert_code_free(db, BudgetAccount, actor.organization_id, data.code)
    if data.group_id is not None:
        await _group(db, actor, data.group_id)
    values = data.model_dump(exclude={"erp_account_ids"})
    row = BudgetAccount(organization_id=actor.organization_id, **values)
    db.add(row)
    await db.flush()
    await _set_links(db, actor, row, data.erp_account_ids)
    await audit(db, actor, "budget_account", row.id, "created", {**values, "erp_account_ids": data.erp_account_ids})
    await db.commit()
    return await _account_response(db, row)


@router.patch("/accounts/{account_id}")
async def update_account(account_id: int, data: AccountPatch, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require(db, actor, SETTINGS_RESOURCE, "edit")
    row = await _account(db, actor, account_id)
    changes = data.model_dump(exclude_unset=True)
    if changes.get("code"):
        await _assert_code_free(db, BudgetAccount, actor.organization_id, changes["code"], exclude_id=row.id)
    if changes.get("group_id") is not None:
        await _group(db, actor, changes["group_id"])
    if "kind" in changes and changes["kind"] and changes["kind"] != row.kind:
        # Existing budgets were signed for the old kind; changing it would flip their meaning.
        if await db.scalar(select(BudgetEntry.id).where(BudgetEntry.budget_account_id == row.id).limit(1)):
            raise BudgetError(409, "budget_account_kind_locked", "Төсөвт ашиглагдсан дансны төрлийг өөрчлөх боломжгүй. Шинэ данс үүсгэнэ үү.")
    links = changes.pop("erp_account_ids", None)
    for field, value in changes.items():
        if value is None and field in {"code", "name", "kind", "sort", "is_active"}:
            continue
        setattr(row, field, value)
    if links is not None:
        await _set_links(db, actor, row, links)
    await audit(db, actor, "budget_account", row.id, "updated", {**changes, **({"erp_account_ids": links} if links is not None else {})})
    await db.commit()
    return await _account_response(db, row)


@router.delete("/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(account_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require(db, actor, SETTINGS_RESOURCE, "archive")
    row = await _account(db, actor, account_id)
    if await db.scalar(select(BudgetEntry.id).where(BudgetEntry.budget_account_id == row.id).limit(1)):
        raise BudgetError(409, "budget_account_in_use", "Төсөвт ашиглагдсан данс тул устгах боломжгүй. Идэвхгүй болгоно уу.")
    await audit(db, actor, "budget_account", row.id, "deleted", {"code": row.code, "name": row.name})
    await db.delete(row)
    await db.commit()


@router.post("/accounts/generate")
async def generate_accounts(data: GenerateAccountsInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    """One budget account per unlinked income/expense ledger account (d161 step ③ shortcut)."""
    await require(db, actor, SETTINGS_RESOURCE, "create")
    org = actor.organization_id
    await ensure_budget_defaults(db, org)
    linked = set((await db.execute(select(BudgetAccountLink.erp_account_id).where(BudgetAccountLink.organization_id == org))).scalars().all())
    statement = select(ERPAccount).where(ERPAccount.organization_id == org, ERPAccount.is_group.is_(False), ERPAccount.is_active.is_(True),
                                         ERPAccount.classification.in_(tuple(CLASSIFICATION_KINDS)))
    if data.erp_account_ids is not None:
        statement = statement.where(ERPAccount.id.in_(data.erp_account_ids))
    candidates = [row for row in (await db.execute(statement.order_by(ERPAccount.code))).scalars().all() if row.id not in linked]
    default_groups = {}
    for kind in ("income", "expense"):
        default_groups[kind] = await db.scalar(select(BudgetAccountGroup.id).where(BudgetAccountGroup.organization_id == org, BudgetAccountGroup.kind == kind,
                                                                                    BudgetAccountGroup.is_active.is_(True)).order_by(BudgetAccountGroup.sort).limit(1))
    used_codes = set((await db.execute(select(BudgetAccount.code).where(BudgetAccount.organization_id == org))).scalars().all())
    created: list[BudgetAccount] = []
    for ledger in candidates:
        code = ledger.code
        suffix = 2
        while code in used_codes:
            code, suffix = f"{ledger.code}-{suffix}", suffix + 1
        used_codes.add(code)
        kind = CLASSIFICATION_KINDS[ledger.classification]
        row = BudgetAccount(organization_id=org, code=code, name=ledger.name, kind=kind, group_id=default_groups.get(kind), sort=0)
        db.add(row)
        await db.flush()
        db.add(BudgetAccountLink(organization_id=org, budget_account_id=row.id, erp_account_id=ledger.id))
        created.append(row)
    await db.flush()
    await audit(db, actor, "budget_accounts", org, "generated", {"created": [row.code for row in created]})
    await db.commit()
    return {"created": len(created), "accounts": await accounts_out(db, created)}
