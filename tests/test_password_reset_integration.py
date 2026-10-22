"""PostgreSQL tests for password reset tokens and API behavior."""
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg import connect

import app.auth_routes as auth
from app.accounts import create_user
from scripts.local_sandbox import DETAIL_COLUMNS

pytestmark = pytest.mark.integration


@pytest.fixture()
def reset_app(db, database_url, monkeypatch):
    db.execute(DETAIL_COLUMNS)
    db.commit()

    class LocalPool:
        @contextmanager
        def connection(self, **kwargs):
            with connect(database_url) as conn:
                yield conn

    pool = LocalPool()
    sent = []

    def capture_email(to, raw_token, base_url=None):
        sent.append({"to": to, "token": raw_token})
        return {"delivered": True, "provider": "test"}

    monkeypatch.setattr(auth, '_pool', lambda: pool)
    monkeypatch.setattr(auth, 'send_password_reset_email', capture_email)
    monkeypatch.setattr(auth, 'send_verification_email', lambda *args: {'delivered': True, 'provider': 'test'})
    monkeypatch.setenv('APP_ENV', 'development')
    auth._limiter.attempts.clear()

    app = FastAPI()
    app.include_router(auth.router)
    try:
        with TestClient(app) as client:
            response = client.post('/auth/register', json={'email': 'reset@example.com', 'password': 'oldpass123'})
            assert response.status_code == 201
            yield client, db, sent
    finally:
        auth._limiter.attempts.clear()


def test_password_reset_changes_password_and_revokes_sessions(reset_app):
    client, db, sent = reset_app
    client.post('/auth/login', json={'email': 'reset@example.com', 'password': 'oldpass123'})

    response = client.post('/auth/forgot-password', json={'email': 'reset@example.com'})
    assert response.status_code == 200
    assert response.json()['message'] == 'If that email has an account, a reset link has been sent.'
    assert len(sent) == 1

    reset = client.post('/auth/reset-password', json={'token': sent[0]['token'], 'password': 'newpass123'})
    assert reset.status_code == 200

    old_login = client.post('/auth/login', json={'email': 'reset@example.com', 'password': 'oldpass123'})
    assert old_login.status_code == 401

    new_login = client.post('/auth/login', json={'email': 'reset@example.com', 'password': 'newpass123'})
    assert new_login.status_code == 200

    assert db.execute('SELECT COUNT(*) FROM public.jt_sessions').fetchone()[0] == 1


def test_reset_token_cannot_be_reused(reset_app):
    client, db, sent = reset_app
    client.post('/auth/forgot-password', json={'email': 'reset@example.com'})
    token = sent[0]['token']

    first = client.post('/auth/reset-password', json={'token': token, 'password': 'newpass123'})
    assert first.status_code == 200
    second = client.post('/auth/reset-password', json={'token': token, 'password': 'another123'})
    assert second.status_code == 400


def test_unknown_email_does_not_send_or_leak_existence(reset_app):
    client, db, sent = reset_app
    response = client.post('/auth/forgot-password', json={'email': 'missing@example.com'})
    assert response.status_code == 200
    assert response.json()['message'] == 'If that email has an account, a reset link has been sent.'
    assert sent == []


def test_expired_reset_token_is_rejected(reset_app):
    client, db, sent = reset_app
    client.post('/auth/forgot-password', json={'email': 'reset@example.com'})
    db.execute(
        """
        UPDATE public.jt_email_tokens
        SET created_at = NOW() - INTERVAL '2 hours',
            expires_at = NOW() - INTERVAL '1 hour'
        WHERE purpose = 'password_reset'
        """,
    )
    db.commit()
    response = client.post('/auth/reset-password', json={'token': sent[0]['token'], 'password': 'newpass123'})
    assert response.status_code == 400


def test_weak_password_is_rejected(reset_app):
    client, db, sent = reset_app
    client.post('/auth/forgot-password', json={'email': 'reset@example.com'})
    response = client.post('/auth/reset-password', json={'token': sent[0]['token'], 'password': 'short'})
    assert response.status_code == 422
