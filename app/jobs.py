from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.database import pool

router = APIRouter(prefix="/jobs", tags=["Jobs"])


class JobCreate(BaseModel):
    title: str
    company: str
    url: Optional[str] = None
    location: Optional[str] = None
    salary: Optional[str] = None
    source: Optional[str] = None
    notes: Optional[str] = None


class JobUpdate(BaseModel):
    title: Optional[str] = None
    company: Optional[str] = None
    url: Optional[str] = None
    location: Optional[str] = None
    salary: Optional[str] = None
    status: Optional[str] = None
    source: Optional[str] = None
    notes: Optional[str] = None


@router.get("")
def list_jobs():
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, title, company, url, location, salary,
                       status, source, notes, created_at, updated_at
                FROM jobs
                ORDER BY created_at DESC
                """
            )
            rows = cur.fetchall()

    return [
        {
            "id": row[0],
            "title": row[1],
            "company": row[2],
            "url": row[3],
            "location": row[4],
            "salary": row[5],
            "status": row[6],
            "source": row[7],
            "notes": row[8],
            "created_at": row[9],
            "updated_at": row[10],
        }
        for row in rows
    ]


@router.post("")
def create_job(job: JobCreate):
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO jobs
                    (title, company, url, location, salary, source, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id, created_at, updated_at
                """,
                (
                    job.title,
                    job.company,
                    job.url,
                    job.location,
                    job.salary,
                    job.source,
                    job.notes,
                ),
            )
            row = cur.fetchone()

    return {
        "message": "Job saved successfully",
        "id": row[0],
        "created_at": row[1],
        "updated_at": row[2],
    }


@router.patch("/{job_id}")
def update_job(job_id: int, job: JobUpdate):
    fields = job.model_dump(exclude_unset=True)

    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    fields["updated_at"] = datetime.now()

    set_clause = ", ".join(f"{key} = %s" for key in fields)
    values = list(fields.values())
    values.append(job_id)

    with pool.connection() as conn:
        with conn.cursor() as cur:
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

    if not row:
        raise HTTPException(status_code=404, detail="Job not found")

    return {"message": "Job updated successfully", "id": row[0]}


@router.delete("/{job_id}")
def delete_job(job_id: int):
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM jobs WHERE id = %s RETURNING id",
                (job_id,),
            )
            row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Job not found")

    return {"message": "Job deleted successfully", "id": row[0]}