"""PostgreSQL password-reset tests with verified users and captured email."""
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg import connect

import app.auth_routes as auth
from scripts.local_sandbox import DETAIL_COLUMNS

pytestmark = pytest.mark.integration
CREDENTIALS = {'email': 'reset@example.com', 'password': 'oldpass123'}


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
    verification = []

    def capture_email(to, raw_token, base_url=None):
        sent.append({'to': to, 'token': raw_token})
        return {'delivered': True, 'provider': 'test'}

    def capture_verification(to, raw_token):
        verification.append({'to': to, 'token': raw_token})
        return {'delivered': True, 'provider': 'test'}

    monkeypatch.setattr(auth, '_pool', lambda: pool)
    monkeypatch.setattr(auth, 'send_password_reset_email', capture_email)
    monkeypatch.setattr(auth, 'send_verification_email', capture_verification)
    monkeypatch.setenv('APP_ENV', 'development')
    auth._limiter.attempts.clear()
    app = FastAPI()
    app.include_router(auth.router)
    try:
        with TestClient(app) as client:
            assert client.post('/auth/register', json=CREDENTIALS).status_code == 201
            assert len(verification) == 1
            assert client.post('/auth/verify-email', json={'token': verification[0]['token']}).status_code == 200
            yield client, db, sent
    finally:
        auth._limiter.attempts.clear()


def test_password_reset_changes_password_and_revokes_sessions(reset_app):
    client, db, sent = reset_app
    with TestClient(client.app) as second:
        assert client.post('/auth/login', json=CREDENTIALS).status_code == 200
        assert second.post('/auth/login', json=CREDENTIALS).status_code == 200
        assert db.execute('SELECT COUNT(*) FROM public.jt_sessions').fetchone()[0] == 2
        db.commit()
        response = client.post('/auth/forgot-password', json={'email': CREDENTIALS['email']})
        assert response.status_code == 200
        assert response.json()['message'] == 'If that email has an account, a reset link has been sent.'
        assert len(sent) == 1
        reset = client.post('/auth/reset-password', json={'token': sent[0]['token'], 'password': 'newpass123'})
        assert reset.status_code == 200
        assert db.execute('SELECT COUNT(*) FROM public.jt_sessions').fetchone()[0] == 0
        db.commit()
        assert client.get('/auth/me').status_code == 401
        assert second.get('/auth/me').status_code == 401
        assert client.post('/auth/login', json=CREDENTIALS).status_code == 401
        assert client.post('/auth/login', json={**CREDENTIALS, 'password': 'newpass123'}).status_code == 200
        assert client.get('/auth/me').status_code == 200
        assert second.get('/auth/me').status_code == 401
        assert db.execute('SELECT COUNT(*) FROM public.jt_sessions').fetchone()[0] == 1


def test_reset_token_cannot_be_reused(reset_app):
    client, db, sent = reset_app
    assert client.post('/auth/forgot-password', json={'email': CREDENTIALS['email']}).status_code == 200
    token = sent[0]['token']
    assert client.post('/auth/reset-password', json={'token': token, 'password': 'newpass123'}).status_code == 200
    assert client.post('/auth/reset-password', json={'token': token, 'password': 'another123'}).status_code == 400


def test_unknown_email_does_not_send_or_leak_existence(reset_app):
    client, db, sent = reset_app
    response = client.post('/auth/forgot-password', json={'email': 'missing@example.com'})
    assert response.status_code == 200
    assert response.json()['message'] == 'If that email has an account, a reset link has been sent.'
    assert sent == []


def test_expired_reset_token_is_rejected(reset_app):
    client, db, sent = reset_app
    assert client.post('/auth/forgot-password', json={'email': CREDENTIALS['email']}).status_code == 200
    db.execute("UPDATE public.jt_email_tokens SET created_at = NOW() - INTERVAL '2 hours', expires_at = NOW() - INTERVAL '1 hour' WHERE purpose = 'password_reset'")
    db.commit()
    assert client.post('/auth/reset-password', json={'token': sent[0]['token'], 'password': 'newpass123'}).status_code == 400


def test_weak_password_is_rejected(reset_app):
    client, db, sent = reset_app
    assert client.post('/auth/forgot-password', json={'email': CREDENTIALS['email']}).status_code == 200
    assert client.post('/auth/reset-password', json={'token': sent[0]['token'], 'password': 'short'}).status_code == 422
