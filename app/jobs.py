"""Job CRUD with editable application dates, cover letters, and flagged ownership."""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg import OperationalError
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row
from pydantic import BaseModel, field_validator

from app.auth_routes import AuthUser, _require_csrf, current_user
from app.cover_letters import router as cover_letters_router
from app.database import get_pool
from app.validation import (
    ALLOWED_STATUSES,
    normalize_status,
    normalize_url,
    optional_text,
    require_non_empty,
)


router = APIRouter(prefix="/jobs", tags=["Jobs"])

HKT = timezone(timedelta(hours=8))

MULTI_USER_ENABLED = os.getenv("MULTI_USER_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}

APPLIED_STATUSES = {
    "applied",
    "interview",
    "offer",
    "rejected",
}

JOB_FIELDS = (
    "title",
    "company",
    "url",
    "location",
    "salary",
    "status",
    "source",
    "notes",
    "applied_at",
    "posted_at",
    "apply_by",
    "responsibilities",
    "requirements",
    "description",
    "cover_letter",
)

JOB_COLUMNS = ", ".join(
    ("id",) + JOB_FIELDS + ("user_id", "created_at", "updated_at")
)


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
    posted_at: Optional[date] = None
    apply_by: Optional[date] = None

    responsibilities: Optional[str] = None
    requirements: Optional[str] = None
    description: Optional[str] = None
    cover_letter: Optional[str] = None

    @field_validator("title", "company")
    @classmethod
    def non_empty_text(cls, value):
        if value is None:
            return None

        return require_non_empty(value, "Title/company")

    @field_validator("url")
    @classmethod
    def normalized_url(cls, value):
        return normalize_url(value)

    @field_validator("status")
    @classmethod
    def allowed_status(cls, value):
        if value is None:
            return None

        result = normalize_status(value)

        if result is None:
            raise ValueError("Status cannot be empty.")

        return result

    @field_validator("location", "salary", "source")
    @classmethod
    def short_text(cls, value):
        return optional_text(value, max_len=200)

    @field_validator("notes")
    @classmethod
    def notes_text(cls, value):
        return optional_text(value, max_len=8000)

    @field_validator("responsibilities", "requirements")
    @classmethod
    def section_text(cls, value):
        return optional_text(value, max_len=20000)

    @field_validator("description", "cover_letter")
    @classmethod
    def long_text(cls, value):
        return optional_text(value, max_len=60000)


class JobCreate(JobUpdate):
    title: str
    company: str
    status: str = "saved"


def today_hk():
    return datetime.now(HKT).date()


def request_user(request: Request) -> Optional[AuthUser]:
    """Return the signed-in user only when multi-user mode is enabled."""
    if not MULTI_USER_ENABLED:
        return None
    return current_user(request)


def require_job_csrf(request: Request) -> None:
    """Protect state-changing job requests in multi-user mode."""
    if MULTI_USER_ENABLED:
        _require_csrf(request)


def prepare_application_update(
    fields,
    existing_applied_at,
    today,
):
    result = dict(fields)

    if (
        result.get("status") in APPLIED_STATUSES
        and "applied_at" not in result
        and existing_applied_at is None
    ):
        result["applied_at"] = today

    return result


def database_unavailable():
    return HTTPException(
        status_code=503,
        detail=(
            "Could not reach the database. "
            "Check PostgreSQL and DATABASE_URL."
        ),
    )


def check_duplicate(cur, url, exclude_id=None, user_id=None):
    if not url:
        return

    sql = """
        SELECT id, title, company
        FROM public.jobs
        WHERE url = %s
    """

    values = [url]

    if user_id is not None:
        sql += " AND user_id = %s"
        values.append(user_id)

    if exclude_id is not None:
        sql += " AND id <> %s"
        values.append(exclude_id)

    cur.execute(sql + " LIMIT 1", values)
    existing = cur.fetchone()

    if existing:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "duplicate_url",
                "message": (
                    "You already saved this listing: "
                    f"{existing['title']} at {existing['company']}."
                ),
                "existing_id": existing["id"],
            },
        )


@router.get("")
def list_jobs(user: Optional[AuthUser] = Depends(request_user)):
    try:
        with get_pool().connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                sql = f"""
                    SELECT {JOB_COLUMNS}
                    FROM public.jobs
                """
                values = []
                if user is not None:
                    sql += " WHERE user_id = %s"
                    values.append(user.id)
                sql += " ORDER BY created_at DESC"
                cur.execute(sql, values)

                return cur.fetchall()

    except OperationalError as exc:
        raise database_unavailable() from exc


@router.get("/meta/statuses")
def list_statuses():
    return {"statuses": list(ALLOWED_STATUSES)}


@router.get("/{job_id}")
def get_job(job_id: int, user: Optional[AuthUser] = Depends(request_user)):
    try:
        with get_pool().connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                sql = f"""
                    SELECT {JOB_COLUMNS}
                    FROM public.jobs
                    WHERE id = %s
                """
                values = [job_id]
                if user is not None:
                    sql += " AND user_id = %s"
                    values.append(user.id)
                cur.execute(sql, values)

                row = cur.fetchone()

    except OperationalError as exc:
        raise database_unavailable() from exc

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="That job is no longer in your list.",
        )

    return row


@router.post("")
def create_job(job: JobCreate, request: Request, user: Optional[AuthUser] = Depends(request_user)):
    require_job_csrf(request)
    data = job.model_dump()

    for key in ("title", "company", "status"):
        if data.get(key) is None:
            raise HTTPException(
                status_code=422,
                detail=f"{key} is required.",
            )

    if data["applied_at"] is None:
        data["applied_at"] = today_hk()

    columns = list(JOB_FIELDS)
    values = [data[key] for key in JOB_FIELDS]

    if user is not None:
        columns.append("user_id")
        values.append(user.id)

    try:
        with get_pool().connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                check_duplicate(
                    cur,
                    data.get("url"),
                    user_id=user.id if user else None,
                )

                try:
                    with conn.transaction():
                        placeholders = ", ".join(
                            ["%s"] * len(columns)
                        )

                        cur.execute(
                            f"""
                            INSERT INTO public.jobs
                                ({", ".join(columns)})
                            VALUES ({placeholders})
                            RETURNING
                                id,
                                created_at,
                                updated_at,
                                status,
                                applied_at
                            """,
                            values,
                        )

                        row = cur.fetchone()

                except UniqueViolation:
                    check_duplicate(
                        cur,
                        data.get("url"),
                        user_id=user.id if user else None,
                    )

                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "A record conflicts with an existing job."
                        ),
                    ) from None

    except OperationalError as exc:
        raise database_unavailable() from exc

    return {
        "message": "Job saved successfully",
        **row,
    }


@router.patch("/{job_id}")
def update_job(job_id: int, job: JobUpdate, request: Request, user: Optional[AuthUser] = Depends(request_user)):
    require_job_csrf(request)
    fields = job.model_dump(exclude_unset=True)

    if not fields:
        raise HTTPException(
            status_code=400,
            detail="No fields to update.",
        )

    for key in ("title", "company", "status"):
        if key in fields and fields[key] is None:
            raise HTTPException(
                status_code=422,
                detail=f"{key} cannot be cleared.",
            )

    try:
        with get_pool().connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                select_sql = """
                    SELECT id, applied_at
                    FROM public.jobs
                    WHERE id = %s
                """
                select_values = [job_id]
                if user is not None:
                    select_sql += " AND user_id = %s"
                    select_values.append(user.id)
                select_sql += " FOR UPDATE"

                cur.execute(select_sql, select_values)
                old = cur.fetchone()

                if old is None:
                    raise HTTPException(
                        status_code=404,
                        detail="That job is no longer in your list.",
                    )

                fields = prepare_application_update(
                    fields,
                    existing_applied_at=old["applied_at"],
                    today=today_hk(),
                )

                check_duplicate(
                    cur,
                    fields.get("url"),
                    exclude_id=job_id,
                    user_id=user.id if user else None,
                )

                fields["updated_at"] = datetime.now(
                    timezone.utc
                )

                set_clause = ", ".join(
                    f"{key} = %s"
                    for key in fields
                )

                update_sql = f"""
                    UPDATE public.jobs
                    SET {set_clause}
                    WHERE id = %s
                """
                update_values = list(fields.values()) + [job_id]
                if user is not None:
                    update_sql += " AND user_id = %s"
                    update_values.append(user.id)
                update_sql += " RETURNING id"

                try:
                    with conn.transaction():
                        cur.execute(update_sql, update_values)
                        row = cur.fetchone()

                except UniqueViolation:
                    check_duplicate(
                        cur,
                        fields.get("url"),
                        exclude_id=job_id,
                        user_id=user.id if user else None,
                    )

                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "A record conflicts with an existing job."
                        ),
                    ) from None

    except OperationalError as exc:
        raise database_unavailable() from exc

    return {
        "message": "Job updated successfully",
        **row,
    }


@router.delete("/{job_id}")
def delete_job(job_id: int, request: Request, user: Optional[AuthUser] = Depends(request_user)):
    require_job_csrf(request)
    try:
        with get_pool().connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                sql = """
                    DELETE FROM public.jobs
                    WHERE id = %s
                """
                values = [job_id]
                if user is not None:
                    sql += " AND user_id = %s"
                    values.append(user.id)
                sql += " RETURNING id"

                cur.execute(sql, values)
                row = cur.fetchone()

    except OperationalError as exc:
        raise database_unavailable() from exc

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="That job is no longer in your list.",
        )

    return {
        "message": "Job deleted successfully",
        **row,
    }


# Final URL: POST /jobs/cover-letter/extract
router.include_router(cover_letters_router)
