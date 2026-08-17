"""Google Calendar OAuth, mapping, outbound, and incremental inbound sync."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import aiohttp
from jose import JWTError, jwt
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.models import (
    CalendarConnection,
    CalendarEntry,
    CalendarEventLink,
    DomainEvent,
    Employee,
    GoogleCalendarOAuthState,
    JobQueue,
    Organization,
    Task,
    UserAccount,
)
from app.services.secret_box import decrypt_secret, encrypt_secret


AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
CALENDAR_API = "https://www.googleapis.com/calendar/v3"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
SCOPE = "https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/calendar.readonly openid email"
OAUTH_STATE_TTL = timedelta(minutes=10)


def is_configured() -> bool:
    return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET and settings.GOOGLE_REDIRECT_URI)


def _code_challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def _signed_state(account_id: int, nonce: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {"sub": str(account_id), "kind": "google_calendar_oauth", "nonce": nonce, "iat": now, "exp": now + int(OAUTH_STATE_TTL.total_seconds())},
        settings.SECRET_KEY,
        algorithm="HS256",
    )


def authorization_url(account_id: int, code_verifier: str | None = None, nonce: str | None = None) -> str:
    verifier = code_verifier or secrets.token_urlsafe(48)
    nonce = nonce or secrets.token_urlsafe(24)
    values = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
        "state": _signed_state(account_id, nonce),
        "code_challenge": _code_challenge(verifier),
        "code_challenge_method": "S256",
    }
    return AUTH_URL + "?" + urlencode(values)


async def create_oauth_state(db: AsyncSession, account_id: int) -> str:
    verifier = secrets.token_urlsafe(48)
    nonce = secrets.token_urlsafe(24)
    db.add(GoogleCalendarOAuthState(account_id=account_id, nonce_hash=hashlib.sha256(nonce.encode()).hexdigest(), encrypted_code_verifier=encrypt_secret(verifier), expires_at=datetime.now(timezone.utc) + OAUTH_STATE_TTL))
    await db.flush()
    return authorization_url(account_id, verifier, nonce)


def _state_payload(state: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(state, settings.SECRET_KEY, algorithms=["HS256"])
        if payload.get("kind") != "google_calendar_oauth" or not payload.get("nonce"):
            raise ValueError("Invalid OAuth state")
        return payload
    except (JWTError, KeyError, ValueError, TypeError) as exc:
        raise ValueError("Invalid or expired OAuth state") from exc


def account_from_state(state: str) -> int:
    try:
        return int(_state_payload(state)["sub"])
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError("Invalid or expired OAuth state") from exc


async def consume_oauth_state(db: AsyncSession, state: str) -> tuple[int, str]:
    payload = _state_payload(state)
    now = datetime.now(timezone.utc)
    nonce_hash = hashlib.sha256(str(payload["nonce"]).encode()).hexdigest()
    record = (await db.execute(select(GoogleCalendarOAuthState).where(GoogleCalendarOAuthState.nonce_hash == nonce_hash, GoogleCalendarOAuthState.used_at.is_(None), GoogleCalendarOAuthState.expires_at > now).with_for_update())).scalar_one_or_none()
    if not record or record.account_id != account_from_state(state):
        raise ValueError("Invalid or expired OAuth state")
    record.used_at = now
    return record.account_id, decrypt_secret(record.encrypted_code_verifier)


async def exchange_code(code: str, code_verifier: str | None = None) -> dict[str, Any]:
    data: dict[str, str] = {"code": code, "client_id": settings.GOOGLE_CLIENT_ID, "client_secret": settings.GOOGLE_CLIENT_SECRET, "redirect_uri": settings.GOOGLE_REDIRECT_URI, "grant_type": "authorization_code"}
    if code_verifier:
        data["code_verifier"] = code_verifier
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
        async with session.post(TOKEN_URL, data=data) as response:
            payload = await response.json(content_type=None)
            if response.status != 200 or "access_token" not in payload:
                raise RuntimeError(f"Google token exchange failed: {payload.get('error', response.status)}")
            return payload


async def access_token(db: AsyncSession, connection: CalendarConnection) -> str:
    now = datetime.now(timezone.utc)
    if connection.encrypted_access_token and connection.token_expires_at and connection.token_expires_at > now + timedelta(minutes=2):
        return decrypt_secret(connection.encrypted_access_token)
    if not connection.encrypted_refresh_token:
        raise RuntimeError("Google refresh token is unavailable; reconnect Calendar")
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
        async with session.post(TOKEN_URL, data={"refresh_token": decrypt_secret(connection.encrypted_refresh_token), "client_id": settings.GOOGLE_CLIENT_ID, "client_secret": settings.GOOGLE_CLIENT_SECRET, "grant_type": "refresh_token"}) as response:
            payload = await response.json(content_type=None)
            if response.status != 200 or "access_token" not in payload:
                connection.status = "error"
                connection.last_error = str(payload.get("error", response.status))[:1000]
                await db.flush()
                raise RuntimeError("Google access token refresh failed; reconnect Calendar")
    connection.encrypted_access_token = encrypt_secret(payload["access_token"])
    connection.token_expires_at = now + timedelta(seconds=int(payload.get("expires_in", 3600)))
    connection.status = "active"
    connection.last_error = None
    await db.flush()
    return payload["access_token"]


async def fetch_connection_metadata(db: AsyncSession, connection: CalendarConnection) -> None:
    token = await access_token(db, connection)
    headers = {"Authorization": f"Bearer {token}"}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
        async with session.get(USERINFO_URL, headers=headers) as response:
            if response.status == 200:
                profile = await response.json(content_type=None)
                connection.google_account_email = profile.get("email") or connection.google_account_email
        async with session.get(f"{CALENDAR_API}/users/me/calendarList/{connection.calendar_id}", headers=headers) as response:
            payload = await response.json(content_type=None)
            if response.status == 200:
                connection.calendar_name = payload.get("summary") or payload.get("summaryOverride") or connection.calendar_id
                connection.calendar_timezone = payload.get("timeZone") or connection.calendar_timezone
            elif response.status not in {404, 410}:
                raise RuntimeError(f"Google calendar metadata failed: {payload.get('error', response.status)}")


async def list_calendars(db: AsyncSession, connection: CalendarConnection) -> list[dict[str, Any]]:
    token = await access_token(db, connection)
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
        async with session.get(f"{CALENDAR_API}/users/me/calendarList", headers={"Authorization": f"Bearer {token}"}, params={"minAccessRole": "writer"}) as response:
            payload = await response.json(content_type=None)
            if response.status != 200:
                raise RuntimeError(f"Google calendar list failed: {payload.get('error', response.status)}")
            return [{"id": item.get("id"), "name": item.get("summaryOverride") or item.get("summary") or item.get("id"), "time_zone": item.get("timeZone"), "primary": item.get("primary", False)} for item in payload.get("items", []) if item.get("id")]


def _timezone_for(connection: CalendarConnection, employee: Employee | None = None) -> ZoneInfo:
    name = (employee.timezone if employee else None) or connection.calendar_timezone or "Asia/Ulaanbaatar"
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("Asia/Ulaanbaatar")


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if value.tzinfo else value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _fingerprint(entity_type: str, entity: Task | CalendarEntry) -> str:
    if entity_type == "task":
        values = {"type": "task", "title": entity.title, "description": entity.description or "", "start": entity.start_at.isoformat() if entity.start_at else None, "end": entity.deadline_at.isoformat() if entity.deadline_at else None, "all_day": bool(entity.is_all_day), "status": entity.workflow_status}
    else:
        values = {"type": "calendar_entry", "title": entity.title, "description": entity.description or "", "start": entity.starts_at.isoformat(), "end": entity.ends_at.isoformat(), "all_day": bool(entity.is_all_day), "recurrence": entity.recurrence_rule}
    return hashlib.sha256(json.dumps(values, sort_keys=True, default=str).encode()).hexdigest()


def _event_body(entity_type: str, entity: Task | CalendarEntry, tz: ZoneInfo, fingerprint: str) -> dict[str, Any] | None:
    if entity_type == "task":
        if entity.is_archived or entity.workflow_status == "cancelled":
            return None
        start = entity.start_at or entity.deadline_at
        end = entity.deadline_at if entity.deadline_at and start and entity.deadline_at > start else (start + timedelta(hours=1) if start else None)
        recurrence = None
    else:
        start, end, recurrence = entity.starts_at, entity.ends_at, entity.recurrence_rule
    if not start or not end:
        return None
    if getattr(entity, "is_all_day", False):
        local_start = start.astimezone(tz).date() if start.tzinfo else start.date()
        local_end = end.astimezone(tz).date() if end.tzinfo else end.date()
        if local_end <= local_start:
            local_end = local_start + timedelta(days=1)
        start_payload, end_payload = {"date": local_start.isoformat()}, {"date": local_end.isoformat()}
    else:
        start_payload, end_payload = {"dateTime": _iso(start), "timeZone": str(tz)}, {"dateTime": _iso(end), "timeZone": str(tz)}
    body: dict[str, Any] = {"summary": entity.title, "description": entity.description or "", "start": start_payload, "end": end_payload, "extendedProperties": {"private": {"oyunsEntityType": entity_type, "oyunsEntityId": str(entity.id), "oyunsPlatformFingerprint": fingerprint, "oyunsSource": "platform"}}}
    if recurrence:
        body["recurrence"] = [recurrence] if isinstance(recurrence, str) else recurrence
    return body


async def _link_for_entity(db: AsyncSession, connection_id: int, entity_type: str, entity_id: int) -> CalendarEventLink | None:
    column = CalendarEventLink.task_id if entity_type == "task" else CalendarEventLink.calendar_entry_id
    return (await db.execute(select(CalendarEventLink).where(CalendarEventLink.connection_id == connection_id, column == entity_id))).scalar_one_or_none()


async def sync_entity(db: AsyncSession, connection_id: int, entity_type: str, entity_id: int, operation: str = "upsert", external_event_id: str | None = None) -> None:
    connection = await db.get(CalendarConnection, connection_id)
    if not connection or connection.status != "active":
        return
    link = await _link_for_entity(db, connection_id, entity_type, entity_id)
    entity = await db.get(Task if entity_type == "task" else CalendarEntry, entity_id)
    if operation == "delete" or not entity:
        event_id = link.external_event_id if link else external_event_id
        if event_id:
            token = await access_token(db, connection)
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
                async with session.delete(f"{CALENDAR_API}/calendars/{connection.calendar_id}/events/{event_id}", headers={"Authorization": f"Bearer {token}"}) as response:
                    if response.status not in {204, 404, 410}:
                        payload = await response.json(content_type=None)
                        raise RuntimeError(f"Google Calendar delete failed: {payload.get('error', response.status)}")
            if link:
                await db.delete(link)
        return
    account = await db.get(UserAccount, connection.account_id)
    employee = await db.get(Employee, account.employee_id) if account and account.employee_id else None
    tz = _timezone_for(connection, employee)
    fingerprint = _fingerprint(entity_type, entity)
    body = _event_body(entity_type, entity, tz, fingerprint)
    if body is None:
        return await sync_entity(db, connection_id, entity_type, entity_id, "delete")
    token = await access_token(db, connection)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    url = f"{CALENDAR_API}/calendars/{connection.calendar_id}/events"
    method = "post"
    if link:
        url += f"/{link.external_event_id}"
        method = "put"
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
        async with getattr(session, method)(url, headers=headers, json=body) as response:
            payload = await response.json(content_type=None)
            if response.status in {404, 410} and link:
                await db.delete(link)
                await db.flush()
                return await sync_entity(db, connection_id, entity_type, entity_id, "upsert")
            if response.status not in {200, 201}:
                raise RuntimeError(f"Google Calendar sync failed: {payload.get('error', response.status)}")
    if not link:
        link = CalendarEventLink(connection_id=connection.id, task_id=entity.id if entity_type == "task" else None, calendar_entry_id=entity.id if entity_type == "calendar_entry" else None, external_event_id=payload["id"])
        db.add(link)
    link.external_event_id = payload["id"]
    link.external_recurring_event_id = payload.get("recurringEventId")
    link.external_etag = payload.get("etag")
    link.external_updated_at = datetime.now(timezone.utc)
    link.platform_version = entity.version
    link.platform_fingerprint = fingerprint
    link.source = "platform"
    link.conflict_state = "none"
    link.sync_state = "synced"
    link.last_error = None
    connection.last_synced_at = datetime.now(timezone.utc)
    connection.last_error = None


async def sync_task(db: AsyncSession, account_id: int, task_id: int) -> None:
    connection = (await db.execute(select(CalendarConnection).where(CalendarConnection.account_id == account_id, CalendarConnection.provider == "google", CalendarConnection.status == "active"))).scalar_one_or_none()
    if connection:
        await sync_entity(db, connection.id, "task", task_id)


async def sync_calendar_entry(db: AsyncSession, account_id: int, entry_id: int, operation: str = "upsert") -> None:
    connection = (await db.execute(select(CalendarConnection).where(CalendarConnection.account_id == account_id, CalendarConnection.provider == "google", CalendarConnection.status == "active"))).scalar_one_or_none()
    if connection:
        await sync_entity(db, connection.id, "calendar_entry", entry_id, operation)


async def queue_entity_sync(db: AsyncSession, account_id: int, entity_type: str, entity_id: int, version: int | None, operation: str = "upsert") -> None:
    connection = (await db.execute(select(CalendarConnection).where(CalendarConnection.account_id == account_id, CalendarConnection.provider == "google", CalendarConnection.status == "active"))).scalar_one_or_none()
    if not connection:
        return
    key = f"calendar-outbound:{connection.id}:{entity_type}:{entity_id}:{version or 'delete'}:{operation}"
    if not await db.scalar(select(JobQueue.id).where(JobQueue.dedup_key == key)):
        payload = {"connection_id": connection.id, "entity_type": entity_type, "entity_id": entity_id, "operation": operation}
        if operation == "delete":
            link = await _link_for_entity(db, connection.id, entity_type, entity_id)
            if link:
                payload["external_event_id"] = link.external_event_id
        db.add(JobQueue(job_type="calendar_outbound", payload=payload, dedup_key=key))


async def queue_account_sync(db: AsyncSession, connection_id: int) -> None:
    connection = await db.get(CalendarConnection, connection_id)
    if not connection or connection.status != "active":
        return
    key = f"calendar-account-sync:{connection.id}:{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}"
    if not await db.scalar(select(JobQueue.id).where(JobQueue.dedup_key == key)):
        db.add(JobQueue(job_type="calendar_account_sync", payload={"connection_id": connection.id}, dedup_key=key))


async def sync_connection(db: AsyncSession, connection_id: int) -> None:
    connection = await db.get(CalendarConnection, connection_id)
    if not connection or connection.status != "active":
        return
    account = await db.get(UserAccount, connection.account_id)
    if not account:
        return
    tasks = (await db.execute(select(Task).where(Task.organization_id == account.organization_id, Task.is_archived.is_(False), or_(Task.start_at.isnot(None), Task.deadline_at.isnot(None))))).scalars().all()
    entries = (await db.execute(select(CalendarEntry).where(CalendarEntry.organization_id == account.organization_id, or_(CalendarEntry.account_id == account.id, CalendarEntry.visibility == "company")))).scalars().all()
    for task in tasks:
        await sync_entity(db, connection.id, "task", task.id)
    for entry in entries:
        await sync_entity(db, connection.id, "calendar_entry", entry.id)
    await incremental_sync(db, connection.id)


def webhook_url() -> str:
    return settings.GOOGLE_WEBHOOK_URL or f"{settings.PUBLIC_APP_URL.rstrip('/')}/api/v1/integrations/google-calendar/webhook"


async def register_watch(db: AsyncSession, connection_id: int) -> None:
    connection = await db.get(CalendarConnection, connection_id)
    if not connection or connection.status != "active":
        raise RuntimeError("Google Calendar connection is unavailable")
    if connection.webhook_channel_id and connection.webhook_resource_id:
        await stop_watch(db, connection)
    token = await access_token(db, connection)
    channel_id, channel_token = secrets.token_urlsafe(24), secrets.token_urlsafe(32)
    body = {"id": channel_id, "type": "web_hook", "address": webhook_url(), "token": channel_token, "params": {"ttl": "604800"}}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
        async with session.post(f"{CALENDAR_API}/calendars/{connection.calendar_id}/events/watch", headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, json=body) as response:
            payload = await response.json(content_type=None)
            if response.status not in {200, 201}:
                raise RuntimeError(f"Google Calendar watch failed: {payload.get('error', response.status)}")
    connection.webhook_channel_id = payload.get("id", channel_id)
    connection.webhook_resource_id = payload.get("resourceId")
    connection.encrypted_channel_token = encrypt_secret(channel_token)
    expiration = payload.get("expiration")
    connection.channel_expires_at = datetime.fromtimestamp(int(expiration) / 1000, timezone.utc) if expiration else datetime.now(timezone.utc) + timedelta(days=7)
    connection.last_webhook_message_number = None
    connection.last_error = None
    connection.sync_failure_count = 0


async def stop_watch(db: AsyncSession, connection: CalendarConnection) -> None:
    if not connection.webhook_channel_id or not connection.webhook_resource_id:
        return
    token = await access_token(db, connection)
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
        async with session.post(f"{CALENDAR_API}/channels/stop", headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, json={"id": connection.webhook_channel_id, "resourceId": connection.webhook_resource_id}) as response:
            if response.status not in {200, 204, 404, 410}:
                raise RuntimeError(f"Google Calendar channel stop failed: {response.status}")


def _event_datetime(value: dict | None) -> datetime | None:
    raw = (value or {}).get("dateTime")
    if not raw:
        return None
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _event_range(event: dict, tz: ZoneInfo) -> tuple[datetime, datetime, bool]:
    start, end = event.get("start") or {}, event.get("end") or {}
    if start.get("date"):
        first = date.fromisoformat(start["date"])
        last = date.fromisoformat(end.get("date") or (first + timedelta(days=1)).isoformat())
        return datetime.combine(first, datetime.min.time(), tzinfo=tz), datetime.combine(last, datetime.min.time(), tzinfo=tz), True
    starts_at = _event_datetime(start) or datetime.now(timezone.utc)
    ends_at = _event_datetime(end) or starts_at + timedelta(hours=1)
    return starts_at, ends_at, False


async def incremental_sync(db: AsyncSession, connection_id: int) -> None:
    connection = await db.get(CalendarConnection, connection_id)
    if not connection or connection.status != "active":
        return
    account = await db.get(UserAccount, connection.account_id)
    organization = await db.get(Organization, account.organization_id) if account else None
    if not account or not organization:
        raise RuntimeError("Calendar account is unavailable")
    employee = await db.get(Employee, account.employee_id) if account.employee_id else None
    tz = _timezone_for(connection, employee)
    token = await access_token(db, connection)
    params: dict[str, str] = {"showDeleted": "true", "maxResults": "2500", "singleEvents": "false"}
    if connection.sync_cursor:
        params["syncToken"] = connection.sync_cursor
    else:
        params["timeMin"] = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    page_token, reset_attempted = None, False
    while True:
        request_params = dict(params)
        if page_token:
            request_params["pageToken"] = page_token
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            async with session.get(f"{CALENDAR_API}/calendars/{connection.calendar_id}/events", headers={"Authorization": f"Bearer {token}"}, params=request_params) as response:
                payload = await response.json(content_type=None)
                if response.status == 410 and not reset_attempted:
                    connection.sync_cursor = None
                    params.pop("syncToken", None)
                    params["timeMin"] = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
                    reset_attempted = True
                    page_token = None
                    continue
                if response.status != 200:
                    raise RuntimeError(f"Google incremental sync failed: {payload.get('error', response.status)}")
        for event in payload.get("items", []):
            external_id = event.get("id")
            if not external_id:
                continue
            private = ((event.get("extendedProperties") or {}).get("private") or {})
            recurring_id = event.get("recurringEventId")
            link = (await db.execute(select(CalendarEventLink).where(CalendarEventLink.connection_id == connection.id, or_(CalendarEventLink.external_event_id == external_id, CalendarEventLink.external_recurring_event_id == external_id, CalendarEventLink.external_event_id == recurring_id, CalendarEventLink.external_recurring_event_id == recurring_id)))).scalar_one_or_none()
            entity_type, entity_id = private.get("oyunsEntityType"), private.get("oyunsEntityId")
            if not link and entity_type in {"task", "calendar_entry"} and str(entity_id).isdigit():
                link = await _link_for_entity(db, connection.id, entity_type, int(entity_id))
                if link:
                    link.external_event_id = external_id
            if event.get("status") == "cancelled":
                if link:
                    link.conflict_state = "google_deleted"
                    link.sync_state = "queued"
                    await queue_entity_sync(db, account.id, "task" if link.task_id else "calendar_entry", link.task_id or link.calendar_entry_id, link.platform_version, "upsert")
                continue
            incoming_fingerprint = private.get("oyunsPlatformFingerprint")
            if link:
                if incoming_fingerprint and incoming_fingerprint == link.platform_fingerprint:
                    link.external_etag = event.get("etag")
                    link.external_updated_at = datetime.now(timezone.utc)
                    link.sync_state, link.conflict_state = "synced", "none"
                else:
                    link.conflict_state = "platform_wins"
                    link.sync_state = "queued"
                    await queue_entity_sync(db, account.id, "task" if link.task_id else "calendar_entry", link.task_id or link.calendar_entry_id, link.platform_version, "upsert")
                continue
            starts_at, ends_at, is_all_day = _event_range(event, tz)
            if ends_at <= starts_at:
                continue
            recurrence = (event.get("recurrence") or [None])[0]
            entry = CalendarEntry(organization_id=account.organization_id, account_id=account.id, created_by_account_id=account.id, kind="event", visibility="private", title=event.get("summary") or "Google Calendar event", description=event.get("description"), starts_at=starts_at, ends_at=ends_at, is_all_day=is_all_day, recurrence_rule=recurrence, recurrence_exceptions=[], version=1)
            db.add(entry)
            await db.flush()
            db.add(CalendarEventLink(connection_id=connection.id, calendar_entry_id=entry.id, external_event_id=external_id, external_recurring_event_id=recurring_id or (external_id if event.get("recurrence") else None), external_etag=event.get("etag"), source="google", platform_version=entry.version, sync_state="synced", platform_fingerprint=_fingerprint("calendar_entry", entry)))
            db.add(DomainEvent(organization_id=account.organization_id, topic="calendar", aggregate_type="calendar_entry", aggregate_id=entry.id, aggregate_version=entry.version, operation="google_imported", payload={"entry_id": entry.id, "google_event_id": external_id}))
        page_token = payload.get("nextPageToken")
        if not page_token:
            connection.sync_cursor = payload.get("nextSyncToken", connection.sync_cursor)
            break
    connection.last_synced_at = datetime.now(timezone.utc)
    connection.last_error = None
    connection.sync_failure_count = 0
