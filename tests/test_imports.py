"""Offline tests for job preview parsing."""

import json

import pytest
from fastapi import HTTPException

from app.imports import build_preview


URL = "https://hk.jobsdb.com/job/95267657"


def make_html(job):
    state = {
        "jobdetails": {
            "result": {
                "job": job,
            }
        }
    }

    # Include a different assignment before and after the JSON.
    return (
        '<html><script data-automation="server-state">'
        'window.SEEK_CONFIG = {"example": true};'
        "window.SEEK_REDUX_DATA = "
        + json.dumps(state, ensure_ascii=True)
        + "; window.OTHER_DATA = {};"
        "</script></html>"
    )


def sample_job():
    return {
        "id": "95267657",
        "title": (
            "AI / Machine Learning Engineer | "
            "Financial Services | 13 Months Package"
        ),
        "advertiser": {"name": "ADECCO"},
        "location": {"label": "Hong Kong Island"},
        "salary": {"label": "$33,000 – $48,000 per month"},
        "isExpired": False,
        "listingDate": "2026-10-01T02:00:00.000Z",
        "expiryDate": "2026-11-01T16:00:00.000Z",
        "content": "<h2>Responsibilities</h2><ul><li>Build models</li></ul><h2>Requirements</h2><p>Python and SQL</p>",
    }


def test_jobsdb_required_fields_present():
    result = build_preview(
        make_html(sample_job()),
        URL,
        "JobsDB",
        "95267657",
    )

    assert result["result"] == "ready"
    assert result["job"]["company"] == "ADECCO"
    assert result["job"]["location"] == "Hong Kong Island"
    assert result["job"]["salary"] == "$33,000 – $48,000 per month"
    assert result["extraction_method"] == "jobsdb_server_state"
    assert result["missing_required"] == []
    assert result["saved"] is False


def test_missing_optional_fields_do_not_block_save():
    job = sample_job()
    job.pop("salary")
    job.pop("location")

    result = build_preview(
        make_html(job),
        URL,
        "JobsDB",
        "95267657",
    )

    assert result["can_save"] is True
    assert result["missing_required"] == []
    assert set(result["missing_optional"]) == {"location", "salary"}


def test_missing_company_requires_input():
    job = sample_job()
    job.pop("advertiser")

    result = build_preview(
        make_html(job),
        URL,
        "JobsDB",
        "95267657",
    )

    assert result["result"] == "partial"
    assert result["can_save"] is False
    assert result["missing_required"] == ["company"]


def test_wrong_job_id_is_rejected():
    job = sample_job()
    job["id"] = "11111111"

    with pytest.raises(HTTPException) as error:
        build_preview(
            make_html(job),
            URL,
            "JobsDB",
            "95267657",
        )

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
        build_preview(html, URL, "JobsDB", "95267657")

    assert error.value.status_code == 502

def test_listing_details_are_kept():
    result = build_preview(
        make_html(sample_job()),
        URL,
        "JobsDB",
        "95267657",
    )
    job = result["job"]
    assert job["posted_at"] == "2026-10-01"
    assert job["apply_by"] == "2026-11-01"
    assert "Build models" in job["responsibilities"]
    assert "Python and SQL" in job["requirements"]
