"""Read-only job previews for JobsDB and Indeed."""
from __future__ import annotations

import asyncio
import json
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from app.validation import normalize_url

router = APIRouter(prefix="/imports", tags=["Job imports"])
MAX_BYTES = 2_000_000
FETCH_LIMIT = asyncio.Semaphore(3)


class ImportRequest(BaseModel):
    url: str = Field(min_length=1, max_length=8000)


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.scripts = []
        self.attrs = None
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "script":
            self.attrs = dict(attrs)
            self.parts = []

    def handle_data(self, data):
        if self.attrs is not None:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "script" and self.attrs is not None:
            self.scripts.append({"attrs": self.attrs, "text": "".join(self.parts)})
            self.attrs = None
            self.parts = []


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"script", "style"}:
            self.hidden_depth += 1
        elif not self.hidden_depth:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag.lower() in {"script", "style"}:
            self.hidden_depth = max(0, self.hidden_depth - 1)
        elif not self.hidden_depth:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden_depth:
            self.parts.append(data)


def clean_text(value, max_length=200):
    if not isinstance(value, str):
        return None
    parser = TextParser()
    parser.feed(value)
    result = " ".join("".join(parser.parts).split()).strip()
    return result if result and len(result) <= max_length else None


def nested(data, *keys):
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def supported_target(raw_url):
    try:
        url = normalize_url(raw_url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not url:
        raise HTTPException(status_code=422, detail="Please enter a job URL.")
    parsed = urlparse(url)
    if parsed.scheme == "https" and parsed.netloc == "hk.jobsdb.com":
        match = re.fullmatch(r"/job/([0-9]+)", parsed.path)
        if match:
            return url, "JobsDB", match.group(1)
    if (parsed.scheme == "https"
        and parsed.netloc in {"hk.indeed.com", "www.indeed.com"}
        and parsed.path == "/viewjob"):
        keys = parse_qs(parsed.query).get("jk", [])
        if len(keys) == 1 and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", keys[0]):
            return url, "Indeed", keys[0]
    raise HTTPException(status_code=422, detail=(
        "Please paste a supported JobsDB or Indeed link identifying one job. "
        "General search pages without a job ID are not supported."
    ))


async def fetch_html(url):
    async with FETCH_LIMIT:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(12.0, connect=5.0),
            follow_redirects=False,
            trust_env=False,
            headers={
                "User-Agent": "JobTrailHK/0.2 (job preview)",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-HK,en;q=0.9",
            },
        ) as client:
            async with client.stream("GET", url) as response:
                if 300 <= response.status_code < 400:
                    raise HTTPException(status_code=502, detail=(
                        "The source redirected this request. "
                        "This version does not follow redirects."
                    ))
                if response.status_code != 200:
                    raise HTTPException(status_code=502, detail=(
                        f"Could not read the source job page (source HTTP {response.status_code}). "
                        "The listing may be unavailable or access may be restricted."
                    ))
                content_type = response.headers.get("content-type", "").lower()
                if not any(t in content_type for t in ("text/html", "application/xhtml+xml")):
                    raise HTTPException(status_code=502, detail="The source did not return HTML.")
                body = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    body.extend(chunk)
                    if len(body) > MAX_BYTES:
                        raise HTTPException(status_code=502, detail="The source page exceeded the size limit.")
                try:
                    return bytes(body).decode(response.encoding or "utf-8", errors="replace")
                except LookupError:
                    return bytes(body).decode("utf-8", errors="replace")


def extract_jobsdb(scripts, expected_id):
    decoder = json.JSONDecoder()
    marker = re.compile(r"\bwindow\.SEEK_REDUX_DATA\s*=\s*")
    for script in scripts:
        text = script["text"]
        for match in marker.finditer(text):
            remainder = text[match.end():].lstrip()
            if not remainder.startswith("{"):
                continue
            try:
                state, _ = decoder.raw_decode(remainder)
            except (ValueError, RecursionError):
                continue
            job = nested(state, "jobdetails", "result", "job")
            if not isinstance(job, dict):
                continue
            if str(job.get("id")) != expected_id:
                raise HTTPException(status_code=502, detail="The source returned a different job ID. Import stopped.")
            return {
                "title": clean_text(job.get("title")),
                "company": clean_text(nested(job, "advertiser", "name")),
                "location": clean_text(nested(job, "location", "label")),
                "salary": clean_text(nested(job, "salary", "label")),
                "is_expired": job.get("isExpired") is True,
            }
    return None


def walk_job_postings(value):
    if isinstance(value, list):
        for item in value:
            yield from walk_job_postings(item)
    elif isinstance(value, dict):
        types = value.get("@type", [])
        if isinstance(types, str):
            types = [types]
        if isinstance(types, list) and "JobPosting" in types:
            yield value
            return
        for child in value.values():
            if isinstance(child, (dict, list)):
                yield from walk_job_postings(child)


def extract_location(posting):
    locations = posting.get("jobLocation") or []
    if isinstance(locations, dict):
        locations = [locations]
    if not isinstance(locations, list):
        return None
    names = []
    for location in locations:
        if not isinstance(location, dict):
            continue
        address = location.get("address")
        if isinstance(address, str):
            name = clean_text(address)
        elif isinstance(address, dict):
            parts = []
            for key in ("addressLocality", "addressRegion", "addressCountry"):
                value = address.get(key)
                if isinstance(value, dict):
                    value = value.get("name")
                text = clean_text(value)
                if text and text not in parts:
                    parts.append(text)
            name = ", ".join(parts) or None
        else:
            name = clean_text(location.get("name"))
        if name and name not in names:
            names.append(name)
    result = "; ".join(names)
    return result if result and len(result) <= 200 else None


def extract_salary(posting):
    salary = posting.get("baseSalary")
    if not isinstance(salary, dict):
        return None
    currency = clean_text(salary.get("currency"), 20)
    value = salary.get("value")
    unit = None
    def number(item):
        return str(item) if isinstance(item, (int, float)) and not isinstance(item, bool) else None
    if isinstance(value, dict):
        exact = number(value.get("value"))
        low = number(value.get("minValue"))
        high = number(value.get("maxValue"))
        unit = clean_text(value.get("unitText"), 30)
        if exact is not None:
            amount = exact
        elif low is not None and high is not None:
            amount = f"{low}–{high}"
        elif low is not None:
            amount = f"From {low}"
        elif high is not None:
            amount = f"Up to {high}"
        else:
            return None
    else:
        amount = number(value)
        if amount is None:
            return None
    result = " ".join(part for part in (currency, amount) if part)
    if unit:
        result += f" / {unit}"
    return result if len(result) <= 200 else None


def extract_jsonld(scripts, target_url):
    postings = []
    for script in scripts:
        script_type = (script["attrs"].get("type") or "").split(";")[0].strip().lower()
        if script_type != "application/ld+json":
            continue
        try:
            postings.extend(walk_job_postings(json.loads(script["text"])))
        except (ValueError, RecursionError):
            continue
    if not postings:
        return None
    matching = []
    for posting in postings:
        posting_url = posting.get("url")
        if isinstance(posting_url, str):
            try:
                if normalize_url(posting_url) == target_url:
                    matching.append(posting)
            except ValueError:
                pass
    if len(matching) == 1:
        posting = matching[0]
    elif len(postings) == 1:
        posting = postings[0]
        posting_url = posting.get("url")
        if isinstance(posting_url, str):
            parsed = urlparse(posting_url)
            if parsed.scheme in {"http", "https"} and parsed.netloc:
                try:
                    same = normalize_url(posting_url) == target_url
                except ValueError:
                    same = False
                if not same:
                    raise HTTPException(status_code=502, detail="Structured data identifies a different URL. Import stopped.")
    else:
        raise HTTPException(status_code=502, detail="Multiple job records found; the selected listing could not be identified safely.")
    organization = posting.get("hiringOrganization")
    company = clean_text(organization.get("name")) if isinstance(organization, dict) else clean_text(organization)
    return {
        "title": clean_text(posting.get("title")),
        "company": company,
        "location": extract_location(posting),
        "salary": extract_salary(posting),
        "is_expired": None,
    }


def build_preview(html, url, source, expected_id):
    parser = PageParser()
    parser.feed(html)
    extracted = None
    method = None
    if source == "JobsDB":
        extracted = extract_jobsdb(parser.scripts, expected_id)
        if extracted is not None:
            method = "jobsdb_server_state"
    if extracted is None:
        extracted = extract_jsonld(parser.scripts, url)
        if extracted is not None:
            method = "jsonld"
    if extracted is None:
        raise HTTPException(status_code=502, detail=(
            "The page was received, but readable job data was not found. "
            "It may require JavaScript, show a verification page, or use an unsupported format. "
            "No job details were guessed."
        ))
    job = {
        "title": extracted.get("title"),
        "company": extracted.get("company"),
        "url": url,
        "location": extracted.get("location"),
        "salary": extracted.get("salary"),
        "source": source,
        "status": "saved",
        "notes": None,
        "applied_at": None,
    }
    missing_required = [key for key in ("title", "company") if not job[key]]
    missing_optional = [key for key in ("location", "salary") if not job[key]]
    warnings = []
    if source == "JobsDB":
        warnings.append("Company is the listing advertiser and may be a recruitment agency rather than the final employer.")
    if extracted.get("is_expired") is True:
        warnings.append("The source marks this listing as expired.")
    return {
        "result": "partial" if missing_required else "ready",
        "job": job,
        "source_job_id": expected_id,
        "extraction_method": method,
        "missing_required": missing_required,
        "missing_optional": missing_optional,
        "can_save": not missing_required,
        "warnings": warnings,
        "saved": False,
    }


@router.post("/preview")
async def preview_job(request: ImportRequest):
    url, source, expected_id = supported_target(request.url)
    try:
        html = await asyncio.wait_for(fetch_html(url), timeout=20.0)
    except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
        raise HTTPException(status_code=504, detail="Reading the source job page timed out.") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Could not connect to the source job page.") from exc
    return build_preview(html, url, source, expected_id)