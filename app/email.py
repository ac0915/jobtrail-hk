"""Transactional email delivery with a local development fallback."""
from __future__ import annotations

import json
import logging
import os
import urllib.request

logger = logging.getLogger(__name__)


def _send(provider_payload: dict, html: str) -> dict:
    api_key = os.getenv("RESEND_API_KEY", "").strip()

    if not api_key:
        logger.warning("Email delivery not configured. %s", html)
        return {"delivered": False, "provider": "local"}

    request = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(provider_payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=10) as response:
        if response.status >= 400:
            raise RuntimeError(f"Email provider returned HTTP {response.status}.")

    return {"delivered": True, "provider": "resend"}


def _base_url(base_url: str | None) -> str:
    return (base_url or os.getenv("APP_BASE_URL", "http://127.0.0.1:8000")).rstrip("/")


def send_verification_email(to: str, raw_token: str, base_url: str | None = None) -> dict:
    link = f"{_base_url(base_url)}/verify-email?token={raw_token}"
    html = (
        "<p>Welcome to JobTrail HK.</p>"
        f"<p><a href=\"{link}\">Verify your email address</a></p>"
        "<p>This link expires in 24 hours and can be used once.</p>"
    )
    result = _send(
        {
            "from": os.getenv("EMAIL_FROM", "JobTrail HK <onboarding@resend.dev>"),
            "to": [to],
            "subject": "Verify your JobTrail HK email",
            "html": html,
        },
        f"Verification link for {to}: {link}",
    )
    return result


def send_password_reset_email(to: str, raw_token: str, base_url: str | None = None) -> dict:
    link = f"{_base_url(base_url)}/reset-password?token={raw_token}"
    html = (
        "<p>A password reset was requested for your JobTrail HK account.</p>"
        f"<p><a href=\"{link}\">Choose a new password</a></p>"
        "<p>This link expires in 1 hour and can be used once. If you did not request this, ignore this email.</p>"
    )
    return _send(
        {
            "from": os.getenv("EMAIL_FROM", "JobTrail HK <onboarding@resend.dev>"),
            "to": [to],
            "subject": "Reset your JobTrail HK password",
            "html": html,
        },
        f"Password reset link for {to}: {link}",
    )
