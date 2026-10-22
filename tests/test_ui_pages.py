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
