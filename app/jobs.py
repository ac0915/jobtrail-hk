"""Job CRUD endpoints with validation and duplicate detection."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from psycopg import OperationalError
from psycopg.errors import UniqueViolation
from pydantic import BaseModel, field_validator

from app.database import get_pool
from app.validation import (
    ALLOWED_STATUSES,
    normalize_status,
    normalize_url,
    optional_text,
    require_non_empty,
)

router = APIRouter(prefix="/jobs", tags=["Jobs"])

JOB_COLUMNS = (
    "id, title, company, url, location, salary, status, source, notes, "
    "applied_at, created_at, updated_at"
)


class JobCreate(BaseModel):
    title: str
    company: str
    url: Optional[str] = None
    location: Optional[str] = None
    salary: Optional[str] = None
    source: Optional[str] = None
    notes: Optional[str] = None
    status: str = "saved"
    applied_at: Optional[date] = None

    @field_validator("title")
    @classmethod
    def title_required(cls, value: str) -> str:
        return require_non_empty(value, "Job title")

    @field_validator("company")
    @classmethod
    def company_required(cls, value: str) -> str:
        return require_non_empty(value, "Company")

    @field_validator("url")
    @classmethod
    def url_normalized(cls, value: Optional[str]) -> Optional[str]:
        return normalize_url(value)

    @field_validator("status")
    @classmethod
    def status_allowed(cls, value: str) -> str:
        result = normalize_status(value)
        if result is None:
            raise ValueError("Status is required.")
        return result

    @field_validator("location", "salary", "source")
    @classmethod
    def short_optional(cls, value: Optional[str]) -> Optional[str]:
        return optional_text(value, max_len=200)

    @field_validator("notes")
    @classmethod
    def notes_optional(cls, value: Optional[str]) -> Optional[str]:
        return optional_text(value, max_len=8000)


class JobUpdate(BaseModel):
    title: Optional[str] = None
    company: Optional[str] = None
    url: Optional[str] = None
    location: Optional[str] = None
    salary: Optional[str] = None
    status: Optional[str] = None
    source: Optional[str] = None
    notes: Optional[str] = None
    applied_at: Optional[date] = None

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return require_non_empty(value, "Job title")

    @field_validator("company")
    @classmethod
    def company_not_blank(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return require_non_empty(value, "Company")

    @field_validator("url")
    @classmethod
    def url_normalized(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not value.strip():
            return None
        return normalize_url(value)

    @field_validator("status")
    @classmethod
    def status_allowed(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        result = normalize_status(value)
        if result is None:
            raise ValueError("Status cannot be empty.")
        return result

    @field_validator("location", "salary", "source")
    @classmethod
    def short_optional(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return optional_text(value, max_len=200)

    @field_validator("notes")
    @classmethod
    def notes_optional(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return optional_text(value, max_len=8000)


def _row_to_job(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": row[0],
        "title": row[1],
        "company": row[2],
        "url": row[3],
        "location": row[4],
        "salary": row[5],
        "status": row[6],
        "source": row[7],
        "notes": row[8],
        "applied_at": row[9],
        "created_at": row[10],
        "updated_at": row[11],
    }


def _db_unavailable() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail=(
            "Could not reach the database. Check that PostgreSQL is running "
            "and DATABASE_URL is correct."
        ),
    )


def _find_by_url(
    cur,
    url: Optional[str],
    exclude_id: Optional[int] = None,
):
    if not url:
        return None

    if exclude_id is None:
        cur.execute(
            "SELECT id, title, company FROM jobs WHERE url = %s LIMIT 1",
            (url,),
        )
    else:
        cur.execute(
            """
            SELECT id, title, company
            FROM jobs
            WHERE url = %s AND id <> %s
            LIMIT 1
            """,
            (url, exclude_id),
        )

    return cur.fetchone()


def _duplicate_response(existing: tuple[Any, ...]) -> HTTPException:
    existing_id, title, company = existing

    return HTTPException(
        status_code=409,
        detail={
            "code": "duplicate_url",
            "message": (
                f"You already saved this listing: {title} at {company}."
            ),
            "existing_id": existing_id,
        },
    )


def _generic_duplicate_response() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "duplicate_url",
            "message": "You already saved a job with this URL.",
        },
    )


@router.get("")
def list_jobs():
    try:
        with get_pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT {JOB_COLUMNS}
                    FROM jobs
                    ORDER BY created_at DESC
                    """
                )
                rows = cur.fetchall()
    except OperationalError as exc:
        raise _db_unavailable() from exc

    return [_row_to_job(row) for row in rows]


@router.get("/meta/statuses")
def list_statuses():
    return {"statuses": list(ALLOWED_STATUSES)}


@router.get("/{job_id}")
def get_job(job_id: int):
    try:
        with get_pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT {JOB_COLUMNS} FROM jobs WHERE id = %s",
                    (job_id,),
                )
                row = cur.fetchone()
    except OperationalError as exc:
        raise _db_unavailable() from exc

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="That job is no longer in your list.",
        )

    return _row_to_job(row)


@router.post("")
def create_job(job: JobCreate):
    status = job.status
    applied_at = job.applied_at

    if (
        status in ("applied", "interview", "offer", "rejected")
        and applied_at is None
    ):
        applied_at = date.today()

    try:
        with get_pool().connection() as conn:
            with conn.cursor() as cur:
                existing = _find_by_url(cur, job.url)

                if existing:
                    raise _duplicate_response(existing)

                try:
                    with conn.transaction():
                        cur.execute(
                            """
                            INSERT INTO jobs
                                (
                                    title, company, url, location, salary,
                                    source, notes, status, applied_at
                                )
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                            RETURNING
                                id, created_at, updated_at, status, applied_at
                            """,
                            (
                                job.title,
                                job.company,
                                job.url,
                                job.location,
                                job.salary,
                                job.source,
                                job.notes,
                                status,
                                applied_at,
                            ),
                        )
                        row = cur.fetchone()

                except UniqueViolation:
                    existing = _find_by_url(cur, job.url)

                    if existing:
                        raise _duplicate_response(existing) from None

                    raise _generic_duplicate_response() from None

    except OperationalError as exc:
        raise _db_unavailable() from exc

    return {
        "message": "Job saved successfully",
        "id": row[0],
        "created_at": row[1],
        "updated_at": row[2],
        "status": row[3],
        "applied_at": row[4],
    }


@router.patch("/{job_id}")
def update_job(job_id: int, job: JobUpdate):
    fields = job.model_dump(exclude_unset=True)

    if not fields:
        raise HTTPException(
            status_code=400,
            detail="No fields to update.",
        )

    if "title" in fields and fields["title"] is None:
        raise HTTPException(
            status_code=422,
            detail="Job title cannot be cleared.",
        )

    if "company" in fields and fields["company"] is None:
        raise HTTPException(
            status_code=422,
            detail="Company cannot be cleared.",
        )

    if "status" in fields and fields["status"] is None:
        raise HTTPException(
            status_code=422,
            detail="Status cannot be cleared.",
        )

    allowed_keys = {
        "title",
        "company",
        "url",
        "location",
        "salary",
        "status",
        "source",
        "notes",
        "applied_at",
    }

    unknown = set(fields) - allowed_keys

    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown fields: {', '.join(sorted(unknown))}",
        )

    fields["updated_at"] = datetime.now()

    if (
        "status" in fields
        and fields["status"] in ("applied", "interview", "offer", "rejected")
        and "applied_at" not in fields
    ):
        fields["applied_at"] = date.today()

    set_clause = ", ".join(f"{key} = %s" for key in fields)
    values = list(fields.values())
    values.append(job_id)

    try:
        with get_pool().connection() as conn:
            with conn.cursor() as cur:
                if "url" in fields and fields["url"]:
                    existing = _find_by_url(
                        cur,
                        fields["url"],
                        exclude_id=job_id,
                    )

                    if existing:
                        raise _duplicate_response(existing)

                try:
                    with conn.transaction():
                        cur.execute(
                            f"""
                            UPDATE jobs
                            SET {set_clause}
                            WHERE id = %s
                            RETURNING id
                            """,
                            values,
                        )
                        row = cur.fetchone()

                except UniqueViolation:
                    existing = _find_by_url(
                        cur,
                        fields.get("url"),
                        exclude_id=job_id,
                    )

                    if existing:
                        raise _duplicate_response(existing) from None

                    raise _generic_duplicate_response() from None

    except OperationalError as exc:
        raise _db_unavailable() from exc

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="That job is no longer in your list.",
        )

    return {
        "message": "Job updated successfully",
        "id": row[0],
    }


@router.delete("/{job_id}")
def delete_job(job_id: int):
    try:
        with get_pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM jobs WHERE id = %s RETURNING id",
                    (job_id,),
                )
                row = cur.fetchone()
    except OperationalError as exc:
        raise _db_unavailable() from exc

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="That job is no longer in your list.",
        )

    return {
        "message": "Job deleted successfully",
        "id": row[0],
    }