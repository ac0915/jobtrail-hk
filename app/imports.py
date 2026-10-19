"""Read-only job previews for JobsDB and Indeed."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.validation import normalize_url


router = APIRouter(
    prefix="/imports",
    tags=["Job imports"],
)

HKT = timezone(timedelta(hours=8))

MAX_BYTES = 2_000_000
FETCH_LIMIT = asyncio.Semaphore(3)


class ImportRequest(BaseModel):
    url: str = Field(min_length=1, max_length=8000)


class PageParser(HTMLParser):
    """Collect script contents without executing JavaScript."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.scripts = []
        self.parts = []
        self.attrs = None

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.attrs = dict(attrs)
            self.parts = []

    def handle_data(self, data):
        if self.attrs is not None:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.attrs is not None:
            self.scripts.append({
                "attrs": self.attrs,
                "text": "".join(self.parts),
            })

            self.attrs = None
            self.parts = []
