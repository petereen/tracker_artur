from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.models import (
    ChatAttachment,
    ChatConversation,
    ChatMessage,
    ChatParticipant,
    Employee,
    MobilePushRegistration,
    UserAccount,
)
from app.services.attachment_storage import delete_attachment
from app.services.secret_box import decrypt_secret


_fcm_access_token: tuple[str, datetime] | None = None
_apns_provider_token: tuple[str, datetime] | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalized_private_key(value: str) -> str:
    return value.replace("\\n", "\n")


def _chat_push_allowed(message: ChatMessage, participant: ChatParticipant, recipient_account_id: int) -> bool:
    return not (
        message.deleted_at
        or message.sender_account_id == recipient_account_id
        or (participant.muted_until and participant.muted_until > _now())
    )


async def _fcm_token(client: httpx.AsyncClient, service_account: dict) -> str:
    global _fcm_access_token
    now = _now()
    if _fcm_access_token and _fcm_access_token[1] > now + timedelta(minutes=2):
        return _fcm_access_token[0]
    token_uri = service_account.get("token_uri") or "https://oauth2.googleapis.com/token"
    assertion = jwt.encode(
        {
            "iss": service_account["client_email"],
            "scope": "https://www.googleapis.com/auth/firebase.messaging",
            "aud": token_uri,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=55)).timestamp()),
        },
        _normalized_private_key(service_account["private_key"]),
        algorithm="RS256",
    )
    response = await client.post(token_uri, data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion})
    response.raise_for_status()
    payload = response.json()
    expires_at = now + timedelta(seconds=int(payload.get("expires_in", 3600)))
    _fcm_access_token = (payload["access_token"], expires_at)
    return payload["access_token"]


def _apns_token() -> str:
    global _apns_provider_token
    now = _now()
    if _apns_provider_token and _apns_provider_token[1] > now + timedelta(minutes=40):
        return _apns_provider_token[0]
    token = jwt.encode(
        {"iss": settings.APNS_TEAM_ID, "iat": int(now.timestamp())},
        _normalized_private_key(settings.APNS_PRIVATE_KEY),
        algorithm="ES256",
        headers={"kid": settings.APNS_KEY_ID},
    )
    _apns_provider_token = (token, now + timedelta(minutes=50))
    return token


async def _send_fcm(client: httpx.AsyncClient, token: str, *, title: str, body: str, target_url: str, message_id: int, conversation_public_id: str) -> bool:
    service_account = json.loads(settings.FCM_SERVICE_ACCOUNT_JSON)
    project_id = settings.FCM_PROJECT_ID or service_account.get("project_id")
    if not project_id:
        raise RuntimeError("FCM project ID is not configured")
    access_token = await _fcm_token(client, service_account)
    response = await client.post(
        f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"message": {
            "token": token,
            "notification": {"title": title, "body": body},
            "data": {"target_url": target_url, "message_id": str(message_id), "conversation_public_id": conversation_public_id},
            "android": {
                "priority": "high",
                "notification": {
                    "channel_id": "oyuns-chat-v1",
                    "sound": "oyuns_chat_notification",
                    "tag": f"chat-message-{message_id}",
                },
            },
        }},
    )
    if response.status_code in {400, 404} and any(marker in response.text for marker in ("UNREGISTERED", "registration-token-not-registered", "INVALID_ARGUMENT")):
        return False
    response.raise_for_status()
    return True


async def _send_apns(client: httpx.AsyncClient, token: str, *, title: str, body: str, target_url: str, message_id: int, conversation_public_id: str) -> bool:
    host = "https://api.sandbox.push.apple.com" if settings.APNS_USE_SANDBOX else "https://api.push.apple.com"
    response = await client.post(
        f"{host}/3/device/{token}",
        headers={
            "authorization": f"bearer {_apns_token()}",
            "apns-topic": settings.APNS_BUNDLE_ID,
            "apns-push-type": "alert",
            "apns-priority": "10",
            "apns-collapse-id": f"chat-message-{message_id}",
        },
        json={
            "aps": {
                "alert": {"title": title, "body": body},
                "sound": "public/sounds/oyuns_chat_notification.caf",
                "thread-id": f"chat-{conversation_public_id}",
            },
            "target_url": target_url,
            "message_id": message_id,
            "conversation_public_id": conversation_public_id,
        },
    )
    if response.status_code == 410 or (response.status_code == 400 and any(marker in response.text for marker in ("BadDeviceToken", "DeviceTokenNotForTopic", "Unregistered"))):
        return False
    response.raise_for_status()
    return True


async def deliver_chat_push(db: AsyncSession, message_id: int, recipient_account_id: int) -> None:
    if not settings.MOBILE_PUSH_DELIVERY_ENABLED:
        return
    row = (
        await db.execute(
            select(ChatMessage, ChatConversation, ChatParticipant)
            .join(ChatConversation, ChatConversation.id == ChatMessage.conversation_id)
            .join(ChatParticipant, ChatParticipant.conversation_id == ChatConversation.id)
            .where(
                ChatMessage.id == message_id,
                ChatParticipant.account_id == recipient_account_id,
                ChatParticipant.left_at.is_(None),
            )
        )
    ).one_or_none()
    if not row:
        return
    message, conversation, participant = row
    if not _chat_push_allowed(message, participant, recipient_account_id):
        return
    sender_row = (
        await db.execute(
            select(UserAccount, Employee)
            .outerjoin(Employee, Employee.id == UserAccount.employee_id)
            .where(UserAccount.id == message.sender_account_id)
        )
    ).one_or_none()
    sender_name = sender_row[1].name if sender_row and sender_row[1] else sender_row[0].email if sender_row else "OYUNS Chat"
    attachment_count = int(await db.scalar(select(ChatAttachment.id).where(ChatAttachment.message_id == message.id).limit(1)) or 0)
    title = conversation.title if conversation.kind == "group" else sender_name
    body = message.body or ("Attachment" if attachment_count else "New message")
    if conversation.kind == "group":
        body = f"{sender_name}: {body}"
    body = body[:180]
    target_url = f"/chat/{conversation.public_id}?message={message.id}"
    registrations = list((await db.execute(select(MobilePushRegistration).where(MobilePushRegistration.account_id == recipient_account_id, MobilePushRegistration.organization_id == conversation.organization_id, MobilePushRegistration.is_active.is_(True)))).scalars().all())
    if not registrations:
        return
    async with httpx.AsyncClient(timeout=20, http2=True) as client:
        for registration in registrations:
            token = decrypt_secret(registration.encrypted_token)
            if registration.provider == "fcm":
                if not settings.FCM_SERVICE_ACCOUNT_JSON:
                    continue
                valid = await _send_fcm(client, token, title=title, body=body, target_url=target_url, message_id=message.id, conversation_public_id=str(conversation.public_id))
            else:
                if not all((settings.APNS_TEAM_ID, settings.APNS_KEY_ID, settings.APNS_PRIVATE_KEY, settings.APNS_BUNDLE_ID)):
                    continue
                valid = await _send_apns(client, token, title=title, body=body, target_url=target_url, message_id=message.id, conversation_public_id=str(conversation.public_id))
            if not valid:
                registration.is_active = False
                registration.revoked_at = _now()


async def purge_expired_chat_uploads(db: AsyncSession) -> int:
    rows = list((await db.execute(select(ChatAttachment).where(ChatAttachment.message_id.is_(None), ChatAttachment.expires_at <= _now()).limit(200))).scalars().all())
    for item in rows:
        await delete_attachment(item.storage_key)
        await db.delete(item)
    return len(rows)
