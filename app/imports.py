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

    keys = parse_qs(parsed.query).get("jk", [])

    if (
        parsed.scheme == "https"
        and parsed.netloc in {
            "hk.indeed.com",
            "www.indeed.com",
        }
        and parsed.path == "/viewjob"
        and len(keys) == 1
        and re.fullmatch(
            r"[A-Za-z0-9_-]{1,100}",
            keys[0],
        )
    ):
        return url, "Indeed", keys[0]

    raise HTTPException(
        status_code=422,
        detail=(
            "Paste a supported JobsDB or Indeed link "
            "identifying one job."
        ),
    )


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
                if response.status_code != 200:
                    raise HTTPException(
                        status_code=502,
                        detail=(
                            "Could not read source "
                            f"(HTTP {response.status_code}). "
                            "Redirects are not followed."
                        ),
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


def extract_jobsdb(scripts, expected_id):
    pattern = re.compile(
        r"\bwindow\.SEEK_REDUX_DATA\s*=\s*"
    )

    for script in scripts:
        source = script["text"]

        for marker in pattern.finditer(source):
            try:
                state, _ = json.JSONDecoder().raw_decode(
                    source[marker.end():].lstrip()
                )
            except (ValueError, RecursionError):
                continue

            job = nested(
                state,
                "jobdetails",
                "result",
                "job",
            )

            if not isinstance(job, dict):
                continue

            if str(job.get("id")) != expected_id:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        "The source returned a different job ID. "
                        "Import stopped."
                    ),
                )

            content = (
                job.get("content")
                or job.get("content2")
            )

            description = clean_description(content)
            sections = split_sections(description)

            return {
                "title": clean_text(job.get("title")),
                "company": clean_text(
                    nested(job, "advertiser", "name")
                ),
                "location": clean_text(
                    nested(job, "location", "label")
                ),
                "salary": clean_text(
                    nested(job, "salary", "label")
                ),
                "posted_at": parse_date(
                    nested(job, "listedAt", "dateTimeUtc")
                    or job.get("listingDate")
                ),
                "apply_by": parse_date(
                    nested(job, "expiresAt", "dateTimeUtc")
                    or job.get("expiryDate")
                ),
                "description": description,
                "responsibilities": sections["responsibilities"],
                "requirements": sections["requirements"],
                "is_expired": job.get("isExpired") is True,
            }

    return None


def walk_job_postings(value):
    if isinstance(value, list):
        for child in value:
            yield from walk_job_postings(child)

    elif isinstance(value, dict):
        types = value.get("@type", [])

        if isinstance(types, str):
            types = [types]

        if (
            isinstance(types, list)
            and "JobPosting" in types
        ):
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

            for key in (
                "addressLocality",
                "addressRegion",
                "addressCountry",
            ):
                value = address.get(key)

                if isinstance(value, dict):
                    value = value.get("name")

                part = clean_text(value)

                if part and part not in parts:
                    parts.append(part)

            name = ", ".join(parts) or None

        else:
            name = clean_text(location.get("name"))

        if name and name not in names:
            names.append(name)

    return clean_text("; ".join(names))


def extract_salary(posting):
    salary = posting.get("baseSalary")

    if not isinstance(salary, dict):
        return None

    def number(value):
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
        ):
            return str(value)

        return None

    value = salary.get("value")
    unit = None

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

    currency = clean_text(salary.get("currency"), 20)

    result = " ".join(
        part for part in (currency, amount) if part
    )

    if unit:
        result += f" / {unit}"

    return clean_text(result)


def extract_jsonld(scripts, target_url):
    postings = []

    for script in scripts:
        script_type = (
            script["attrs"].get("type") or ""
        ).split(";")[0].strip().lower()

        if script_type != "application/ld+json":
            continue

        try:
            postings.extend(
                walk_job_postings(
                    json.loads(script["text"])
                )
            )
        except (ValueError, RecursionError):
            continue

    if not postings:
        return None

    matching = []

    for posting in postings:
        posting_url = posting.get("url")

        if not isinstance(posting_url, str):
            continue

        try:
            if normalize_url(posting_url) == target_url:
                matching.append(posting)
        except ValueError:
            continue

    if len(matching) == 1:
        posting = matching[0]

    elif len(postings) == 1:
        posting = postings[0]
        explicit_url = posting.get("url")

        if (
            isinstance(explicit_url, str)
            and urlparse(explicit_url).netloc
        ):
            try:
                matches_url = (
                    normalize_url(explicit_url) == target_url
                )
            except ValueError:
                matches_url = False

            if not matches_url:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        "Structured data identifies "
                        "a different listing."
                    ),
                )

    else:
        raise HTTPException(
            status_code=502,
            detail=(
                "Multiple job records were found; "
                "the selected listing could not be identified safely."
            ),
        )

    organization = posting.get("hiringOrganization")

    if isinstance(organization, dict):
        company = clean_text(organization.get("name"))
    else:
        company = clean_text(organization)

    description = clean_description(
        posting.get("description")
    )

    sections = split_sections(description)

    return {
        "title": clean_text(posting.get("title")),
        "company": company,
        "location": extract_location(posting),
        "salary": extract_salary(posting),
        "posted_at": parse_date(posting.get("datePosted")),
        "apply_by": parse_date(posting.get("validThrough")),
        "description": description,
        "responsibilities": (
            clean_long_text(posting.get("responsibilities"))
            or sections["responsibilities"]
        ),
        "requirements": (
            clean_long_text(posting.get("qualifications"))
            or sections["requirements"]
        ),
        "is_expired": None,
    }


def build_preview(html, url, source, expected_id):
    parser = PageParser()
    parser.feed(html)

    extracted = None

    if source == "JobsDB":
        extracted = extract_jobsdb(
            parser.scripts,
            expected_id,
        )

    method = (
        "jobsdb_server_state"
        if extracted is not None
        else "jsonld"
    )

    if extracted is None:
        extracted = extract_jsonld(
            parser.scripts,
            url,
        )

    if extracted is None:
        raise HTTPException(
            status_code=502,
            detail=(
                "The page was received, but readable job data "
                "was not found. It may require JavaScript or "
                "verification. No details were guessed."
            ),
        )

    job = {
        key: extracted.get(key)
        for key in (
            "title",
            "company",
            "location",
            "salary",
            "posted_at",
            "apply_by",
            "description",
            "responsibilities",
            "requirements",
        )
    }

    job.update(
        url=url,
        source=source,
        status="saved",
        notes=None,
        applied_at=None,
    )

    missing_required = [
        key
        for key in ("title", "company")
        if not job[key]
    ]

    warnings = []

    if source == "JobsDB":
        warnings.append(
            "Company is the listing advertiser and may be a "
            "recruitment agency rather than the final employer."
        )

    if job["apply_by"]:
        warnings.append(
            "apply_by is the source listing expiry date; "
            "it is not a verified application deadline."
        )

    if extracted.get("is_expired"):
        warnings.append(
            "The source marks this listing as expired."
        )

    return {
        "result": "partial" if missing_required else "ready",
        "job": job,
        "source_job_id": expected_id,
        "extraction_method": method,
        "missing_required": missing_required,
        "missing_optional": [
            key
            for key in ("location", "salary")
            if not job[key]
        ],
        "can_save": not missing_required,
        "warnings": warnings,
        "saved": False,
    }


@router.post("/preview")
async def preview_job(request: ImportRequest):
    url, source, expected_id = supported_target(
        request.url
    )

    try:
        html = await asyncio.wait_for(
            fetch_html(url),
            timeout=20.0,
        )
    except (
        httpx.TimeoutException,
        asyncio.TimeoutError,
    ) as exc:
        raise HTTPException(
            status_code=504,
            detail="Reading the source job page timed out.",
        ) from exc

    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail="Could not connect to the source job page.",
        ) from exc

    return build_preview(
        html,
        url,
        source,
        expected_id,
    )