"""Database connection pool lifecycle for JobTrail HK."""

from __future__ import annotations

import os
from typing import Optional

from dotenv import load_dotenv
from psycopg_pool import ConnectionPool

load_dotenv()

_pool: Optional[ConnectionPool] = None


def get_database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError(
            "DATABASE_URL is missing. Copy .env.example to .env and set your "
            "PostgreSQL connection string."
        )
    return url


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=get_database_url(),
            min_size=1,
            max_size=5,
            open=False,
            timeout=10,
            kwargs={"connect_timeout": 5},
        )
    return _pool


def open_pool() -> None:
    """Open the pool at application startup."""
    pool = get_pool()
    if pool.closed:
        pool.open()
    pool.wait(timeout=10)


def close_pool() -> None:
    """Close the pool at application shutdown."""
    global _pool
    if _pool is not None and not _pool.closed:
        _pool.close()
    _pool = None
