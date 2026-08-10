"""Minimal-scope Google Calendar OAuth and outbound task synchronization."""

from __future__ import annotations

import secrets
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import aiohttp
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.models import CalendarConnection, CalendarEventLink, DomainEvent, Task, UserAccount
from app.services.secret_box import decrypt_secret, encrypt_secret


AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
CALENDAR_API = "https://www.googleapis.com/calendar/v3"
SCOPE = "https://www.googleapis.com/auth/calendar.events"


def is_configured() -> bool:
    return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET and settings.GOOGLE_REDIRECT_URI)


def authorization_url(account_id: int) -> str:
    now = int(time.time())
    state = jwt.encode({"sub": str(account_id), "kind": "google_calendar_oauth", "nonce": secrets.token_urlsafe(16), "iat": now, "exp": now + 600}, settings.SECRET_KEY, algorithm="HS256")
    return AUTH_URL + "?" + urlencode({"client_id": settings.GOOGLE_CLIENT_ID, "redirect_uri": settings.GOOGLE_REDIRECT_URI, "response_type": "code", "scope": SCOPE, "access_type": "offline", "include_granted_scopes": "true", "prompt": "consent", "state": state})


def account_from_state(state: str) -> int:
    try:
        payload = jwt.decode(state, settings.SECRET_KEY, algorithms=["HS256"])
        if payload.get("kind") != "google_calendar_oauth":
            raise ValueError("Invalid OAuth state")
        return int(payload["sub"])
    except (JWTError, KeyError, ValueError) as exc:
        raise ValueError("Invalid or expired OAuth state") from exc


async def exchange_code(code: str) -> dict:
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
        async with session.post(TOKEN_URL, data={"code": code, "client_id": settings.GOOGLE_CLIENT_ID, "client_secret": settings.GOOGLE_CLIENT_SECRET, "redirect_uri": settings.GOOGLE_REDIRECT_URI, "grant_type": "authorization_code"}) as response:
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


async def sync_task(db: AsyncSession, account_id: int, task_id: int) -> None:
    connection = (await db.execute(select(CalendarConnection).where(CalendarConnection.account_id == account_id, CalendarConnection.provider == "google", CalendarConnection.status == "active"))).scalar_one_or_none()
    task = await db.get(Task, task_id)
    if not connection or not task:
        raise RuntimeError("Google Calendar connection or task is unavailable")
    link = (await db.execute(select(CalendarEventLink).where(CalendarEventLink.connection_id == connection.id, CalendarEventLink.task_id == task.id))).scalar_one_or_none()
    token = await access_token(db, connection)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if task.workflow_status == "cancelled" and link:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
            async with session.delete(f"{CALENDAR_API}/calendars/primary/events/{link.external_event_id}", headers=headers) as response:
                if response.status not in {204, 404, 410}:
                    raise RuntimeError(f"Google Calendar delete failed: {response.status}")
        await db.delete(link)
        return
    start = task.start_at or task.deadline_at or datetime.now(timezone.utc) + timedelta(hours=1)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    end = task.deadline_at if task.deadline_at and task.deadline_at > start else start + timedelta(hours=1)
    event = {"summary": task.title, "description": task.description or "", "start": {"dateTime": start.isoformat()}, "end": {"dateTime": end.isoformat()}, "extendedProperties": {"private": {"oyunsTaskId": str(task.id), "oyunsTaskPublicId": str(task.public_id)}}}
    url = f"{CALENDAR_API}/calendars/primary/events"
    method = "post"
    if link:
        url += f"/{link.external_event_id}"
        method = "put"
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
        async with getattr(session, method)(url, headers=headers, json=event) as response:
            payload = await response.json(content_type=None)
            if response.status not in {200, 201}:
                raise RuntimeError(f"Google Calendar sync failed: {payload.get('error', response.status)}")
    if link:
        link.external_etag = payload.get("etag")
        link.sync_state = "synced"
        link.last_error = None
    else:
        db.add(CalendarEventLink(connection_id=connection.id, task_id=task.id, external_event_id=payload["id"], external_etag=payload.get("etag"), sync_state="synced"))
    connection.last_synced_at = datetime.now(timezone.utc)


def webhook_url() -> str:
    return settings.GOOGLE_WEBHOOK_URL or f"{settings.PUBLIC_APP_URL.rstrip('/')}/api/v1/integrations/google-calendar/webhook"


async def register_watch(db: AsyncSession, connection_id: int) -> None:
    connection = await db.get(CalendarConnection, connection_id)
    if not connection or connection.status != "active":
        raise RuntimeError("Google Calendar connection is unavailable")
    if connection.webhook_channel_id and connection.webhook_resource_id:
        await stop_watch(db, connection)
    token = await access_token(db, connection)
    channel_id = secrets.token_urlsafe(24)
    channel_token = secrets.token_urlsafe(32)
    body = {"id": channel_id, "type": "web_hook", "address": webhook_url(), "token": channel_token, "params": {"ttl": "604800"}}
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
        async with session.post(f"{CALENDAR_API}/calendars/{connection.calendar_id}/events/watch", headers=headers, json=body) as response:
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
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {"id": connection.webhook_channel_id, "resourceId": connection.webhook_resource_id}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
        async with session.post(f"{CALENDAR_API}/channels/stop", headers=headers, json=body) as response:
            if response.status not in {200, 204, 404, 410}:
                raise RuntimeError(f"Google Calendar channel stop failed: {response.status}")


def _event_datetime(value: dict | None) -> datetime | None:
    raw = (value or {}).get("dateTime")
    if not raw:
        return None
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


async def incremental_sync(db: AsyncSession, connection_id: int) -> None:
    connection = await db.get(CalendarConnection, connection_id)
    if not connection or connection.status != "active":
        return
    account = await db.get(UserAccount, connection.account_id)
    if not account:
        raise RuntimeError("Calendar account is unavailable")
    token = await access_token(db, connection)
    headers = {"Authorization": f"Bearer {token}"}
    params: dict[str, str] = {"singleEvents": "true", "showDeleted": "true", "maxResults": "2500"}
    if connection.sync_cursor:
        params["syncToken"] = connection.sync_cursor
    else:
        params["timeMin"] = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    page_token = None
    reset_attempted = False
    while True:
        request_params = dict(params)
        if page_token: request_params["pageToken"] = page_token
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            async with session.get(f"{CALENDAR_API}/calendars/{connection.calendar_id}/events", headers=headers, params=request_params) as response:
                payload = await response.json(content_type=None)
                if response.status == 410 and not reset_attempted:
                    connection.sync_cursor = None
                    params.pop("syncToken", None)
                    params["timeMin"] = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
                    reset_attempted = True
                    continue
                if response.status != 200:
                    raise RuntimeError(f"Google incremental sync failed: {payload.get('error', response.status)}")
        for event in payload.get("items", []):
            external_id = event.get("id")
            if not external_id:
                continue
            link = (await db.execute(select(CalendarEventLink).where(CalendarEventLink.connection_id == connection.id, CalendarEventLink.external_event_id == external_id))).scalar_one_or_none()
            task_id = ((event.get("extendedProperties") or {}).get("private") or {}).get("oyunsTaskId")
            if link is None and task_id and str(task_id).isdigit():
                task = await db.get(Task, int(task_id))
                if task and task.organization_id == account.organization_id:
                    link = CalendarEventLink(connection_id=connection.id, task_id=task.id, external_event_id=external_id, sync_state="synced")
                    db.add(link)
            task = await db.get(Task, link.task_id) if link else None
            if not link or not task or task.organization_id != account.organization_id:
                continue
            if event.get("status") == "cancelled":
                await db.delete(link)
                db.add(DomainEvent(organization_id=account.organization_id, topic="tasks", aggregate_type="task", aggregate_id=task.id, aggregate_version=task.version, operation="calendar_unlinked", payload={"task_id": task.id, "provider": "google"}))
                continue
            if connection.sync_mode == "bidirectional":
                starts_at = _event_datetime(event.get("start")); ends_at = _event_datetime(event.get("end"))
                if starts_at and ends_at and ends_at > starts_at and (task.start_at != starts_at or task.deadline_at != ends_at):
                    task.start_at = starts_at; task.deadline_at = ends_at; task.version += 1; task.updated_at = datetime.now(timezone.utc)
                    db.add(DomainEvent(organization_id=account.organization_id, topic="tasks", aggregate_type="task", aggregate_id=task.id, aggregate_version=task.version, operation="calendar_scheduled", payload={"task_id": task.id, "start_at": starts_at.isoformat(), "deadline_at": ends_at.isoformat()}))
            link.external_etag = event.get("etag"); link.sync_state = "synced"; link.last_error = None
        page_token = payload.get("nextPageToken")
        if not page_token:
            connection.sync_cursor = payload.get("nextSyncToken", connection.sync_cursor)
            break
    connection.last_synced_at = datetime.now(timezone.utc)
    connection.last_error = None
    connection.sync_failure_count = 0
