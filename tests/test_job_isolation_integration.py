"""Real PostgreSQL authorization tests using independent browser sessions."""
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg import connect

import app.auth_routes as auth
import app.jobs as jobs
from scripts.local_sandbox import DETAIL_COLUMNS

pytestmark = pytest.mark.integration


@pytest.fixture()
def browser_pair(db, database_url, monkeypatch):
    db.execute(DETAIL_COLUMNS)
    db.commit()

    class LocalPool:
        @contextmanager
        def connection(self, **kwargs):
            with connect(database_url) as conn:
                yield conn

    pool = LocalPool()
    monkeypatch.setattr(auth, '_pool', lambda: pool)
    monkeypatch.setattr(jobs, 'get_pool', lambda: pool)
    monkeypatch.setattr(jobs, 'MULTI_USER_ENABLED', True)
    monkeypatch.setenv('APP_ENV', 'development')
    auth._attempts.clear()
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(jobs.router)
    try:
        with TestClient(app) as first, TestClient(app) as second:
            for client, email in ((first, 'first@example.com'), (second, 'second@example.com')):
                response = client.post('/auth/register', json={'email': email, 'password': 'password123'})
                assert response.status_code == 201
            yield first, second, app
    finally:
        auth._attempts.clear()


def save(client, title):
    response = client.post('/jobs', json={'title': title, 'company': 'Test Company'})
    assert response.status_code == 200
    return response.json()['id']


def test_accounts_only_list_their_own_jobs(browser_pair):
    first, second, _ = browser_pair
    first_id, second_id = save(first, 'First private job'), save(second, 'Second private job')
    assert [job['id'] for job in first.get('/jobs').json()] == [first_id]
    assert [job['id'] for job in second.get('/jobs').json()] == [second_id]


def test_other_account_cannot_read_edit_or_delete(browser_pair):
    first, second, _ = browser_pair
    job_id = save(first, 'Private job')
    assert second.get(f'/jobs/{job_id}').status_code == 404
    assert second.patch(f'/jobs/{job_id}', json={'notes': 'unauthorised'}).status_code == 404
    assert second.delete(f'/jobs/{job_id}').status_code == 404
    result = first.get(f'/jobs/{job_id}')
    assert result.status_code == 200
    assert result.json()['notes'] is None


def test_owner_can_edit_and_delete(browser_pair):
    first, _, _ = browser_pair
    job_id = save(first, 'Editable job')
    assert first.patch(f'/jobs/{job_id}', json={'notes': 'Updated'}).status_code == 200
    assert first.get(f'/jobs/{job_id}').json()['notes'] == 'Updated'
    assert first.delete(f'/jobs/{job_id}').status_code == 200
    assert first.get(f'/jobs/{job_id}').status_code == 404


def test_unauthenticated_crud_is_rejected(browser_pair):
    _, _, app = browser_pair
    with TestClient(app) as guest:
        assert guest.get('/jobs').status_code == 401
        assert guest.get('/jobs/1').status_code == 401
        assert guest.post('/jobs', json={'title': 'Guest', 'company': 'Test'}).status_code == 401
        assert guest.patch('/jobs/1', json={'notes': 'Guest'}).status_code == 401
        assert guest.delete('/jobs/1').status_code == 401
