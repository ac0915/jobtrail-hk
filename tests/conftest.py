"""Disposable PostgreSQL fixtures for integration tests.

Set TEST_DATABASE_URL to a local/administrable PostgreSQL URL to enable these
tests. Without it, integration tests skip. Never point this at production.
"""
import os
import secrets
from pathlib import Path

import pytest
from psycopg import connect
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "db" / "schema.sql"
MIGRATION_PATH = ROOT / "db" / "migrations" / "001_multi_user_expand.sql"

FORBIDDEN_HOSTS = {"render.com", "neon.tech", "aws.neon.tech", "supabase.co", "amazonaws.com"}


def _admin_url():
    url = os.environ.get("TEST_DATABASE_URL", "").strip()
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set; skipping PostgreSQL integration tests.")
    lowered = url.lower()
    if any(host in lowered for host in FORBIDDEN_HOSTS):
        raise RuntimeError("Refusing to run integration tests against a hosted production-like database.")
    if "sslmode=require" in lowered:
        raise RuntimeError("Refusing to run integration tests with sslmode=require.")
    return url


@pytest.fixture(scope="session")
def database_url():
    admin_url = _admin_url()
    dbname = f"jobtrail_test_{secrets.token_hex(8)}"
    with connect(admin_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))
    base = admin_url.rstrip("/")
    if "?" in base:
        url, query = base.split("?", 1)
        test_url = f"{url.rsplit('/', 1)[0]}/{dbname}?{query}"
    else:
        test_url = f"{base.rsplit('/', 1)[0]}/{dbname}"
    try:
        yield test_url
    finally:
        with connect(admin_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(dbname)))


@pytest.fixture()
def db(database_url):
    with connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA_PATH.read_text())
            cur.execute(MIGRATION_PATH.read_text())
        conn.commit()
        try:
            yield conn
        finally:
            conn.rollback()
