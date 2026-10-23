"""PostgreSQL email-verification tests with captured email transport."""
from contextlib import contextmanager
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg import connect

import app.auth_routes as auth
import app.email as email_module
from scripts.local_sandbox import DETAIL_COLUMNS

pytestmark = pytest.mark.integration
CREDENTIALS = {'email': 'verify@example.com', 'password': 'password123'}


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
        sent.append({'to': to, 'token': raw_token})
        return {'delivered': True, 'provider': 'test'}

    monkeypatch.setattr(auth, '_pool', lambda: pool)
    monkeypatch.setattr(auth, 'send_verification_email', capture_email)
    monkeypatch.setenv('APP_ENV', 'development')
    auth._limiter.attempts.clear()
    app = FastAPI()
    app.include_router(auth.router)
    try:
        with TestClient(app) as client:
            response = client.post('/auth/register', json=CREDENTIALS)
            assert response.status_code == 201
            assert not client.cookies.get(auth.SESSION_COOKIE)
            assert not client.cookies.get(auth.CSRF_COOKIE)
            assert len(sent) == 1
            yield client, db, sent
    finally:
        auth._limiter.attempts.clear()


def test_verification_token_marks_account_verified_once(verification_app):
    client, db, sent = verification_app
    assert sent[0]['to'] == CREDENTIALS['email']
    assert client.get('/auth/me').status_code == 401
    assert client.post('/auth/login', json=CREDENTIALS).status_code == 403
    assert client.post('/auth/verify-email', json={'token': sent[0]['token']}).status_code == 200
    assert client.get('/auth/me').status_code == 401
    assert client.post('/auth/login', json=CREDENTIALS).status_code == 200
    assert client.get('/auth/me').json()['user']['email_verified'] is True
    assert client.post('/auth/verify-email', json={'token': sent[0]['token']}).status_code == 400


def test_expired_token_is_rejected(verification_app):
    client, db, sent = verification_app
    db.execute("UPDATE public.jt_email_tokens SET created_at = NOW() - INTERVAL '25 hours', expires_at = NOW() - INTERVAL '1 hour' WHERE user_id = (SELECT id FROM public.jt_users WHERE email = %s)", (CREDENTIALS['email'],))
    db.commit()
    assert client.post('/auth/verify-email', json={'token': sent[0]['token']}).status_code == 400
    assert client.post('/auth/login', json=CREDENTIALS).status_code == 403
    assert db.execute('SELECT email_verified_at FROM public.jt_users WHERE email = %s', (CREDENTIALS['email'],)).fetchone()[0] is None
    assert db.execute('SELECT COUNT(*) FROM public.jt_sessions').fetchone()[0] == 0


def test_resend_invalidates_previous_token(verification_app):
    client, db, sent = verification_app
    old_token = sent[0]['token']
    response = client.post('/auth/resend-verification', json={'email': CREDENTIALS['email']})
    assert response.status_code == 200
    assert len(sent) == 2
    new_token = sent[1]['token']
    assert new_token != old_token
    assert client.post('/auth/verify-email', json={'token': old_token}).status_code == 400
    assert client.post('/auth/verify-email', json={'token': new_token}).status_code == 200
    assert client.post('/auth/login', json=CREDENTIALS).status_code == 200


def test_invalid_token_is_rejected(verification_app):
    client, _, _ = verification_app
    assert client.post('/auth/verify-email', json={'token': '0' * 64}).status_code == 400


def test_sender_requires_private_configuration_without_network_call(monkeypatch):
    monkeypatch.delenv('GMAIL_TOKEN_JSON', raising=False)
    monkeypatch.delenv('GMAIL_TOKEN_FILE', raising=False)
    monkeypatch.setenv('APP_ENV', 'development')
    load = Mock(side_effect=AssertionError('Credentials must not be loaded'))
    network = Mock(side_effect=AssertionError('Network must not be called'))
    monkeypatch.setattr(email_module, '_load_credentials', load)
    monkeypatch.setattr(email_module.httpx, 'post', network)
    with pytest.raises(RuntimeError, match='Set exactly one of GMAIL_TOKEN_JSON or GMAIL_TOKEN_FILE'):
        email_module.send_verification_email('person@example.com', 'a' * 64, base_url='http://testserver/')
    load.assert_not_called()
    network.assert_not_called()
