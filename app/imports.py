"""Read-only job previews for JobsDB, Indeed and CTgoodjobs pastes."""

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

MAX_PASTE_CHARS = 200_000


class ImportRequest(BaseModel):
    url: str = Field(min_length=1, max_length=8000)


class PasteRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_PASTE_CHARS)


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

        # CTgoodjobs page metadata: stop the current section.
        "技能": "other",
        "更多資料": "other",
        "工種": "other",
        "工作地點": "other",
        "待遇": "other",
        "職場攻略": "other",
        "分享這份工作": "other",
        "公司概覽": "other",
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


PASTE_SALARY_LINE = re.compile(
    r"(?:HK\s*\$|HKD|\$|月薪|每月)\s*\d",
    re.I,
)


def normalize_paste(value):
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = value.replace("\u00a0", " ")

    lines = [
        " ".join(line.split())
        for line in value.splitlines()
    ]

    return [line for line in lines if line]


def find_main_job(lines):
    """Locate the opened job using Indeed, JobsDB or CTgoodjobs markers."""

    # Indeed: opened job has an apply button and full description marker.
    detail_index = None

    for index, line in enumerate(lines):
        if line.lower() in {
            "完整職位描述",
            "job description",
            "full job description",
        }:
            detail_index = index
            break

    if detail_index is not None:
        apply_index = None

        for index in range(detail_index - 1, -1, -1):
            if lines[index].startswith("立即申請"):
                apply_index = index
                break

        if apply_index is not None:
            header_start = max(0, apply_index - 15)
            body_end = len(lines)

            for index in range(detail_index + 1, len(lines)):
                if lines[index].startswith("舉報職位"):
                    body_end = index
                    break

            return {
                "site": "Indeed",
                "header": lines[header_start:apply_index],
                "body": lines[detail_index + 1:body_end],
            }

    # JobsDB: the opened job ends at its report link.
    report_index = None

    for index, line in enumerate(lines):
        if line.startswith(
            "Report this job advert"
        ) or line.startswith("Report this job"):
            report_index = index
            break

    if report_index is not None:
        body_start = None

        for index in range(report_index):
            if lines[index].lower() in {
                "key responsibilities",
                "responsibilities",
                "requirements",
                "job responsibilities",
            }:
                body_start = index
                break

        if body_start is not None:
            return {
                "site": "JobsDB",
                "header": lines[:body_start],
                "body": lines[body_start:report_index],
            }

    # CTgoodjobs: the opened job is the first job details block.
    work_index = None

    for index, line in enumerate(lines):
        if line == "工作內容":
            work_index = index
            break

    if work_index is not None:
        header_start = max(0, work_index - 12)
        body_end = len(lines)

        for index in range(work_index + 1, len(lines)):
            if lines[index] == "工作內容":
                body_end = index
                break

            if lines[index] == "職場攻略":
                body_end = index
                break

            if lines[index] == "技能":
                body_end = index
                break

        return {
            "site": "CTgoodjobs",
            "header": lines[header_start:work_index],
            "body": lines[work_index + 1:body_end],
        }

    return None


def is_employment_type(value):
    return value.strip().lower() in {
        "全職",
        "長工",
        "合約",
        "兼職",
        "實習",
        "長工, 全職",
        "全職 +1",
    }


def is_salary_line(value):
    return bool(
        PASTE_SALARY_LINE.search(value)
        or value.lower().startswith("pay:")
    )


def is_location_line(value):
    location_words = (
        "hong kong", "kowloon", "new territories",
        "香港", "九龍", "新界",
    )

    lowered = value.lower()

    return any(word in lowered for word in location_words)


def extract_paste_salary(header, body):
    for line in reversed(header):
        if is_salary_line(line):
            return line[:200]

    for line in body[:20]:
        if is_salary_line(line):
            return line[:200]

    return None


def extract_paste_location(header, body):
    for line in body[:30]:
        if line.startswith("來源於"):
            return line.replace("來源於", "", 1).strip()[:200]

    for line in reversed(header):
        if is_location_line(line) and not is_salary_line(line):
            return line[:200]

    return None


def extract_paste_title_and_company(header, location):
    company_index = None

    if location:
        for index in range(len(header) - 1, -1, -1):
            if header[index] == location:
                company_index = index - 1
                break

    if company_index is None:
        for index in range(len(header) - 1, -1, -1):
            line = header[index]

            if is_salary_line(line):
                continue

            if is_employment_type(line):
                continue

            if is_location_line(line):
                continue

            if line in {"-", "—", "·"}:
                continue

            company_index = index
            break

    if company_index is None or company_index < 1:
        return None, None

    company = header[company_index][:200]
    title = header[company_index - 1][:200]

    if not title or is_salary_line(title) or is_employment_type(title):
        title = None

    return title, company


def extract_jobsdb_paste_title_and_company(header):
    anchor_index = None

    for index, line in enumerate(header):
        if line.lower() == "employer site":
            anchor_index = index
            break

    if anchor_index is None or anchor_index + 2 >= len(header):
        return None, None

    title = header[anchor_index + 1][:200]
    company = header[anchor_index + 2][:200]

    if is_salary_line(title) or is_employment_type(title):
        title = None

    if is_salary_line(company) or is_employment_type(company):
        company = None

    return title, company


def extract_ct_paste_title_and_company(header):
    apply_index = None

    for index, line in enumerate(header):
        if line == "立即申請":
            apply_index = index
            break

    if apply_index is None or apply_index < 2:
        return None, None

    title = header[apply_index - 2][:200]
    company = header[apply_index - 1][:200]

    if is_salary_line(title) or is_employment_type(title):
        title = None

    if is_salary_line(company) or is_employment_type(company):
        company = None

    return title, company


def extract_ct_paste_salary(header, body):
    for line in header + body[:40]:
        if line.startswith("薪酬"):
            value = line.replace("薪酬", "", 1).strip()

            if value and value.lower() not in {
                "n/a",
                "na",
                "不適用",
            }:
                return value[:200]

            return None

    for line in header + body[:40]:
        if is_salary_line(line):
            return line[:200]

    return None


def extract_ct_paste_location(body):
    for index, line in enumerate(body):
        if line == "工作地點" and index + 1 < len(body):
            return body[index + 1][:200]

    return None


def build_paste_preview(text):
    lines = normalize_paste(text)
    main_job = find_main_job(lines)

    if main_job is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "未能辨識主要職位。請貼上完整職位內容，"
                "或只複製正在查看的職位後重試。"
            ),
        )

    header = main_job["header"]
    body = "\n".join(main_job["body"])

    if main_job["site"] == "CTgoodjobs":
        title, company = extract_ct_paste_title_and_company(
            header
        )
        salary = extract_ct_paste_salary(
            header,
            main_job["body"],
        )
        location = extract_ct_paste_location(
            main_job["body"]
        )
    else:
        salary = extract_paste_salary(
            header,
            main_job["body"],
        )
        location = extract_paste_location(
            header,
            main_job["body"],
        )

        if main_job["site"] == "JobsDB":
            title, company = (
                extract_jobsdb_paste_title_and_company(header)
            )
        else:
            title, company = extract_paste_title_and_company(
                header,
                location,
            )

    sections = split_sections(body)

    job = {
        "title": title,
        "company": company,
        "url": None,
        "location": location,
        "salary": salary,
        "source": "Pasted text",
        "status": "saved",
        "notes": None,
        "applied_at": None,
        "posted_at": None,
        "apply_by": None,
        "description": body[:60000] or None,
        "responsibilities": sections["responsibilities"],
        "requirements": sections["requirements"],
        "cover_letter": None,
    }

    missing_required = [
        key
        for key in ("title", "company")
        if not job[key]
    ]

    return {
        "result": "partial" if missing_required else "ready",
        "job": job,
        "source_job_id": None,
        "extraction_method": "paste_text",
        "missing_required": missing_required,
        "missing_optional": [
            key
            for key in ("location", "salary")
            if not job[key]
        ],
        "can_save": not missing_required,
        "warnings": [
            "請檢查辨識結果；如欄位留空，請自行補上。"
        ],
        "saved": False,
    }


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


@router.post("/paste")
async def preview_pasted_job(request: PasteRequest):
    return build_paste_preview(request.text)