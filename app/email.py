"""Transactional email delivery through authenticated SMTP."""
from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import parseaddr
from html import escape
from urllib.parse import urlencode

logger = logging.getLogger(__name__)


def _base_url(base_url: str | None) -> str:
    return (
        base_url
        or os.getenv("APP_BASE_URL", "http://127.0.0.1:8000")
    ).rstrip("/")


def _send(to: str, subject: str, text: str, html: str) -> dict:
    host = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
    username = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").replace(" ", "").strip()
    sender = os.getenv(
        "EMAIL_FROM",
        f"JobTrail HK <{username}>",
    ).strip()

    if not username or not password:
        logger.warning(
            "Email not sent: SMTP_USER or SMTP_PASSWORD is missing."
        )
        return {"delivered": False, "provider": "smtp"}

    port = int(os.getenv("SMTP_PORT", "587"))
    if port not in {465, 587}:
        raise ValueError(
            "SMTP_PORT must be 587 (STARTTLS) or 465 (SSL)."
        )

    sender_address = parseaddr(sender)[1]
    if not sender_address:
        raise ValueError("EMAIL_FROM must contain a valid sender address.")

    message = EmailMessage()
    message["From"] = sender
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text)
    message.add_alternative(html, subtype="html")

    context = ssl.create_default_context()

    if port == 465:
        with smtplib.SMTP_SSL(
            host, port, timeout=20, context=context
        ) as smtp:
            smtp.login(username, password)
            smtp.send_message(
                message,
                from_addr=sender_address,
                to_addrs=[to],
            )
    else:
        with smtplib.SMTP(host, port, timeout=20) as smtp:
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
            smtp.login(username, password)
            smtp.send_message(
                message,
                from_addr=sender_address,
                to_addrs=[to],
            )

    return {"delivered": True, "provider": "smtp"}


def send_verification_email(
    to: str,
    raw_token: str,
    base_url: str | None = None,
) -> dict:
    query = urlencode({"token": raw_token})
    link = f"{_base_url(base_url)}/verify-email?{query}"

    text = (
        "Welcome to JobTrail HK!\n\n"
        "Verify your email address by opening this link:\n"
        f"{link}\n\n"
        "This link expires in 24 hours and can be used once.\n"
        "If you did not create this account, ignore this email."
    )

    html = (
        "<p>Welcome to JobTrail HK!</p>"
        f'<p><a href="{escape(link, quote=True)}">'
        "Verify your email address"
        "</a></p>"
        "<p>This link expires in 24 hours and can be used once.</p>"
        "<p>If you did not create this account, ignore this email.</p>"
    )

    return _send(
        to,
        "Verify your JobTrail HK email",
        text,
        html,
    )


def send_password_reset_email(
    to: str,
    raw_token: str,
    base_url: str | None = None,
) -> dict:
    query = urlencode({"token": raw_token})
    link = f"{_base_url(base_url)}/reset-password?{query}"

    text = (
        "A password reset was requested for your JobTrail HK account.\n\n"
        "Choose a new password by opening this link:\n"
        f"{link}\n\n"
        "This link expires in 1 hour and can be used once.\n"
        "If you did not request this, ignore this email."
    )

    html = (
        "<p>A password reset was requested for your JobTrail HK account.</p>"
        f'<p><a href="{escape(link, quote=True)}">'
        "Choose a new password"
        "</a></p>"
        "<p>This link expires in 1 hour and can be used once.</p>"
        "<p>If you did not request this, ignore this email.</p>"
    )

    return _send(
        to,
        "Reset your JobTrail HK password",
        text,
        html,
    )
