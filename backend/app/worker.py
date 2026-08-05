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

from sqlalchemy import or_, select

from app.core.database import AsyncSessionLocal
from app.models.models import JobQueue
from app.observability.sentry import init_from_env
from app.services.email_service import send_auth_email
from app.services.secret_box import decrypt_secret
from app.services.google_calendar import sync_task


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
            elif job.job_type in {"voice_transcription", "assistant_action"}:
                raise RuntimeError(f"{job.job_type} provider is not configured")
            else:
                raise RuntimeError(f"unsupported job type: {job.job_type}")
            job.state = "completed"
            job.last_error = None
        except Exception as exc:  # noqa: BLE001 - job errors are persisted for operators
            job.last_error = str(exc)[:2000]
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
    while True:
        job_id = await claim_job()
        if job_id is None:
            await asyncio.sleep(2)
            continue
        await execute_job(job_id)


if __name__ == "__main__":
    asyncio.run(run())
