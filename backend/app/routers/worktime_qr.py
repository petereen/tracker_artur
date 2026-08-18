from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.enterprise_deps import ActorContext, get_actor, require_roles
from app.models.models import Employee, IdempotencyRecord, WorkReport, WorkTimeEntry, WorktimeQrKiosk
from app.services.enterprise_events import record_change

try:
    import redis.asyncio as redis
except ImportError:  # pragma: no cover - dependency is present in production
    redis = None


router = APIRouter()
KIOSK_COOKIE = "oyuns_worktime_kiosk"
PAIRING_TTL = timedelta(minutes=10)
QR_OPERATION = "worktime_qr_clock"


class KioskInput(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    location_id: str = Field(default="main_office", min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    display_name: str = Field(default="Main office", min_length=1, max_length=160)


class PairInput(BaseModel):
    code: str = Field(min_length=8, max_length=8, pattern=r"^[A-Za-z0-9]+$")


class ClockInput(BaseModel):
    token: str = Field(min_length=20, max_length=4096)
    client_timestamp: datetime | None = None


def _secret() -> bytes:
    # SECRET_KEY remains a safe development fallback; production deployments
    # should set the dedicated key so QR signing can be rotated independently.
    return (settings.WORKTIME_QR_SIGNING_SECRET or settings.SECRET_KEY).encode()


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _sign(payload: dict) -> str:
    encoded = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signature = _b64(hmac.new(_secret(), encoded.encode(), hashlib.sha256).digest())
    return f"oyuns-worktime:v1:{encoded}.{signature}"


def _decode(token: str) -> dict:
    try:
        parts = token.split(":")
        if len(parts) != 3 or parts[0] != "oyuns-worktime" or parts[1] != "v1":
            raise ValueError
        encoded, signature = parts[2].split(".", 1)
        expected = _b64(hmac.new(_secret(), encoded.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        payload = json.loads(_unb64(encoded))
        if payload.get("v") != 1 or not isinstance(payload.get("nonce"), str):
            raise ValueError
        return payload
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, UnicodeDecodeError, binascii.Error):
        raise HTTPException(status_code=422, detail={"code": "invalid_token", "message": "QR token is invalid"})


async def _limit(key: str, limit: int, *, fail_closed: bool = False) -> bool:
    if redis is None:
        if fail_closed:
            raise HTTPException(status_code=503, detail={"code": "rate_limit_unavailable", "message": "Pairing is temporarily unavailable"})
        return True
    client = None
    try:
        client = redis.from_url(settings.WORKTIME_QR_REDIS_URL, decode_responses=True)
        bucket = f"oyuns:worktime-qr:rate:{key}"
        current = await client.incr(bucket)
        if current == 1:
            await client.expire(bucket, 60)
        return current <= limit
    except Exception:
        if fail_closed:
            raise HTTPException(status_code=503, detail={"code": "rate_limit_unavailable", "message": "Pairing is temporarily unavailable"})
        return True
    finally:
        if client is not None:
            await client.aclose()


def _new_code() -> str:
    return "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))


def _kiosk_out(kiosk: WorktimeQrKiosk, pairing_code: str | None = None) -> dict:
    output = {
        "id": kiosk.id,
        "public_id": str(kiosk.public_id),
        "label": kiosk.label,
        "location_id": kiosk.location_id,
        "display_name": kiosk.display_name,
        "status": kiosk.status,
        "paired_at": kiosk.paired_at,
        "last_seen_at": kiosk.last_seen_at,
        "revoked_at": kiosk.revoked_at,
    }
    if pairing_code:
        output["pairing_code"] = pairing_code
        output["pairing_expires_at"] = kiosk.pairing_expires_at
    return output


async def _kiosk_from_cookie(cookie: str | None, db: AsyncSession) -> WorktimeQrKiosk:
    if not cookie or "." not in cookie:
        raise HTTPException(status_code=401, detail={"code": "kiosk_pairing_required", "message": "Pair this display first"})
    public_id, credential = cookie.split(".", 1)
    try:
        kiosk = await db.scalar(select(WorktimeQrKiosk).where(WorktimeQrKiosk.public_id == uuid.UUID(public_id)))
    except ValueError:
        kiosk = None
    if not kiosk or kiosk.status != "active" or not hmac.compare_digest(kiosk.credential_hash, _digest(credential)):
        raise HTTPException(status_code=401, detail={"code": "kiosk_revoked", "message": "This display must be paired again"})
    return kiosk


@router.get("/kiosks")
async def list_kiosks(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles("admin", "manager"))):
    rows = (await db.execute(select(WorktimeQrKiosk).where(WorktimeQrKiosk.organization_id == actor.organization_id).order_by(WorktimeQrKiosk.label))).scalars().all()
    return [_kiosk_out(row) for row in rows]


@router.post("/kiosks", status_code=status.HTTP_201_CREATED)
async def create_kiosk(data: KioskInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles("admin", "manager"))):
    code = _new_code()
    credential = secrets.token_urlsafe(32)
    kiosk = WorktimeQrKiosk(
        organization_id=actor.organization_id,
        label=data.label.strip(),
        location_id=data.location_id.strip(),
        display_name=data.display_name.strip(),
        credential_hash=_digest(credential),
        pairing_code_hash=_digest(code),
        pairing_expires_at=datetime.now(timezone.utc) + PAIRING_TTL,
        created_by_account_id=actor.account_id,
    )
    db.add(kiosk)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail={"code": "duplicate_kiosk_label", "message": "A kiosk with this label already exists"}) from exc
    await db.refresh(kiosk)
    return _kiosk_out(kiosk, code)


@router.post("/kiosks/{kiosk_id}/pairing-code")
async def renew_pairing_code(kiosk_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles("admin", "manager"))):
    kiosk = await db.scalar(select(WorktimeQrKiosk).where(WorktimeQrKiosk.id == kiosk_id, WorktimeQrKiosk.organization_id == actor.organization_id).with_for_update())
    if not kiosk:
        raise HTTPException(status_code=404, detail={"code": "kiosk_not_found", "message": "Kiosk not found"})
    if kiosk.status != "active":
        raise HTTPException(status_code=409, detail={"code": "kiosk_revoked", "message": "Revoke state must be cleared before pairing"})
    code = _new_code()
    credential = secrets.token_urlsafe(32)
    kiosk.credential_hash = _digest(credential)
    kiosk.pairing_code_hash = _digest(code)
    kiosk.pairing_expires_at = datetime.now(timezone.utc) + PAIRING_TTL
    kiosk.paired_at = None
    await db.commit()
    return _kiosk_out(kiosk, code)


@router.post("/kiosks/{kiosk_id}/revoke")
async def revoke_kiosk(kiosk_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles("admin", "manager"))):
    kiosk = await db.scalar(select(WorktimeQrKiosk).where(WorktimeQrKiosk.id == kiosk_id, WorktimeQrKiosk.organization_id == actor.organization_id).with_for_update())
    if not kiosk:
        raise HTTPException(status_code=404, detail={"code": "kiosk_not_found", "message": "Kiosk not found"})
    kiosk.status = "revoked"
    kiosk.revoked_at = datetime.now(timezone.utc)
    kiosk.pairing_code_hash = None
    kiosk.pairing_expires_at = None
    await db.commit()
    return _kiosk_out(kiosk)


@router.post("/pair")
async def pair_kiosk(data: PairInput, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    address = request.client.host if request.client else "unknown"
    if not await _limit(f"pair:{address}", 5, fail_closed=True):
        raise HTTPException(status_code=429, detail={"code": "rate_limited", "message": "Too many pairing attempts"})
    now = datetime.now(timezone.utc)
    kiosk = await db.scalar(select(WorktimeQrKiosk).where(WorktimeQrKiosk.pairing_code_hash == _digest(data.code.upper())).with_for_update())
    if not kiosk or kiosk.status != "active" or not kiosk.pairing_expires_at or kiosk.pairing_expires_at < now:
        raise HTTPException(status_code=401, detail={"code": "pairing_invalid", "message": "Pairing code is invalid or expired"})
    # The credential was rotated when the code was issued; the cookie only
    # needs the opaque public id and the one-time credential value.
    credential = secrets.token_urlsafe(32)
    kiosk.credential_hash = _digest(credential)
    kiosk.pairing_code_hash = None
    kiosk.pairing_expires_at = None
    kiosk.paired_at = now
    kiosk.last_seen_at = now
    await db.commit()
    response.set_cookie(KIOSK_COOKIE, f"{kiosk.public_id}.{credential}", max_age=settings.WORKTIME_QR_KIOSK_COOKIE_DAYS * 86400, httponly=True, secure=settings.AUTH_COOKIE_SECURE, samesite="strict", path="/api/v1/worktime-qr")
    return {"status": "paired", "kiosk": _kiosk_out(kiosk)}


@router.get("/display-token")
async def display_token(response: Response, kiosk_cookie: str | None = Cookie(default=None, alias=KIOSK_COOKIE), db: AsyncSession = Depends(get_db)):
    kiosk = await _kiosk_from_cookie(kiosk_cookie, db)
    if not await _limit(f"display:{kiosk.id}", 10):
        raise HTTPException(status_code=429, detail={"code": "rate_limited", "message": "Please wait before refreshing the display"})
    now = datetime.now(timezone.utc)
    ttl = max(15, min(30, settings.WORKTIME_QR_ROTATION_SECONDS))
    payload = {"v": 1, "org": kiosk.organization_id, "kiosk": kiosk.id, "location_id": kiosk.location_id, "iat": int(now.timestamp()), "exp": int((now + timedelta(seconds=ttl)).timestamp()), "nonce": _b64(secrets.token_bytes(16))}
    kiosk.last_seen_at = now
    await db.commit()
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    return {"token": _sign(payload), "issued_at": now, "expires_at": now + timedelta(seconds=ttl), "server_time": now, "location_id": kiosk.location_id, "display_name": kiosk.display_name}


def _entry_out(entry: WorkTimeEntry | None) -> dict | None:
    if not entry:
        return None
    return {"id": entry.id, "employee_id": entry.employee_id, "local_work_date": entry.local_work_date, "project_id": entry.project_id, "task_id": entry.task_id, "entry_type": entry.entry_type, "mode": entry.mode, "started_at": entry.started_at, "ended_at": entry.ended_at, "source_channel": entry.source_channel, "source_kiosk_id": entry.source_kiosk_id, "work_location_id": entry.work_location_id, "version": entry.version}


async def _daily_report(db: AsyncSession, employee: Employee, local_day: date) -> WorkReport:
    report = await db.scalar(select(WorkReport).where(WorkReport.employee_id == employee.id, WorkReport.report_type == "daily", WorkReport.period_date == local_day))
    if report:
        return report
    report = WorkReport(employee_id=employee.id, report_type="daily", period_date=local_day, status="awaiting")
    db.add(report)
    await db.flush()
    return report


def _summary(entries: list[WorkTimeEntry], now: datetime) -> dict:
    return {"active": _entry_out(next((entry for entry in reversed(entries) if entry.ended_at is None), None)), "today_entries": [_entry_out(entry) for entry in entries]}


@router.post("/clock")
async def qr_clock(data: ClockInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    if not actor.employee_id:
        raise HTTPException(status_code=409, detail={"code": "employee_unlinked", "message": "Account is not linked to an employee"})
    if not await _limit(f"clock:{actor.account_id}", 10):
        raise HTTPException(status_code=429, detail={"code": "rate_limited", "message": "Too many scan attempts"})
    payload = _decode(data.token)
    now = datetime.now(timezone.utc)
    try:
        issued = int(payload["iat"])
        expires = int(payload["exp"])
        kiosk_id = int(payload["kiosk"])
        organization_id = int(payload["org"])
        location_id = str(payload["location_id"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=422, detail={"code": "invalid_token", "message": "QR token is invalid"})
    grace = max(0, settings.WORKTIME_QR_GRACE_SECONDS)
    if organization_id != actor.organization_id or issued > int(now.timestamp()) + grace:
        raise HTTPException(status_code=422, detail={"code": "invalid_token", "message": "QR token is not valid for this organization"})
    if int(now.timestamp()) > expires + grace:
        raise HTTPException(status_code=410, detail={"code": "expired_token", "message": "QR code expired; scan the current code"})
    employee = await db.scalar(select(Employee).where(Employee.id == actor.employee_id, Employee.is_active.is_(True)).with_for_update())
    kiosk = await db.scalar(select(WorktimeQrKiosk).where(WorktimeQrKiosk.id == kiosk_id, WorktimeQrKiosk.organization_id == actor.organization_id, WorktimeQrKiosk.status == "active"))
    if not employee or not kiosk or kiosk.location_id != location_id:
        raise HTTPException(status_code=422, detail={"code": "invalid_token", "message": "QR code is no longer valid"})
    existing = await db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.account_id == actor.account_id, IdempotencyRecord.operation == QR_OPERATION, IdempotencyRecord.key == payload["nonce"], IdempotencyRecord.expires_at > now))
    if existing and existing.response_body:
        output = dict(existing.response_body)
        output["replayed"] = True
        return output
    local_day = now.astimezone(ZoneInfo(employee.timezone)).date()
    active = await db.scalar(select(WorkTimeEntry).where(WorkTimeEntry.employee_id == employee.id, WorkTimeEntry.ended_at.is_(None)).order_by(WorkTimeEntry.started_at.desc(), WorkTimeEntry.id.desc()).with_for_update())
    entries = (await db.execute(select(WorkTimeEntry).where(WorkTimeEntry.employee_id == employee.id, WorkTimeEntry.local_work_date == local_day).order_by(WorkTimeEntry.started_at, WorkTimeEntry.id).with_for_update())).scalars().all()
    if active and active.entry_type == "break":
        raise HTTPException(status_code=409, detail={"code": "active_break", "message": "Resume or end the break before scanning the office QR"})
    action: Literal["clock_in", "switched_to_office", "clock_out"]
    affected: list[dict] = []
    if active and active.mode == "in_person":
        active.ended_at = now
        active.version += 1
        action = "clock_out"
        affected.append(_entry_out(active))
    else:
        if active:
            active.ended_at = now
            active.version += 1
            affected.append(_entry_out(active))
        report = await _daily_report(db, employee, local_day)
        entry = WorkTimeEntry(report_id=report.id, employee_id=employee.id, local_work_date=local_day, timezone=employee.timezone, entry_type="work", mode="in_person", started_at=now, source_channel="web_qr", source_kiosk_id=kiosk.id, work_location_id=kiosk.location_id)
        db.add(entry)
        await db.flush()
        action = "switched_to_office" if active else "clock_in"
        affected.append(_entry_out(entry))
    await db.flush()
    entries = (await db.execute(select(WorkTimeEntry).where(WorkTimeEntry.employee_id == employee.id, WorkTimeEntry.local_work_date == local_day).order_by(WorkTimeEntry.started_at, WorkTimeEntry.id))).scalars().all()
    response_body = {"action": action, "replayed": False, "location_id": kiosk.location_id, "server_time": now, "timezone": employee.timezone, "affected_entries": affected, "shift_summary": _summary(entries, now)}
    db.add(IdempotencyRecord(account_id=actor.account_id, operation=QR_OPERATION, key=payload["nonce"], request_hash=_digest(data.token), response_status=200, response_body=jsonable_encoder(response_body), expires_at=datetime.fromtimestamp(expires + grace + 60, tz=timezone.utc)))
    await record_change(db, actor=actor, topic="clocks", aggregate_type="time_entry", aggregate_id=affected[-1]["id"], operation=action, after=affected[-1])
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        duplicate = await db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.account_id == actor.account_id, IdempotencyRecord.operation == QR_OPERATION, IdempotencyRecord.key == payload["nonce"]))
        if duplicate and duplicate.response_body:
            output = dict(duplicate.response_body)
            output["replayed"] = True
            return output
        raise
    return response_body
