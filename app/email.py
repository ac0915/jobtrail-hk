"""Transactional email delivery with a local development fallback."""
from __future__ import annotations

import json
import logging
import os
import urllib.request

logger = logging.getLogger(__name__)


def verification_link(raw_token: str, base_url: str | None = None) -> str:
    base = (base_url or os.getenv("APP_BASE_URL", "http://127.0.0.1:8000")).rstrip("/")
    return f"{base}/verify-email?token={raw_token}"


def send_verification_email(to: str, raw_token: str, base_url: str | None = None) -> dict:
    """Send via Resend when configured; otherwise log the link for local testing."""
    link = verification_link(raw_token, base_url)
    api_key = os.getenv("RESEND_API_KEY", "").strip()

    if not api_key:
        logger.warning("Email delivery not configured. Verification link for %s: %s", to, link)
        return {"delivered": False, "provider": "local"}

    payload = {
        "from": os.getenv("EMAIL_FROM", "JobTrail HK <onboarding@resend.dev>"),
        "to": [to],
        "subject": "Verify your JobTrail HK email",
        "html": (
            "<p>Welcome to JobTrail HK.</p>"
            f"<p><a href=\"{link}\">Verify your email address</a></p>"
            "<p>This link expires in 24 hours and can be used once.</p>"
        ),
    }

    request = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode("utf-8"),
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
