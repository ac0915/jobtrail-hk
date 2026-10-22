"""Tests for server-rendered UI page contracts."""
from fastapi.testclient import TestClient

from main import app


def test_home_page_serves_html():
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "JobTrail HK" in response.text


def test_verify_email_page_is_served():
    with TestClient(app) as client:
        response = client.get("/verify-email")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Verify your email" in response.text
    assert "verification-status" in response.text


def test_verify_email_page_calls_verification_api():
    with open("web/verify-email.html", encoding="utf-8") as page_file:
        page = page_file.read()
    assert "new URLSearchParams(window.location.search).get('token')" in page
    assert "fetch('/auth/verify-email'" in page
    assert "JSON.stringify({ token: token })" in page


def test_forgot_password_page_is_served():
    with TestClient(app) as client:
        response = client.get("/forgot-password")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Forgot password?" in response.text
    assert "forgot-form" in response.text


def test_forgot_password_page_calls_forgot_password_api():
    with open("web/forgot-password.html", encoding="utf-8") as page_file:
        page = page_file.read()
    assert "fetch('/auth/forgot-password'" in page
    assert "JSON.stringify({ email: document.getElementById('email').value })" in page


def test_reset_password_page_is_served():
    with TestClient(app) as client:
        response = client.get("/reset-password")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Choose a new password" in response.text
    assert "reset-form" in response.text


def test_reset_password_page_calls_reset_password_api():
    with open("web/reset-password.html", encoding="utf-8") as page_file:
        page = page_file.read()
    assert "new URLSearchParams(window.location.search).get('token')" in page
    assert "fetch('/auth/reset-password'" in page
    assert "JSON.stringify({" in page
    assert "token: token" in page
    assert "password: document.getElementById('password').value" in page
