"""Tests for application router wiring and the multi-user feature flag."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

import main
from app.auth_routes import router as auth_router
from app.jobs import router as jobs_router


def test_default_mode_hides_auth_routes():
    client = TestClient(main.app)
    paths = main.app.openapi()["paths"]
    assert "/auth/register" not in paths
    assert "/auth/login" not in paths
    assert "/jobs" in paths
    assert client.get("/api-info").json()["multi_user_enabled"] is False


def test_enabled_mode_exposes_auth_routes(monkeypatch):
    monkeypatch.setattr(main, "MULTI_USER_ENABLED", True)

    app = FastAPI()
    app.include_router(jobs_router)
    if main.MULTI_USER_ENABLED:
        app.include_router(auth_router)

    paths = app.openapi()["paths"]
    assert "/auth/register" in paths
    assert "/auth/login" in paths
    assert "/auth/me" in paths
    assert "/auth/logout" in paths
