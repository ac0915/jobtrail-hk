"""Real PostgreSQL authorization and per-user URL uniqueness tests."""
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg import connect, errors

import app.auth_routes as auth
import app.jobs as jobs
from app.accounts import create_user
from scripts.local_sandbox import DETAIL_COLUMNS, URL_SCOPE_MIGRATION

pytestmark = pytest.mark.integration


def apply_url_scope(db):
    db.commit()
    db.execute(URL_SCOPE_MIGRATION.read_text(encoding='utf-8'))
    db.commit()


@pytest.fixture()
def browser_pair(db, database_url, monkeypatch):
    db.execute(DETAIL_COLUMNS)
    db.commit()
    apply_url_scope(db)

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
    auth._limiter.attempts.clear()
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(jobs.router)
    try:
        with TestClient(app) as first, TestClient(app) as second:
            for client, email in ((first, 'first@example.com'), (second, 'second@example.com')):
                response = client.post('/auth/register', json={'email': email, 'password': 'password123'})
                assert response.status_code == 201
                csrf_token = response.cookies.get(auth.CSRF_COOKIE)
                assert csrf_token
                client.headers.update({auth.CSRF_HEADER: csrf_token})
            yield first, second, app
    finally:
        auth._limiter.attempts.clear()


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


def test_same_url_allowed_across_accounts_but_not_within_account(browser_pair):
    first, second, _ = browser_pair
    payload = {'title': 'Shared listing', 'company': 'Test Company', 'url': 'https://example.com/shared-job'}
    a = first.post('/jobs', json=payload)
    b = second.post('/jobs', json=payload)
    assert a.status_code == b.status_code == 200
    assert a.json()['id'] != b.json()['id']
    for client, own_id in ((first, a.json()['id']), (second, b.json()['id'])):
        duplicate = client.post('/jobs', json=payload)
        assert duplicate.status_code == 409
        assert duplicate.json()['detail']['existing_id'] == own_id
        assert [job['id'] for job in client.get('/jobs').json()] == [own_id]


def test_updating_to_own_duplicate_url_is_rejected(browser_pair):
    first, _, _ = browser_pair
    a = first.post('/jobs', json={'title': 'A', 'company': 'Test', 'url': 'https://example.com/a'})
    b = first.post('/jobs', json={'title': 'B', 'company': 'Test', 'url': 'https://example.com/b'})
    assert a.status_code == b.status_code == 200
    response = first.patch('/jobs/' + str(b.json()['id']), json={'url': 'https://example.com/a'})
    assert response.status_code == 409
    assert response.json()['detail']['existing_id'] == a.json()['id']
    assert first.get('/jobs/' + str(b.json()['id'])).json()['url'] == 'https://example.com/b'


def test_database_indexes_enforce_owner_and_legacy_uniqueness(db):
    db.execute('INSERT INTO public.jobs (title, company, url) VALUES (%s, %s, %s)', ('Legacy', 'Test', 'https://example.com/shared'))
    db.commit()
    apply_url_scope(db)
    account = create_user(db, 'index@example.com', 'password123', reserved_email='owner@example.com')
    db.execute('INSERT INTO public.jobs (title, company, url, user_id) VALUES (%s, %s, %s, %s)', ('Owned', 'Test', 'https://example.com/shared', account['id']))
    db.commit()
    with pytest.raises(errors.UniqueViolation):
        db.execute('INSERT INTO public.jobs (title, company, url, user_id) VALUES (%s, %s, %s, %s)', ('Duplicate', 'Test', 'https://example.com/shared', account['id']))
    db.rollback()
    with pytest.raises(errors.UniqueViolation):
        db.execute('INSERT INTO public.jobs (title, company, url) VALUES (%s, %s, %s)', ('Duplicate legacy', 'Test', 'https://example.com/shared'))
    db.rollback()
    assert db.execute('SELECT COUNT(*) FROM public.jobs').fetchone()[0] == 2
