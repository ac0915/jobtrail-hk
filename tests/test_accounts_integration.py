"""Integration tests requiring a disposable PostgreSQL database.

Run locally with, for example:
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres pytest tests/test_accounts_integration.py
"""
import pytest
from psycopg import errors

from app.accounts import (
    authenticate_user,
    create_session,
    create_user,
    delete_expired_sessions,
    resolve_session,
    revoke_session,
)
from app.auth_security import hash_password, session_token_hash


pytestmark = pytest.mark.integration


def test_register_login_and_session_round_trip(db):
    user = create_user(db, "Friend@example.com", "password123", reserved_email="owner@example.com")
    db.commit()
    assert user["email"] == "friend@example.com"

    authenticated = authenticate_user(db, " FRIEND@EXAMPLE.COM ", "password123")
    db.commit()
    assert authenticated["id"] == user["id"]

    token = create_session(db, user["id"])
    db.commit()
    assert resolve_session(db, token)["id"] == user["id"]
    db.commit()


def test_duplicate_email_is_rejected_by_database(db):
    create_user(db, "friend@example.com", "password123", reserved_email="owner@example.com")
    db.commit()
    with pytest.raises(errors.UniqueViolation):
        create_user(db, "Friend@example.com", "password123", reserved_email="owner@example.com")
    db.rollback()


def test_wrong_password_and_disabled_account_fail(db):
    user = create_user(db, "friend@example.com", "password123", reserved_email="owner@example.com")
    db.commit()
    assert authenticate_user(db, "friend@example.com", "incorrect123") is None
    db.commit()

    with db.cursor() as cur:
        cur.execute("UPDATE public.jt_users SET is_active = FALSE WHERE id = %s", (user["id"],))
    db.commit()
    assert authenticate_user(db, "friend@example.com", "password123") is None
    db.commit()


def test_expired_session_cannot_resolve(db):
    user = create_user(db, "friend@example.com", "password123", reserved_email="owner@example.com")
    db.commit()
    token = create_session(db, user["id"])
    db.commit()
    with db.cursor() as cur:
        cur.execute("UPDATE public.jt_sessions SET expires_at = NOW() - INTERVAL '1 minute' WHERE token_hash = %s", (session_token_hash(token),))
    db.commit()
    assert resolve_session(db, token) is None
    db.commit()


def test_logout_and_expiry_cleanup(db):
    user = create_user(db, "friend@example.com", "password123", reserved_email="owner@example.com")
    db.commit()
    active = create_session(db, user["id"])
    expired = create_session(db, user["id"])
    db.commit()
    with db.cursor() as cur:
        cur.execute("UPDATE public.jt_sessions SET expires_at = NOW() - INTERVAL '1 minute' WHERE token_hash = %s", (session_token_hash(expired),))
    db.commit()

    revoke_session(db, active)
    db.commit()
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM public.jt_sessions WHERE token_hash = %s", (session_token_hash(active),))
        assert cur.fetchone()[0] == 0

    delete_expired_sessions(db)
    db.commit()
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM public.jt_sessions")
        assert cur.fetchone()[0] == 0


def test_owner_address_is_reserved(db):
    with pytest.raises(ValueError):
        create_user(db, "owner@example.com", "password123", reserved_email="owner@example.com")
    db.rollback()


def test_jobs_user_id_foreign_key(db):
    user = create_user(db, "friend@example.com", "password123", reserved_email="owner@example.com")
    db.commit()
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO public.jobs (title, company, user_id) VALUES (%s, %s, %s) RETURNING id",
            ("Backend Engineer", "Example Ltd", user["id"]),
        )
        job_id = cur.fetchone()[0]
    db.commit()
    with db.cursor() as cur:
        cur.execute("SELECT user_id FROM public.jobs WHERE id = %s", (job_id,))
        assert cur.fetchone()[0] == user["id"]


def test_invalid_hash_format_is_rejected(db):
    with pytest.raises(errors.CheckViolation):
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO public.jt_users (email, password_hash) VALUES (%s, %s)",
                ("badhash@example.com", "not-a-valid-hash"),
            )
    db.rollback()
