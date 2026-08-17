"""PostgreSQL-backed enterprise job worker.

The worker intentionally has no Redis dependency. Jobs are leased with
SKIP LOCKED so additional replicas can be added safely when throughput grows.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select

from app.core.database import AsyncSessionLocal
from app.models.models import AssistantToolAudit, CalendarConnection, CompanyKnowledge, CompanyLibraryItem, JobQueue, KnowledgeDocument
from app.observability.sentry import init_from_env
from app.services.email_service import send_auth_email
from app.services.secret_box import decrypt_secret
from app.services.google_calendar import incremental_sync, register_watch, sync_connection, sync_entity, sync_task
from app.services.enterprise_tools import index_company_file, index_company_knowledge


log = logging.getLogger(__name__)
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"


async def claim_job() -> int | None:
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        job = (
            await db.execute(
                select(JobQueue)
                .where(
                    JobQueue.run_at <= now,
                    JobQueue.attempts < JobQueue.max_attempts,
                    or_(JobQueue.state == "pending", (JobQueue.state == "running") & (JobQueue.lease_expires_at < now)),
                )
                .order_by(JobQueue.run_at, JobQueue.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
        ).scalar_one_or_none()
        if not job:
            return None
        job.state = "running"
        job.lease_owner = WORKER_ID
        job.lease_expires_at = now + timedelta(minutes=5)
        job.attempts += 1
        await db.commit()
        return job.id


async def execute_job(job_id: int) -> None:
    async with AsyncSessionLocal() as db:
        job = await db.get(JobQueue, job_id)
        if not job or job.lease_owner != WORKER_ID:
            return
        try:
            # The foundation worker owns scheduling and retries. Integration
            # modules register concrete work by job_type as they are enabled.
            if job.job_type == "healthcheck":
                pass
            elif job.job_type == "auth_email":
                payload = job.payload or {}
                await send_auth_email(
                    to=payload["to"],
                    kind=payload["kind"],
                    action_url=decrypt_secret(payload["action_url_encrypted"]),
                    locale=payload.get("locale", "mn"),
                    idempotency_key=payload["idempotency_key"],
                )
            elif job.job_type == "calendar_sync":
                await sync_task(db, int(job.payload["account_id"]), int(job.payload["task_id"]))
            elif job.job_type == "calendar_outbound":
                await sync_entity(db, int(job.payload["connection_id"]), job.payload["entity_type"], int(job.payload["entity_id"]), job.payload.get("operation", "upsert"), job.payload.get("external_event_id"))
            elif job.job_type == "calendar_account_sync":
                await sync_connection(db, int(job.payload["connection_id"]))
            elif job.job_type == "calendar_watch":
                await register_watch(db, int(job.payload["connection_id"]))
            elif job.job_type == "calendar_inbound":
                await incremental_sync(db, int(job.payload["connection_id"]))
            elif job.job_type == "knowledge_index_file":
                item = await db.get(CompanyLibraryItem, int(job.payload["item_id"]))
                if item and item.kind == "file" and item.deleted_at is None:
                    await index_company_file(db, item)
            elif job.job_type == "knowledge_index_article":
                entry = await db.get(CompanyKnowledge, int(job.payload["entry_id"]))
                if entry and entry.is_active:
                    await index_company_knowledge(db, entry)
            elif job.job_type == "assistant_audit_purge":
                now = datetime.now(timezone.utc)
                rows = list((await db.execute(select(AssistantToolAudit).where(AssistantToolAudit.content_expires_at <= now, AssistantToolAudit.encrypted_payload.isnot(None)))).scalars().all())
                for row in rows:
                    row.encrypted_payload = None
                await db.execute(AssistantToolAudit.__table__.delete().where(AssistantToolAudit.metadata_expires_at <= now))
            elif job.job_type in {"voice_transcription", "assistant_action"}:
                raise RuntimeError(f"{job.job_type} provider is not configured")
            else:
                raise RuntimeError(f"unsupported job type: {job.job_type}")
            job.state = "completed"
            job.last_error = None
        except Exception as exc:  # noqa: BLE001 - job errors are persisted for operators
            job.last_error = str(exc)[:2000]
            if job.job_type.startswith("calendar_") and job.payload.get("connection_id"):
                connection = await db.get(CalendarConnection, int(job.payload["connection_id"]))
                if connection:
                    connection.sync_failure_count += 1
                    connection.last_error = job.last_error
            if job.attempts >= job.max_attempts:
                job.state = "failed"
            else:
                job.state = "pending"
                job.run_at = datetime.now(timezone.utc) + timedelta(seconds=min(3600, 15 * 2 ** job.attempts))
            log.exception("Enterprise job %s failed", job.id)
        finally:
            job.lease_owner = None
            job.lease_expires_at = None
            await db.commit()


async def run() -> None:
    logging.basicConfig(level=logging.INFO)
    init_from_env(server_name="tracker-artur-worker")
    last_watch_scan = datetime.min.replace(tzinfo=timezone.utc)
    last_audit_purge = datetime.min.replace(tzinfo=timezone.utc)
    last_index_scan = datetime.min.replace(tzinfo=timezone.utc)
    while True:
        now = datetime.now(timezone.utc)
        if now - last_watch_scan >= timedelta(minutes=15):
            async with AsyncSessionLocal() as db:
                expiring = (await db.execute(select(CalendarConnection).where(CalendarConnection.status == "active", or_(CalendarConnection.channel_expires_at.is_(None), CalendarConnection.channel_expires_at < now + timedelta(hours=24))))).scalars().all()
                for connection in expiring:
                    dedup = f"calendar-watch:{connection.id}:{connection.channel_expires_at.date().isoformat() if connection.channel_expires_at else 'new'}"
                    exists = await db.scalar(select(JobQueue.id).where(JobQueue.dedup_key == dedup, JobQueue.state.in_(("pending", "running", "completed"))))
                    if not exists:
                        db.add(JobQueue(job_type="calendar_watch", payload={"connection_id": connection.id}, dedup_key=dedup))
                await db.commit()
            last_watch_scan = now
        if now - last_audit_purge >= timedelta(days=1):
            async with AsyncSessionLocal() as db:
                dedup = f"assistant-audit-purge:{now.date().isoformat()}"
                exists = await db.scalar(select(JobQueue.id).where(JobQueue.dedup_key == dedup))
                if not exists:
                    db.add(JobQueue(job_type="assistant_audit_purge", payload={}, dedup_key=dedup))
                    await db.commit()
            last_audit_purge = now
        if now - last_index_scan >= timedelta(minutes=15):
            async with AsyncSessionLocal() as db:
                file_rows = list((await db.execute(select(CompanyLibraryItem).outerjoin(KnowledgeDocument, and_(KnowledgeDocument.organization_id == CompanyLibraryItem.organization_id, KnowledgeDocument.source_type == "company_file", KnowledgeDocument.source_id == CompanyLibraryItem.id)).where(CompanyLibraryItem.kind == "file", CompanyLibraryItem.deleted_at.is_(None), or_(KnowledgeDocument.id.is_(None), KnowledgeDocument.checksum != CompanyLibraryItem.checksum, KnowledgeDocument.index_status.in_(("pending", "failed")))).limit(100))).scalars().all())
                for item in file_rows:
                    key = f"knowledge-index-file:{item.id}:{item.checksum}"
                    if not await db.scalar(select(JobQueue.id).where(JobQueue.dedup_key == key)):
                        db.add(JobQueue(job_type="knowledge_index_file", payload={"item_id": item.id}, dedup_key=key))
                article_rows = list((await db.execute(select(CompanyKnowledge).outerjoin(KnowledgeDocument, and_(KnowledgeDocument.organization_id == CompanyKnowledge.organization_id, KnowledgeDocument.source_type == "company_knowledge", KnowledgeDocument.source_id == CompanyKnowledge.id)).where(CompanyKnowledge.organization_id.isnot(None), CompanyKnowledge.is_active.is_(True), or_(KnowledgeDocument.id.is_(None), KnowledgeDocument.index_status.in_(("pending", "failed")))).limit(100))).scalars().all())
                for entry in article_rows:
                    key = f"knowledge-index-article-backfill:{entry.id}:{entry.updated_at.isoformat() if entry.updated_at else 'new'}"
                    if not await db.scalar(select(JobQueue.id).where(JobQueue.dedup_key == key)):
                        db.add(JobQueue(job_type="knowledge_index_article", payload={"entry_id": entry.id}, dedup_key=key))
                if file_rows or article_rows:
                    await db.commit()
            last_index_scan = now
        job_id = await claim_job()
        if job_id is None:
            await asyncio.sleep(2)
            continue
        await execute_job(job_id)


if __name__ == "__main__":
    asyncio.run(run())
