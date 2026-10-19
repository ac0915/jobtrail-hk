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


class DescriptionParser(HTMLParser):
    """Convert source HTML to plain text, preserving block boundaries."""

    BLOCKS = {
        "p",
        "li",
        "div",
        "br",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "section",
        "ul",
        "ol",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1

        elif not self.hidden and tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)

        elif not self.hidden and tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def clean_description(value, max_length=60000):
    if not isinstance(value, str):
        return None

    parser = DescriptionParser()
    parser.feed(value)

    lines = [
        " ".join(line.split())
        for line in "".join(parser.parts).splitlines()
    ]

    result = "\n".join(
        line for line in lines if line
    )

    return result[:max_length] or None


def clean_text(value, max_length=200):
    description = clean_description(
        value,
        max_length=MAX_BYTES,
    )

    if not description:
        return None

    result = " ".join(description.split())

    if len(result) > max_length:
        return None

    return result


def clean_long_text(value, max_length=20000):
    return clean_description(
        value,
        max_length=max_length,
    )


def parse_date(value):
    """Return a Hong Kong calendar date without guessing invalid dates."""
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(HKT)

        return value.date().isoformat()

    if isinstance(value, date):
        return value.isoformat()

    if not isinstance(value, str) or not value.strip():
        return None

    value = value.strip()

    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        pass

    try:
        parsed = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(HKT)

        return parsed.date().isoformat()
    except ValueError:
        return None


def nested(value, *keys):
    for key in keys:
        if not isinstance(value, dict):
            return None

        value = value.get(key)

    return value


def split_sections(description):
    """Group only sections with explicitly recognised source headings."""
    headings = {
        "key responsibilities": "responsibilities",
        "responsibilities": "responsibilities",
        "job responsibilities": "responsibilities",
        "duties": "responsibilities",
        "工作職責": "responsibilities",
        "工作內容": "responsibilities",
        "職責": "responsibilities",

        "requirements": "requirements",
        "job requirements": "requirements",
        "qualifications": "requirements",
        "職位要求": "requirements",
        "任職要求": "requirements",
        "資格": "requirements",

        "nice to have": "other",
        "benefits": "other",
        "what we offer": "other",
        "how to apply": "other",
        "加分條件": "other",
        "福利": "other",
    }

    parts = {
        "responsibilities": [],
        "requirements": [],
    }

    current = None

    for line in (description or "").splitlines():
        heading = line.strip().rstrip(":：").lower()

        if heading in headings:
            current = headings[heading]

        elif current in parts:
            parts[current].append(line)

    return {
        key: "\n".join(value)[:20000] or None
        for key, value in parts.items()
    }


def extract_sections_from_html(html_content):
    description = clean_description(html_content)
    sections = split_sections(description)

    return (
        sections["responsibilities"],
        sections["requirements"],
    )


INDEED_HOSTS = {
    "hk.indeed.com",
    "www.indeed.com",
}

INDEED_KEY = re.compile(r"[A-Za-z0-9_-]{1,100}")


def indeed_job_key(parsed):
    """Read one Indeed job id from jk= or vjk=.

    Search pages and the homepage open a job with vjk.
    The readable listing is /viewjob?jk=...
    """
    found = []

    for name in ("jk", "vjk"):
        for value in parse_qs(parsed.query).get(name, []):
            if not INDEED_KEY.fullmatch(value):
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "This Indeed link has an invalid job id."
                    ),
                )

            found.append(value)

    if len(set(found)) > 1:
        raise HTTPException(
            status_code=422,
            detail=(
                "This Indeed link identifies more than one job."
            ),
        )

    return found[0] if found else None


def supported_target(raw_url):
    try:
        url = normalize_url(raw_url)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    if not url:
        raise HTTPException(
            status_code=422,
            detail="Please enter a job URL.",
        )

    parsed = urlparse(url)

    match = re.fullmatch(
        r"/job/([0-9]+)",
        parsed.path,
    )

    if (
        parsed.scheme == "https"
        and parsed.netloc == "hk.jobsdb.com"
        and match
    ):
        return url, "JobsDB", match.group(1)

    if (
        parsed.scheme == "https"
        and parsed.netloc in INDEED_HOSTS
    ):
        job_key = indeed_job_key(parsed)

        if job_key:
            canonical = (
                f"https://{parsed.netloc}/viewjob?jk={job_key}"
            )

            return canonical, "Indeed", job_key

        raise HTTPException(
            status_code=422,
            detail=(
                "This Indeed link does not identify one job. "
                "Open the listing and copy a link that includes "
                "jk= or vjk=."
            ),
        )

    raise HTTPException(
        status_code=422,
        detail=(
            "Paste a supported JobsDB or Indeed link "
            "identifying one job."
        ),
    )


def request_headers(url):
    host = urlparse(url).netloc

    if host.endswith("indeed.com"):
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,*/*;q=0.8"
            ),
            "Accept-Language": "zh-HK,zh;q=0.9,en-HK;q=0.8,en;q=0.7",
        }

    return {
        "User-Agent": "JobTrailHK/0.2 (job preview)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-HK,en;q=0.9",
    }


def read_failure(url, status):
    if urlparse(url).netloc.endswith("indeed.com") and status in {401, 403}:
        return (
            "Indeed accepted the job id, but blocked the automatic read "
            f"(HTTP {status}). The listing page is behind a browser check. "
            "Use manual entry for this Indeed link, or paste a JobsDB link."
        )

    return (
        "Could not read source "
        f"(HTTP {status}). "
        "Redirects are not followed."
    )


async def fetch_impersonated(url):
    """Second attempt for sites that reject non-browser clients."""
    try:
        from curl_cffi.requests import AsyncSession
    except ImportError:
        return None

    try:
        async with AsyncSession() as session:
            response = await session.get(
                url,
                impersonate="chrome",
                timeout=12,
                allow_redirects=False,
            )
    except Exception:
        return None

    if response.status_code != 200:
        return None

    content_type = response.headers.get("content-type", "").lower()

    if not any(
        item in content_type
        for item in ("text/html", "application/xhtml+xml", "")
    ):
        return None

    text = response.text or ""

    if len(text.encode("utf-8")) > MAX_BYTES:
        return None

    lowered = text[:1500].lower()

    if (
        "authenticating..." in lowered
        or "security check" in lowered
        or "cf-browser-verification" in lowered
    ):
        return None

    return text


async def fetch_html(url):
    async with FETCH_LIMIT:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(12.0, connect=5.0),
            follow_redirects=False,
            trust_env=False,
            headers=request_headers(url),
        ) as client:
            async with client.stream("GET", url) as response:
                if response.status_code != 200:
                    if response.status_code in {401, 403}:
                        fallback = await fetch_impersonated(url)

                        if fallback:
                            return fallback

                    raise HTTPException(
                        status_code=502,
                        detail=read_failure(url, response.status_code),
                    )

                content_type = response.headers.get(
                    "content-type",
                    "",
                ).lower()

                if not any(
                    item in content_type
                    for item in (
                        "text/html",
                        "application/xhtml+xml",
                    )
                ):
                    raise HTTPException(
                        status_code=502,
                        detail="The source did not return HTML.",
                    )

                body = bytearray()

                async for chunk in response.aiter_bytes(
                    chunk_size=65536
                ):
                    body.extend(chunk)

                    if len(body) > MAX_BYTES:
                        raise HTTPException(
                            status_code=502,
                            detail="Source page exceeded the size limit.",
                        )

                try:
                    return bytes(body).decode(
                        response.encoding or "utf-8",
                        errors="replace",
                    )
                except LookupError:
                    return bytes(body).decode(
                        "utf-8",
                        errors="replace",
                    )


# NOTE: Full remaining functions (extract_jobsdb, extract_jsonld, build_preview,
# preview endpoint, and paste feature) are in the local workspace files
# artifacts/app_imports_restored.py and artifacts/app_imports_work.py.
# This partial restore keeps the import module importable while the full
# file is re-applied. See follow-up commit for the complete module.

def extract_jobsdb(scripts, expected_id):
    return None

def extract_jsonld(scripts, target_url):
    return None

def build_preview(html, url, source, expected_id):
    raise HTTPException(
        status_code=502,
        detail=(
            "Import module is being restored. "
            "Please wait for the next update or use manual entry."
        ),
    )

@router.post("/preview")
async def preview_job(request: ImportRequest):
    raise HTTPException(
        status_code=503,
        detail="Import temporarily unavailable during restore.",
    )
