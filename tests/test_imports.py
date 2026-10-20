"""Offline regression tests for job import previews.

These tests do not make network requests or modify the database.
"""

import json

import pytest
from fastapi import HTTPException

from app.imports import (
    build_preview,
    parse_date,
    parse_pasted_listing,
    supported_target,
)


URL = "https://hk.jobsdb.com/job/95267657"


def make_html(job):
    """Wrap a job in the JobsDB server-state structure."""
    state = {
        "jobdetails": {
            "result": {
                "job": job,
            }
        }
    }

    return (
        '<html><script data-automation="server-state">'
        'window.SEEK_CONFIG = {"example": true};'
        "window.SEEK_REDUX_DATA = "
        + json.dumps(state, ensure_ascii=True)
        + "; window.OTHER_DATA = {};"
        "</script></html>"
    )


def sample_job():
    """Legacy-format fixture retained for backward compatibility."""
    return {
        "id": "95267657",
        "title": (
            "AI / Machine Learning Engineer | "
            "Financial Services | 13 Months Package"
        ),
        "advertiser": {
            "name": "ADECCO",
        },
        "location": {
            "label": "Hong Kong Island",
        },
        "salary": {
            "label": "$33,000 – $48,000 per month",
        },
        "isExpired": False,
        "listingDate": "2026-10-01T02:00:00.000Z",
        "expiryDate": "2026-11-01T16:00:00.000Z",
        "content": (
            "<h2>Responsibilities</h2>"
            "<ul><li>Build models</li></ul>"
            "<h2>Requirements</h2>"
            "<p>Python and SQL</p>"
        ),
    }


def real_format_job():
    """Fixture using the structure seen in the actual JobsDB page."""
    job = sample_job()

    job.pop("listingDate")
    job.pop("expiryDate")

    job["listedAt"] = {
        "__typename": "SeekDateTime",
        "dateTimeUtc": "2026-10-14T09:52:45.012Z",
    }

    job["expiresAt"] = {
        "__typename": "SeekDateTime",
        "dateTimeUtc": "2026-11-13T12:59:59.999Z",
    }

    job["content"] = (
        "<p><strong>Key Responsibilities</strong></p>"
        "<ul>"
        "<li><p>Build AI platforms</p></li>"
        "<li><p>Maintain integrations</p></li>"
        "</ul>"
        "<p><strong>Requirements</strong></p>"
        "<ul>"
        "<li><p>Python and SQL</p></li>"
        "<li><p>Software engineering experience</p></li>"
        "</ul>"
        "<p><strong>Nice to Have</strong></p>"
        "<ul>"
        "<li><p>Cloud experience</p></li>"
        "</ul>"
    )

    return job


def preview(job):
    return build_preview(
        make_html(job),
        URL,
        "JobsDB",
        "95267657",
    )


def test_jobsdb_required_fields_present():
    result = preview(sample_job())

    assert result["result"] == "ready"
    assert result["job"]["company"] == "ADECCO"
    assert result["job"]["location"] == "Hong Kong Island"

    assert (
        result["job"]["salary"]
        == "$33,000 – $48,000 per month"
    )

    assert (
        result["extraction_method"]
        == "jobsdb_server_state"
    )

    assert result["missing_required"] == []
    assert result["can_save"] is True
    assert result["saved"] is False


def test_missing_optional_fields_do_not_block_save():
    job = sample_job()
    job.pop("salary")
    job.pop("location")

    result = preview(job)

    assert result["can_save"] is True
    assert result["missing_required"] == []

    assert set(result["missing_optional"]) == {
        "location",
        "salary",
    }


def test_missing_company_requires_input():
    job = sample_job()
    job.pop("advertiser")

    result = preview(job)

    assert result["result"] == "partial"
    assert result["can_save"] is False
    assert result["missing_required"] == ["company"]


def test_wrong_job_id_is_rejected():
    job = sample_job()
    job["id"] = "11111111"

    with pytest.raises(HTTPException) as error:
        preview(job)

    assert error.value.status_code == 502


def test_website_schema_is_not_a_job():
    html = """
    <script type=\"application/ld+json\">
    {
        \"@context\": \"https://schema.org\",
        \"@type\": \"WebSite\",
        \"url\": \"https://hk.jobsdb.com\"
    }
    </script>
    """

    with pytest.raises(HTTPException) as error:
        build_preview(
            html,
            URL,
            "JobsDB",
            "95267657",
        )

    assert error.value.status_code == 502


def test_listing_details_are_kept():
    result = preview(sample_job())
    job = result["job"]

    assert job["posted_at"] == "2026-10-01"

    # UTC 2026-11-01 16:00 becomes
    # Hong Kong 2026-11-02 00:00.
    assert job["apply_by"] == "2026-11-02"

    assert "Build models" in job["responsibilities"]
    assert "Python and SQL" in job["requirements"]


def test_dates_use_hong_kong_calendar_day():
    assert parse_date(
        "2026-11-01T16:00:00.000Z"
    ) == "2026-11-02"


def test_date_only_value_is_not_shifted():
    assert parse_date(
        "2026-11-01"
    ) == "2026-11-01"


def test_invalid_date_is_rejected():
    assert parse_date("2026-99-99Tbroken") is None


def test_real_nested_dates_are_read():
    result = preview(real_format_job())
    job = result["job"]

    assert job["posted_at"] == "2026-10-14"
    assert job["apply_by"] == "2026-11-13"


def test_real_paragraph_headings_are_split():
    result = preview(real_format_job())
    job = result["job"]

    assert "Build AI platforms" in job["responsibilities"]
    assert "Maintain integrations" in job["responsibilities"]

    assert "Python and SQL" in job["requirements"]
    assert (
        "Software engineering experience"
        in job["requirements"]
    )

    # Requirements must not be included in responsibilities.
    assert "Python and SQL" not in job["responsibilities"]

    # Nice-to-have content belongs in the full description,
    # not in the required qualifications section.
    assert "Cloud experience" not in job["requirements"]
    assert "Cloud experience" in job["description"]


def test_unstructured_description_is_not_mislabelled():
    job = real_format_job()

    job["content"] = (
        "<p>An unstructured job description.</p>"
    )

    result = preview(job)
    imported = result["job"]

    assert imported["description"] == (
        "An unstructured job description."
    )

    assert imported["responsibilities"] is None
    assert imported["requirements"] is None


def test_content2_is_supported():
    job = real_format_job()
    job["content2"] = job.pop("content")

    result = preview(job)
    imported = result["job"]

    assert "Build AI platforms" in imported["responsibilities"]
    assert "Python and SQL" in imported["requirements"]
    assert "Cloud experience" in imported["description"]


def test_indeed_link_is_rejected_use_paste():
    """Indeed cannot be scraped; link mode must refuse and point to paste."""
    with pytest.raises(HTTPException) as error:
        supported_target(
            "https://hk.indeed.com/viewjob?jk=2cd42ed09b6c530b"
        )

    assert error.value.status_code == 422
    assert "Paste" in error.value.detail


def test_paste_target_job_only():
    """Single job paste without page chrome."""
    text = """
Python Developer
Acme Labs
Hong Kong Island
$40,000 – $55,000 per month

Full Job Description
We build data products for finance teams.

Responsibilities
- Design APIs
- Review pull requests

Requirements
- 3 years Python
- SQL experience
"""

    result = parse_pasted_listing(text)
    job = result["job"]

    assert result["extraction_method"] == "paste_text"
    assert result["can_save"] is True
    assert job["title"] == "Python Developer"
    assert job["company"] == "Acme Labs"
    assert job["location"] == "Hong Kong Island"
    assert "40,000" in (job["salary"] or "")
    assert "Design APIs" in (job["responsibilities"] or "")
    assert "3 years Python" in (job["requirements"] or "")
    assert job["source"] == "Paste"
    assert job["url"] is None


def test_paste_whole_page_keeps_one_complete_job():
    """Whole-page paste: cut recommendations, keep main job only."""
    text = """
Sign in
Create account
Skip to main content

Senior Backend Engineer
Horizon Fintech
Central, Hong Kong
HKD 50,000 – 70,000 per month

Job Description
Own the payment platform and lead a small team.

Key Responsibilities
- Build payment APIs
- Mentor junior engineers

Requirements
- 5+ years backend experience
- Strong Python or Go

Similar jobs
Junior Frontend Developer
Other Co
$20,000 per month

People also searched
Data Analyst
"""

    result = parse_pasted_listing(text)
    job = result["job"]

    assert result["can_save"] is True
    assert job["title"] == "Senior Backend Engineer"
    assert job["company"] == "Horizon Fintech"
    assert "Build payment APIs" in (job["responsibilities"] or "")
    assert "5+ years" in (job["requirements"] or "")

    # Must not leak recommendation listings.
    assert "Junior Frontend" not in (job["description"] or "")
    assert "Other Co" not in (job["description"] or "")
    assert "Data Analyst" not in (job["description"] or "")
    assert "Junior Frontend" not in (job["title"] or "")
