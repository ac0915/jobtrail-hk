"""Real SQL behind FastAPI routes; email transport is captured, not sent."""
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg import connect
import app.auth_routes as auth

pytestmark = pytest.mark.integration


@pytest.fixture()
def api_client(db, database_url, monkeypatch):
    class LocalPool:
        @contextmanager
        def connection(self, **kwargs):
            with connect(database_url) as conn:
                yield conn

    sent = []

    def capture_email(to, token):
        sent.append({'to': to, 'token': token})
        return {'delivered': True, 'provider': 'test'}

    monkeypatch.setattr(auth, '_pool', lambda: LocalPool())
    monkeypatch.setattr(auth, 'send_verification_email', capture_email)
    monkeypatch.setenv('APP_ENV', 'development')
    auth._attempts.clear()
    app = FastAPI()
    app.include_router(auth.router)
    try:
        with TestClient(app) as client:
            yield client, sent
    finally:
        auth._attempts.clear()


def test_register_logout_login_and_revocation(api_client):
    client, sent = api_client
    credentials = {'email': 'person@example.com', 'password': 'password123'}
    registered = client.post('/auth/register', json=credentials)
    assert registered.status_code == 201
    assert not client.cookies.get(auth.SESSION_COOKIE)
    assert not client.cookies.get(auth.CSRF_COOKIE)
    assert client.get('/auth/me').status_code == 401
    assert client.post('/auth/login', json=credentials).status_code == 403
    assert len(sent) == 1 and sent[0]['to'] == credentials['email']
    assert client.post('/auth/verify-email', json={'token': sent[0]['token']}).status_code == 200
    assert client.post('/auth/login', json=credentials).status_code == 200
    assert client.get('/auth/me').json()['user']['email'] == credentials['email']
    old_token = client.cookies.get(auth.SESSION_COOKIE)
    assert old_token
    assert client.post('/auth/logout').status_code == 403
    csrf = client.cookies.get(auth.CSRF_COOKIE)
    assert csrf
    assert client.post('/auth/logout', headers={auth.CSRF_HEADER: csrf}).status_code == 200
    assert client.get('/auth/me').status_code == 401
    assert client.get('/auth/me', headers={'Cookie': f'{auth.SESSION_COOKIE}={old_token}'}).status_code == 401
    assert client.post('/auth/login', json={**credentials, 'password': 'incorrect123'}).status_code == 401
    assert client.post('/auth/login', json=credentials).status_code == 200
    assert client.cookies.get(auth.SESSION_COOKIE) != old_token
    assert client.get('/auth/me').status_code == 200


def test_duplicate_registration_returns_conflict(api_client):
    client, sent = api_client
    credentials = {'email': 'person@example.com', 'password': 'password123'}
    assert client.post('/auth/register', json=credentials).status_code == 201
    assert client.post('/auth/register', json=credentials).status_code == 409
    assert len(sent) == 1
