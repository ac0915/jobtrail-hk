"""Tests for flagged job ownership scoping."""
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.jobs as jobs_module
from app.jobs import router


CSRF_TOKEN = "test-csrf-token"


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
        yield app, cursor, conn


def client_for(app, user):
    if user is not None:
        app.dependency_overrides[jobs_module.request_user] = lambda: user
    else:
        app.dependency_overrides[jobs_module.request_user] = lambda: None
    client = TestClient(app)
    if user is not None:
        client.cookies.set("jt_csrf", CSRF_TOKEN)
        client.headers.update({"X-CSRF-Token": CSRF_TOKEN})
    return client


class User:
    def __init__(self, id):
        self.id = id
        self.email = f"user{id}@example.com"


def test_multi_user_requires_session(monkeypatch, jobs_app):
    app, _, _ = jobs_app
    monkeypatch.setattr(jobs_module, "MULTI_USER_ENABLED", True)
    client = TestClient(app)
    response = client.get("/jobs")
    assert response.status_code == 401


def test_list_jobs_scopes_by_user(monkeypatch, jobs_app):
    app, cursor, _ = jobs_app
    monkeypatch.setattr(jobs_module, "MULTI_USER_ENABLED", True)
    cursor.fetchall.return_value = []
    client = client_for(app, User(7))
    assert client.get("/jobs").status_code == 200
    sql, values = cursor.execute.call_args.args
    assert "WHERE user_id = %s" in sql
    assert values == [7]


def test_get_job_scopes_by_user(monkeypatch, jobs_app):
    app, cursor, _ = jobs_app
    monkeypatch.setattr(jobs_module, "MULTI_USER_ENABLED", True)
    cursor.fetchone.return_value = None
    client = client_for(app, User(7))
    assert client.get("/jobs/12").status_code == 404
    sql, values = cursor.execute.call_args.args
    assert "AND user_id = %s" in sql
    assert values == [12, 7]


def test_create_job_inserts_user_id(monkeypatch, jobs_app):
    app, cursor, _ = jobs_app
    monkeypatch.setattr(jobs_module, "MULTI_USER_ENABLED", True)
    cursor.fetchone.return_value = {"id": 1, "created_at": "now", "updated_at": "now", "status": "saved", "applied_at": "today"}
    client = client_for(app, User(7))
    response = client.post("/jobs", json={"title": "Engineer", "company": "Example"})
    assert response.status_code == 200
    insert_call = next(call for call in cursor.execute.call_args_list if "INSERT INTO public.jobs" in call.args[0])
    sql, values = insert_call.args
    assert "user_id" in sql
    assert 7 in values


def test_update_and_delete_scope_by_user(monkeypatch, jobs_app):
    app, cursor, _ = jobs_app
    monkeypatch.setattr(jobs_module, "MULTI_USER_ENABLED", True)
    cursor.fetchone.return_value = {"id": 12, "applied_at": None}
    client = client_for(app, User(7))

    assert client.patch("/jobs/12", json={"notes": "updated"}).status_code == 200
    update_call = next(call for call in cursor.execute.call_args_list if "UPDATE public.jobs" in call.args[0])
    assert "AND user_id = %s" in update_call.args[0]
    assert 7 in update_call.args[1]

    cursor.fetchone.return_value = {"id": 12}
    assert client.delete("/jobs/12").status_code == 200
    delete_call = next(call for call in cursor.execute.call_args_list if "DELETE FROM public.jobs" in call.args[0])
    assert "AND user_id = %s" in delete_call.args[0]
    assert delete_call.args[1] == [12, 7]


def test_duplicate_check_scopes_by_user(monkeypatch, jobs_app):
    app, cursor, _ = jobs_app
    monkeypatch.setattr(jobs_module, "MULTI_USER_ENABLED", True)
    cursor.fetchone.side_effect = [None, {"id": 1, "created_at": "now", "updated_at": "now", "status": "saved", "applied_at": "today"}]
    client = client_for(app, User(7))
    response = client.post("/jobs", json={"title": "Engineer", "company": "Example", "url": "https://example.com/job"})
    assert response.status_code == 200

    duplicate_call = next(
        call
        for call in cursor.execute.call_args_list
        if "FROM public.jobs" in call.args[0]
        and "url = %s" in call.args[0]
        and "INSERT INTO" not in call.args[0]
    )
    assert "AND user_id = %s" in duplicate_call.args[0]
    assert duplicate_call.args[1] == ["https://example.com/job", 7]


def test_disabled_mode_preserves_legacy_behavior(monkeypatch, jobs_app):
    app, cursor, _ = jobs_app
    monkeypatch.setattr(jobs_module, "MULTI_USER_ENABLED", False)
    cursor.fetchall.return_value = []
    client = client_for(app, None)
    assert client.get("/jobs").status_code == 200
    sql, values = cursor.execute.call_args.args
    assert "WHERE user_id" not in sql
    assert values == []
