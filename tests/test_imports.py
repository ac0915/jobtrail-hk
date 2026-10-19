"""Offline regression tests for job import previews.

These tests do not make network requests or modify the database.
"""

import json

import pytest
from fastapi import HTTPException

from app.imports import build_preview, parse_date, supported_target


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
    <script type="application/ld+json">
    {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "url": "https://hk.jobsdb.com"
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


def test_indeed_homepage_vjk_becomes_viewjob():
    url, source, job_id = supported_target(
        "https://hk.indeed.com/?hl=zh&vjk=2cd42ed09b6c530b"
    )

    assert source == "Indeed"
    assert job_id == "2cd42ed09b6c530b"
    assert url == (
        "https://hk.indeed.com/viewjob?jk=2cd42ed09b6c530b"
    )


def test_indeed_search_vjk_becomes_viewjob():
    url, source, job_id = supported_target(
        "https://hk.indeed.com/jobs?q=python&l=Hong+Kong"
        "&vjk=2cd42ed09b6c530b"
    )

    assert source == "Indeed"
    assert job_id == "2cd42ed09b6c530b"
    assert url == (
        "https://hk.indeed.com/viewjob?jk=2cd42ed09b6c530b"
    )


def test_indeed_viewjob_extra_params_are_canonical():
    url, source, job_id = supported_target(
        "https://www.indeed.com/viewjob?jk=abc_12-Z&from=serp"
    )

    assert source == "Indeed"
    assert job_id == "abc_12-Z"
    assert url == "https://www.indeed.com/viewjob?jk=abc_12-Z"


def test_indeed_page_without_job_id_is_rejected():
    with pytest.raises(HTTPException) as error:
        supported_target("https://hk.indeed.com/?hl=zh")

    assert error.value.status_code == 422


def test_conflicting_indeed_ids_are_rejected():
    with pytest.raises(HTTPException) as error:
        supported_target(
            "https://hk.indeed.com/viewjob?jk=aaaa&vjk=bbbb"
        )

    assert error.value.status_code == 422
