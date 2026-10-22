"""PostgreSQL tests for email verification tokens and API behavior."""
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg import connect

import app.auth_routes as auth
import app.email as email_module
from scripts.local_sandbox import DETAIL_COLUMNS

pytestmark = pytest.mark.integration


@pytest.fixture()
def verification_app(db, database_url, monkeypatch):
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
    monkeypatch.setattr(auth, 'send_verification_email', capture_email)
    monkeypatch.setattr(auth, 'MULTI_USER_ENABLED', True)
    monkeypatch.setenv('APP_ENV', 'development')
    auth._limiter.attempts.clear()

    app = FastAPI()
    app.include_router(auth.router)
    try:
        with TestClient(app) as client:
            response = client.post('/auth/register', json={'email': 'verify@example.com', 'password': 'password123'})
            assert response.status_code == 201
            yield client, db, sent
    finally:
        auth._limiter.attempts.clear()


def test_verification_token_marks_account_verified_once(verification_app):
    client, _, sent = verification_app
    assert len(sent) == 1
    assert sent[0]['to'] == 'verify@example.com'

    me = client.get('/auth/me').json()['user']
    assert me['email_verified'] is False

    response = client.post('/auth/verify-email', json={'token': sent[0]['token']})
    assert response.status_code == 200

    me = client.get('/auth/me').json()['user']
    assert me['email_verified'] is True

    reuse = client.post('/auth/verify-email', json={'token': sent[0]['token']})
    assert reuse.status_code == 400


def test_expired_token_is_rejected(verification_app):
    client, db, sent = verification_app
    db.execute(
        "UPDATE public.jt_email_tokens SET expires_at = NOW() - INTERVAL '1 second' WHERE user_id = %s",
        (client.get('/auth/me').json()['user']['id'],),
    )
    db.commit()
    response = client.post('/auth/verify-email', json={'token': sent[0]['token']})
    assert response.status_code == 400
    assert client.get('/auth/me').json()['user']['email_verified'] is False


def test_resend_invalidates_previous_token(verification_app):
    client, db, sent = verification_app
    old_token = sent[0]['token']

    response = client.post('/auth/resend-verification')
    assert response.status_code == 200
    assert len(sent) == 2
    new_token = sent[1]['token']
    assert new_token != old_token

    assert client.post('/auth/verify-email', json={'token': old_token}).status_code == 400
    assert client.post('/auth/verify-email', json={'token': new_token}).status_code == 200


def test_invalid_token_is_rejected(verification_app):
    client, _, _ = verification_app
    response = client.post('/auth/verify-email', json={'token': '0' * 64})
    assert response.status_code == 400


def test_local_sender_logs_link_without_network_call(monkeypatch):
    monkeypatch.delenv('RESEND_API_KEY', raising=False)
    logged = []
    monkeypatch.setattr(email_module.logger, 'warning', lambda message, *args: logged.append(message % args))
    result = email_module.send_verification_email('person@example.com', 'a' * 64, base_url='http://testserver/')
    assert result == {'delivered': False, 'provider': 'local'}
    assert any('http://testserver/verify-email?token=' + 'a' * 64 in item for item in logged)
