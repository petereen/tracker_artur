from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select

from app.core.database import AsyncSessionLocal
from app.models.contracts import ContractArchiveEntry, ContractDocument
from app.models.models import RoleAssignment, UserAccount
from app.services.user_notifications import create_notifications


async def reconcile_contract_expiry_reminders() -> None:
    """Notify each organization's active legal counsel on configured dates."""
    today = datetime.now(ZoneInfo("Asia/Ulaanbaatar")).date()
    async with AsyncSessionLocal() as db:
        contracts = (await db.execute(
            select(ContractDocument).where(
                ContractDocument.status.in_({"APPROVED", "SIGNED_AND_STAMPED"}),
                ContractDocument.effective_end_on.is_not(None),
                ContractDocument.effective_end_on >= today,
                ContractDocument.effective_end_on <= today + timedelta(days=365),
            )
        )).scalars().all()
        for contract in contracts:
            days_before = (contract.effective_end_on - today).days
            is_expired_today = days_before == 0
            if not is_expired_today and days_before not in (contract.expiry_reminder_days or []):
                continue
            legal_account_ids = set((await db.execute(
                select(UserAccount.id)
                .join(RoleAssignment, RoleAssignment.account_id == UserAccount.id)
                .where(
                    UserAccount.organization_id == contract.organization_id,
                    UserAccount.status == "active",
                    RoleAssignment.role == "legal_counsel",
                    or_(RoleAssignment.valid_from.is_(None), RoleAssignment.valid_from <= today),
                    or_(RoleAssignment.valid_until.is_(None), RoleAssignment.valid_until >= today),
                )
            )).scalars().all())
            if not legal_account_ids:
                continue
            expired_label = "гэрээ" if contract.document_type == "contract" else "хэлэлцээр"
            kind = "contract_expired" if is_expired_today else "contract_expiry_reminder"
            title = "Гэрээний хугацаа дууслаа" if is_expired_today else "Гэрээний хугацаа дуусах гэж байна"
            body = (
                f"{expired_label.capitalize()} “{contract.title}” өнөөдөр дууслаа."
                if is_expired_today
                else f"{expired_label.capitalize()} “{contract.title}” {days_before} хоногийн дараа дуусна."
            )
            await create_notifications(
                db,
                organization_id=contract.organization_id,
                account_ids=legal_account_ids,
                kind=kind,
                title=title,
                body=body,
                target_url=f"/contracts/{contract.public_id}",
                payload={"contract_id": contract.id, "public_id": str(contract.public_id), "effective_end_on": str(contract.effective_end_on), "days_before_expiry": days_before},
                dedup_key=f"contract-expiry:{contract.id}:{contract.effective_end_on}:days:{days_before}",
            )
        archive_entries = (await db.execute(
            select(ContractArchiveEntry).where(
                ContractArchiveEntry.review_status == "approved",
                ContractArchiveEntry.deleted_at.is_(None),
                ContractArchiveEntry.expiry_on.is_not(None),
                ContractArchiveEntry.expiry_on >= today,
                ContractArchiveEntry.expiry_on <= today + timedelta(days=365),
            )
        )).scalars().all()
        for entry in archive_entries:
            days_before = (entry.expiry_on - today).days
            is_expired_today = days_before == 0
            if not is_expired_today and days_before not in (entry.expiry_reminder_days or []):
                continue
            legal_account_ids = set((await db.execute(
                select(UserAccount.id)
                .join(RoleAssignment, RoleAssignment.account_id == UserAccount.id)
                .where(
                    UserAccount.organization_id == entry.organization_id,
                    UserAccount.status == "active",
                    RoleAssignment.role == "legal_counsel",
                    or_(RoleAssignment.valid_from.is_(None), RoleAssignment.valid_from <= today),
                    or_(RoleAssignment.valid_until.is_(None), RoleAssignment.valid_until >= today),
                )
            )).scalars().all())
            if not legal_account_ids:
                continue
            kind = "contract_expired" if is_expired_today else "contract_expiry_reminder"
            title = "Гэрээний хугацаа дууслаа" if is_expired_today else "Гэрээний хугацаа дуусах гэж байна"
            body = (
                f"Архивласан “{entry.name}” баримтын хугацаа өнөөдөр дууслаа."
                if is_expired_today
                else f"Архивласан “{entry.name}” баримтын хугацаа {days_before} хоногийн дараа дуусна."
            )
            dedup_subject = f"{entry.contract_id}" if entry.contract_id else f"archive:{entry.id}"
            await create_notifications(
                db,
                organization_id=entry.organization_id,
                account_ids=legal_account_ids,
                kind=kind,
                title=title,
                body=body,
                target_url="/contracts/archive",
                payload={"archive_entry_id": entry.id, "contract_id": entry.contract_id, "effective_end_on": str(entry.expiry_on), "days_before_expiry": days_before},
                dedup_key=f"contract-expiry:{dedup_subject}:{entry.expiry_on}:days:{days_before}",
            )
        await db.commit()
