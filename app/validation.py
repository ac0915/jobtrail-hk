"""Shared validation and URL helpers for JobTrail HK."""

from __future__ import annotations

from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

ALLOWED_STATUSES = (
    "saved",
    "applied",
    "interview",
    "offer",
    "rejected",
    "closed",
)

TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "fbclid",
    "gclid",
    "mc_eid",
    "igshid",
}


def normalize_status(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip().lower()
    if not cleaned:
        return None
    if cleaned not in ALLOWED_STATUSES:
        raise ValueError(
            "Status must be one of: saved, applied, interview, offer, rejected, closed."
        )
    return cleaned


def require_non_empty(value: Optional[str], label: str) -> str:
    if value is None or not str(value).strip():
        raise ValueError(f"{label} is required and cannot be empty.")
    cleaned = str(value).strip()
    if len(cleaned) > 200:
        raise ValueError(f"{label} is too long (max 200 characters).")
    return cleaned


def normalize_url(value: Optional[str]) -> Optional[str]:
    """Normalize a job URL for storage and duplicate checks.

    Returns None for blank input. Raises ValueError for invalid URLs.
    """
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None

    if "://" not in raw:
        raw = "https://" + raw

    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL must use http or https.")
    if not parsed.netloc:
        raise ValueError("URL is not valid.")

    host = parsed.netloc.lower()
    path = parsed.path.rstrip("/") or ""
    query_pairs = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k.lower() not in TRACKING_PARAMS
    ]
    query = urlencode(query_pairs, doseq=True)
    return urlunparse((parsed.scheme, host, path, "", query, ""))


def optional_text(value: Optional[str], max_len: int = 2000) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) > max_len:
        raise ValueError(f"Text is too long (max {max_len} characters).")
    return cleaned
