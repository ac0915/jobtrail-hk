"""CSRF protection for state-changing job endpoints."""
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.jobs as jobs_module
from app.jobs import router


TOKEN = "valid-csrf-token"


@pytest.fixture()
def jobs_app():
    app = FastAPI()
    app.include_router(router)
    pool = MagicMock()
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    pool.connection.return_value.__enter__.return_value = conn
    with patch("app.jobs.get_pool", return_value=pool):
        yield app, cursor


def signed_in_client(app, csrf_header=None):
    app.dependency_overrides[jobs_module.request_user] = lambda: type("User", (), {"id": 7, "email": "user7@example.com"})()
    client = TestClient(app)
    client.cookies.set("jt_csrf", TOKEN)
    if csrf_header is not None:
        client.headers.update({"X-CSRF-Token": csrf_header})
    return client


def test_create_job_rejects_missing_csrf(monkeypatch, jobs_app):
    app, cursor = jobs_app
    monkeypatch.setattr(jobs_module, "MULTI_USER_ENABLED", True)
    client = signed_in_client(app)
    response = client.post("/jobs", json={"title": "Engineer", "company": "Example"})
    assert response.status_code == 403
    assert not any("INSERT INTO public.jobs" in call.args[0] for call in cursor.execute.call_args_list)


def test_update_job_rejects_mismatched_csrf(monkeypatch, jobs_app):
    app, cursor = jobs_app
    monkeypatch.setattr(jobs_module, "MULTI_USER_ENABLED", True)
    client = signed_in_client(app, csrf_header="different-token")
    response = client.patch("/jobs/12", json={"notes": "updated"})
    assert response.status_code == 403
    assert not any("UPDATE public.jobs" in call.args[0] for call in cursor.execute.call_args_list)


def test_delete_job_accepts_matching_csrf(monkeypatch, jobs_app):
    app, cursor = jobs_app
    monkeypatch.setattr(jobs_module, "MULTI_USER_ENABLED", True)
    cursor.fetchone.return_value = {"id": 12}
    client = signed_in_client(app, csrf_header=TOKEN)
    response = client.delete("/jobs/12")
    assert response.status_code == 200
    delete_call = next(call for call in cursor.execute.call_args_list if "DELETE FROM public.jobs" in call.args[0])
    assert delete_call.args[1] == [12, 7]


def test_legacy_mode_does_not_require_csrf(monkeypatch, jobs_app):
    app, cursor = jobs_app
    monkeypatch.setattr(jobs_module, "MULTI_USER_ENABLED", False)
    app.dependency_overrides[jobs_module.request_user] = lambda: None
    cursor.fetchone.return_value = {"id": 1, "created_at": "now", "updated_at": "now", "status": "saved", "applied_at": "today"}
    client = TestClient(app)
    response = client.post("/jobs", json={"title": "Engineer", "company": "Example"})
    assert response.status_code == 200
