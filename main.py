"""JobTrail HK FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from psycopg import OperationalError

from app.database import close_pool, open_pool
from app.jobs import router as jobs_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        open_pool()
    except RuntimeError as exc:
        raise RuntimeError(str(exc)) from exc
    except Exception as exc:
        raise RuntimeError(
            "Could not open the database pool. Check DATABASE_URL and that "
            "PostgreSQL is running."
        ) from exc
    yield
    close_pool()


app = FastAPI(
    title="JobTrail HK API",
    description=(
        "Hong Kong-focused job application tracker API. "
        "Statuses: saved, applied, interview, offer, rejected, closed."
    ),
    version="0.2.0",
    lifespan=lifespan,
)


@app.exception_handler(OperationalError)
async def handle_db_unavailable(request: Request, exc: OperationalError):
    return JSONResponse(
        status_code=503,
        content={
            "detail": (
                "Could not reach the database. Check that PostgreSQL is "
                "running and DATABASE_URL is correct."
            )
        },
    )


app.include_router(jobs_router)


@app.get("/")
def read_root():
    return {
        "message": "JobTrail HK API is running",
        "docs": "/docs",
        "jobs": "/jobs",
    }
