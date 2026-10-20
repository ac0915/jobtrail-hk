"""Serve the JobTrail HK website from plain or compressed sources."""
from __future__ import annotations

import base64
import zlib
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import HTMLResponse

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"
WEB_FILE = WEB_DIR / "index.html"


def load_website_html() -> str:
    if WEB_FILE.is_file():
        text = WEB_FILE.read_text(encoding="utf-8")
        if len(text) > 5000 and "JobTrail HK — restoring" not in text:
            return text

    parts = sorted(WEB_DIR.glob("_index_part*.b64"))
    if parts:
        payload = "".join(
            "".join(p.read_text(encoding="utf-8").split())
            for p in parts
        )
        return zlib.decompress(base64.b64decode(payload)).decode("utf-8")

    if WEB_FILE.is_file():
        return WEB_FILE.read_text(encoding="utf-8")

    raise HTTPException(
        status_code=500,
        detail="Website file missing: create web/index.html.",
    )


def website_response() -> HTMLResponse:
    return HTMLResponse(content=load_website_html())
