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
from app.models.models import CalendarConnection, CalendarEventLink, Task
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
