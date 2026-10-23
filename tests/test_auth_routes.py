"""FastAPI TestClient tests for authentication routes."""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg import errors

from app.auth_routes import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE, _attempts, router
from app.auth_security import hash_password


@pytest.fixture(autouse=True)
def reset_rate_limits(monkeypatch):
    monkeypatch.setenv('APP_ENV', 'development')
    _attempts.clear()
    yield
    _attempts.clear()


@pytest.fixture()
def app_and_pool():
    app = FastAPI()
    app.include_router(router)
    pool = MagicMock()
    conn = MagicMock()
    pool.connection.return_value.__enter__.return_value = conn
    with patch("app.auth_routes.get_pool", return_value=pool):
        yield app, conn, pool


@pytest.fixture()
def client(app_and_pool):
    app, _, _ = app_and_pool
    return TestClient(app)


def register_response(client, email="friend@example.com", password="password123"):
    return client.post("/auth/register", json={"email": email, "password": password})


def test_register_creates_account_and_sends_verification_without_session(app_and_pool, client):
    _, conn, _ = app_and_pool
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = (2, "friend@example.com")
    with patch("app.auth_routes.send_verification_email", return_value={'delivered': True, 'provider': 'test'}) as send_email:
        response = register_response(client)
    assert response.status_code == 201
    assert response.json() == {"message": "Account created. Check your email and click the verification link.", "user": {"id": 2, "email": "friend@example.com"}}
    assert not response.cookies.get(SESSION_COOKIE)
    assert not response.cookies.get(CSRF_COOKIE)
    assert not client.cookies.get(SESSION_COOKIE)
    assert not client.cookies.get(CSRF_COOKIE)
    assert 'set-cookie' not in response.headers
    assert conn.commit.call_count == 2
    send_email.assert_called_once()
    recipient, token = send_email.call_args.args
    assert recipient == 'friend@example.com'
    assert isinstance(token, str) and len(token) >= 32


def test_register_rejects_short_password_and_invalid_email(client):
    assert client.post("/auth/register", json={"email": "friend@example.com", "password": "short"}).status_code == 422
    assert client.post("/auth/register", json={"email": "not-an-email", "password": "password123"}).status_code == 422


def test_register_duplicate_email_returns_409(app_and_pool, client):
    _, conn, _ = app_and_pool
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = (2, "friend@example.com")
    conn.commit.side_effect = errors.UniqueViolation
    response = register_response(client)
    assert response.status_code == 409
    assert response.json()["detail"] == "An account with this email already exists."


def set_verified_login_rows(conn):
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.side_effect = [
        (2, 'friend@example.com', hash_password('password123'), True, datetime(2026, 1, 1, tzinfo=timezone.utc)),
        (2,),
    ]
    return cur


def test_login_success_and_generic_failure(app_and_pool, client):
    _, conn, _ = app_and_pool
    cur = set_verified_login_rows(conn)
    response = client.post("/auth/login", json={"email": "friend@example.com", "password": "password123"})
    assert response.status_code == 200
    assert response.cookies.get(SESSION_COOKIE)
    assert response.cookies.get(CSRF_COOKIE)
    cookies = response.headers.get_list('set-cookie')
    session_cookie = next(value for value in cookies if value.startswith(SESSION_COOKIE + '='))
    csrf_cookie = next(value for value in cookies if value.startswith(CSRF_COOKIE + '='))
    assert 'HttpOnly' in session_cookie
    assert 'HttpOnly' not in csrf_cookie
    assert all('SameSite=lax' in value for value in cookies)
    assert all('Secure' not in value for value in cookies)
    cur.fetchone.side_effect = None
    cur.fetchone.return_value = None
    failed = client.post("/auth/login", json={"email": "friend@example.com", "password": "wrongpass1"})
    assert failed.status_code == 401
    assert failed.json()["detail"] == "Invalid email or password."


def test_login_rejects_unverified_account_without_session(app_and_pool, client):
    _, conn, _ = app_and_pool
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = (2, 'friend@example.com', hash_password('password123'), True, None)
    response = client.post('/auth/login', json={'email': 'friend@example.com', 'password': 'password123'})
    assert response.status_code == 403
    assert response.json()['detail'] == 'Please verify your email address before signing in.'
    assert 'set-cookie' not in response.headers
    cur.fetchone.assert_called_once()
    assert not any('INSERT INTO public.jt_sessions' in call.args[0] for call in cur.execute.call_args_list)
    conn.commit.assert_not_called()


def test_production_login_sets_secure_cookies(app_and_pool, client, monkeypatch):
    monkeypatch.setenv('APP_ENV', 'production')
    _, conn, _ = app_and_pool
    set_verified_login_rows(conn)
    response = client.post('/auth/login', json={'email': 'friend@example.com', 'password': 'password123'})
    assert response.status_code == 200
    assert response.cookies.get(SESSION_COOKIE)
    assert response.cookies.get(CSRF_COOKIE)
    cookies = response.headers.get_list('set-cookie')
    assert len(cookies) == 2
    assert all('Secure' in value for value in cookies)
    assert all('SameSite=lax' in value for value in cookies)
    assert any(value.startswith(SESSION_COOKIE + '=') and 'HttpOnly' in value for value in cookies)
    assert any(value.startswith(CSRF_COOKIE + '=') and 'HttpOnly' not in value for value in cookies)


def test_me_requires_session(app_and_pool, client):
    _, conn, _ = app_and_pool
    assert client.get("/auth/me").status_code == 401
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = (2, "friend@example.com", None)
    client.cookies.set(SESSION_COOKIE, "A" * 43)
    response = client.get("/auth/me")
    assert response.status_code == 200
    assert response.json()["user"] == {"id": 2, "email": "friend@example.com", "email_verified": False}


def test_logout_requires_csrf_and_clears_cookies(app_and_pool, client):
    _, conn, _ = app_and_pool
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = (2, "friend@example.com", None)
    client.cookies.set(SESSION_COOKIE, "A" * 43)
    client.cookies.set(CSRF_COOKIE, "csrf-token")
    missing = client.post("/auth/logout")
    assert missing.status_code == 403
    response = client.post("/auth/logout", headers={CSRF_HEADER: "csrf-token"})
    assert response.status_code == 200
    set_cookie = response.headers["set-cookie"]
    assert f'{SESSION_COOKIE}=""' in set_cookie
    assert "Max-Age=0" in set_cookie
    assert f'{CSRF_COOKIE}=""' in set_cookie
    conn.commit.assert_called_once()


def test_rate_limit_blocks_sixth_login_attempt(app_and_pool, client):
    _, conn, _ = app_and_pool
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = None
    for _ in range(5):
        assert client.post("/auth/login", json={"email": "friend@example.com", "password": "wrongpass1"}).status_code == 401
    sixth = client.post("/auth/login", json={"email": "friend@example.com", "password": "wrongpass1"})
    assert sixth.status_code == 429


def test_oversized_request_is_rejected(client):
    response = client.post("/auth/register", json={"email": "friend@example.com", "password": "password123"}, headers={"Content-Length": "5000"})
    assert response.status_code == 413
