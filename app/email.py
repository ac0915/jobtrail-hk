"""Transactional email delivery through Gmail API (no SMTP fallback)."""
from __future__ import annotations

import base64
import json
import os
from email.message import EmailMessage
from email.utils import parseaddr
from functools import lru_cache
from html import escape
from pathlib import Path
from threading import Lock
from urllib.parse import urlencode, urlsplit

import httpx

GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.send"
GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
_refresh_lock = Lock()


@lru_cache(maxsize=1)
def _load_credentials(inline: str, filename: str):
    from google.oauth2.credentials import Credentials

    try:
        info = json.loads(inline) if inline else json.loads(Path(filename).read_text(encoding="utf-8"))
        if not isinstance(info, dict):
            raise ValueError()
        scopes = info.get("scopes")
        if scopes is not None:
            scopes = scopes.split() if isinstance(scopes, str) else scopes
            if set(scopes) != {GMAIL_SCOPE}:
                raise ValueError()
        return Credentials.from_authorized_user_info(info, scopes=[GMAIL_SCOPE])
    except Exception:
        raise RuntimeError("Gmail credentials are missing, invalid, or not send-only. Check private configuration.") from None


def _refresh_credentials(credentials):
    import requests
    from google.auth.transport.requests import Request

    with requests.Session() as session:
        adapter = Request(session=session)

        def request(*args, **kwargs):
            kwargs["timeout"] = 20
            return adapter(*args, **kwargs)

        credentials.refresh(request)


def _base_url(base_url: str | None) -> str:
    value = (base_url or os.getenv("APP_BASE_URL", "")).strip().rstrip("/")
    production = os.getenv("APP_ENV", "development").strip().lower() == "production"
    if not value:
        if production:
            raise ValueError("APP_BASE_URL is required in production.")
        value = "http://127.0.0.1:8000"
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("APP_BASE_URL must be an absolute HTTP(S) website URL without credentials, query or fragment.")
    if production and parsed.scheme != "https":
        raise ValueError("APP_BASE_URL must use HTTPS in production.")
    return value


def _send(to: str, subject: str, text: str, html: str) -> dict:
    inline = os.getenv("GMAIL_TOKEN_JSON", "").strip()
    filename = os.getenv("GMAIL_TOKEN_FILE", "").strip()
    if bool(inline) == bool(filename):
        raise RuntimeError("Set exactly one of GMAIL_TOKEN_JSON or GMAIL_TOKEN_FILE in private configuration.")
    sender = os.getenv("EMAIL_FROM", "JobTrail HK <jobtrialhk@gmail.com>").strip()
    sender_address = parseaddr(sender)[1]
    if not sender_address or "@" not in sender_address:
        raise ValueError("EMAIL_FROM must contain a valid sender address.")
    if not to or any(c in to for c in "\r\n") or parseaddr(to)[1] != to or "@" not in to:
        raise ValueError("Recipient must be a plain email address.")

    message = EmailMessage()
    message["From"] = sender
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text)
    message.add_alternative(html, subtype="html")
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")

    try:
        with _refresh_lock:
            credentials = _load_credentials(inline, filename)
            if not credentials.valid:
                _refresh_credentials(credentials)
            access_token = credentials.token
            if not credentials.valid or not access_token:
                raise RuntimeError()
    except Exception:
        raise RuntimeError("Gmail authorization unavailable. Check token expiry, revocation and private configuration.") from None

    try:
        response = httpx.post(
            GMAIL_SEND_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            json={"raw": raw},
            timeout=20,
            follow_redirects=False,
        )
    except httpx.HTTPError:
        raise RuntimeError("Gmail API request failed; delivery is unconfirmed. No automatic resend was attempted.") from None
    if response.status_code != 200:
        raise RuntimeError(f"Gmail API rejected the request (HTTP {response.status_code}).")
    try:
        message_id = response.json().get("id")
        if not isinstance(message_id, str) or not message_id:
            raise ValueError()
    except (ValueError, AttributeError):
        raise RuntimeError("Gmail API returned an unexpected response; delivery is unconfirmed.") from None
    return {"delivered": True, "provider": "gmail_api", "message_id": message_id}


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

    return _send(to, "Verify your JobTrail HK email", text, html)


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

    return _send(to, "Reset your JobTrail HK password", text, html)
