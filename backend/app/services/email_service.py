"""Authentication email delivery through a TLS-protected SMTP provider."""

from __future__ import annotations

import asyncio
import html
import smtplib
import ssl
from email.message import EmailMessage

from app.core.config import settings


def email_is_configured() -> bool:
    return bool(settings.SMTP_HOST and settings.SMTP_PASSWORD and settings.SMTP_FROM and settings.PUBLIC_APP_URL)


def _content(kind: str, action_url: str, locale: str) -> tuple[str, str, str]:
    safe_url = html.escape(action_url, quote=True)
    if kind == "invitation":
        subject = "OYUNS workspace invitation"
        heading = "You have been invited to OYUNS"
        action = "Create password"
    else:
        subject = "OYUNS password reset"
        heading = "Reset your OYUNS password"
        action = "Reset password"
    if locale == "mn":
        subject = "OYUNS нэвтрэх эрх" if kind == "invitation" else "OYUNS нууц үг сэргээх"
        heading = "OYUNS ажлын орчинд урьж байна" if kind == "invitation" else "OYUNS нууц үгээ сэргээнэ үү"
        action = "Нууц үг үүсгэх" if kind == "invitation" else "Нууц үг сэргээх"
    text = f"{heading}\n\n{action}: {action_url}\n\nIf you did not request this, ignore this email."
    body = (
        '<div style="font-family:Arial,sans-serif;max-width:560px;margin:auto;color:#172033">'
        f"<h1 style=\"font-size:24px\">{html.escape(heading)}</h1>"
        '<p>This secure link can be used once and expires automatically.</p>'
        f'<p><a href="{safe_url}" style="display:inline-block;padding:12px 18px;background:#2563eb;color:white;text-decoration:none;border-radius:10px">{html.escape(action)}</a></p>'
        '<p style="font-size:13px;color:#667085">If you did not request this, you can ignore this email.</p></div>'
    )
    return subject, text, body


def _send_sync(*, to: str, kind: str, action_url: str, locale: str, idempotency_key: str) -> None:
    if not email_is_configured():
        raise RuntimeError("Authentication email delivery is not configured")
    subject, text, body = _content(kind, action_url, locale)
    message = EmailMessage()
    message["From"] = settings.SMTP_FROM
    message["To"] = to
    message["Subject"] = subject
    message["Resend-Idempotency-Key"] = idempotency_key[:256]
    message.set_content(text)
    message.add_alternative(body, subtype="html")
    context = ssl.create_default_context()
    if settings.SMTP_USE_TLS and settings.SMTP_PORT in {465, 2465}:
        with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20, context=context) as smtp:
            smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            smtp.send_message(message)
        return
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as smtp:
        if settings.SMTP_USE_TLS:
            smtp.starttls(context=context)
        smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        smtp.send_message(message)


async def send_auth_email(**kwargs: str) -> None:
    await asyncio.to_thread(_send_sync, **kwargs)
