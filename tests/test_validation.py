"""Unit tests for validation helpers (no database required)."""

import pytest

from app.validation import (
    ALLOWED_STATUSES,
    normalize_status,
    normalize_url,
    optional_text,
    require_non_empty,
)


def test_require_non_empty_rejects_blank():
    with pytest.raises(ValueError, match="Job title"):
        require_non_empty("   ", "Job title")
    with pytest.raises(ValueError, match="Company"):
        require_non_empty(None, "Company")


def test_require_non_empty_trims():
    assert require_non_empty("  Junior Developer  ", "Job title") == "Junior Developer"


def test_status_must_be_allowed():
    assert normalize_status("Applied") == "applied"
    assert normalize_status("SAVED") == "saved"
    with pytest.raises(ValueError, match="Status must be one of"):
        normalize_status("wishlist")
    with pytest.raises(ValueError, match="Status must be one of"):
        normalize_status("in-progress")


def test_allowed_statuses_cover_workflow():
    assert set(ALLOWED_STATUSES) == {
        "saved",
        "applied",
        "interview",
        "offer",
        "rejected",
        "closed",
    }


def test_normalize_url_strips_tracking_and_trailing_slash():
    result = normalize_url(
        "https://HK.JobsDB.com/job/100/?utm_source=share&utm_medium=email#apply"
    )
    assert result == "https://hk.jobsdb.com/job/100"


def test_normalize_url_blank_is_none():
    assert normalize_url(None) is None
    assert normalize_url("  ") is None


def test_normalize_url_adds_https():
    assert normalize_url("example.com/jobs/1") == "https://example.com/jobs/1"


def test_normalize_url_rejects_bad_scheme():
    with pytest.raises(ValueError):
        normalize_url("ftp://example.com/job")


def test_optional_text():
    assert optional_text("  notes  ") == "notes"
    assert optional_text("   ") is None
    assert optional_text(None) is None
