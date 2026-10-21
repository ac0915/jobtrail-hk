"""Database connection pool lifecycle for JobTrail HK."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from psycopg_pool import ConnectionPool


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=BASE_DIR / ".env")

_pool: Optional[ConnectionPool] = None


def get_database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()

    if not url:
        raise RuntimeError(
            "DATABASE_URL is missing. Set your PostgreSQL "
            "connection string in .env or environment variables."
        )

    return url


def get_pool() -> ConnectionPool:
    global _pool

    if _pool is None:
        _pool = ConnectionPool(
            conninfo=get_database_url(),
            min_size=0,
            max_size=5,
            open=False,
            timeout=30,
            max_idle=60,
            check=ConnectionPool.check_connection,
            kwargs={"connect_timeout": 15},
        )

    return _pool


def open_pool() -> None:
    """Open the pool and verify connectivity at application startup."""
    pool = get_pool()

    if pool.closed:
        pool.open()

    with pool.connection(timeout=30) as conn:
        conn.execute("SELECT 1")


def close_pool() -> None:
    """Close the pool at application shutdown."""
    global _pool

    if _pool is not None and not _pool.closed:
        _pool.close()

    _pool = None