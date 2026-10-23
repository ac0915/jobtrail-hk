"""Cover-letter route authorization without PostgreSQL or real email."""
from unittest.mock import Mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import app.auth_routes as auth
import app.cover_letters as letters
import app.jobs as jobs


@pytest.fixture()
def extraction_client(monkeypatch):
    monkeypatch.setattr(jobs, 'MULTI_USER_ENABLED', True)

    def fake_current_user(request):
        if request.cookies.get(auth.SESSION_COOKIE) != 'valid-test-session':
            raise HTTPException(401, 'Not signed in.')
        return auth.AuthUser(id=1, email='test@example.com', email_verified=True)

    monkeypatch.setattr(auth, 'current_user', fake_current_user)
    extract = Mock(return_value='Test letter')
    monkeypatch.setattr(letters, 'extract_letter', extract)
    app = FastAPI()
    app.include_router(jobs.router)
    with TestClient(app) as client:
        yield client, extract


def upload(client, headers=None):
    return client.post(
        '/jobs/cover-letter/extract',
        files={'file': ('letter.pdf', b'%PDF-test', 'application/pdf')},
        headers=headers or {},
    )


@pytest.mark.parametrize('session', [None, 'invalid-test-session'])
def test_anonymous_or_invalid_session_is_rejected(extraction_client, session):
    client, extract = extraction_client
    if session is not None:
        client.cookies.set(auth.SESSION_COOKIE, session)
    assert upload(client).status_code == 401
    extract.assert_not_called()


@pytest.mark.parametrize('cookie,header', [(None, None), ('csrf-test', None), ('csrf-test', 'wrong')])
def test_signed_in_user_requires_matching_csrf(extraction_client, cookie, header):
    client, extract = extraction_client
    client.cookies.set(auth.SESSION_COOKIE, 'valid-test-session')
    if cookie is not None:
        client.cookies.set(auth.CSRF_COOKIE, cookie)
    headers = {auth.CSRF_HEADER: header} if header is not None else {}
    assert upload(client, headers).status_code == 403
    extract.assert_not_called()


def test_signed_in_user_with_csrf_can_extract(extraction_client):
    client, extract = extraction_client
    client.cookies.set(auth.SESSION_COOKIE, 'valid-test-session')
    client.cookies.set(auth.CSRF_COOKIE, 'csrf-test')
    response = upload(client, {auth.CSRF_HEADER: 'csrf-test'})
    assert response.status_code == 200
    assert response.json() == {
        'text': 'Test letter',
        'characters': 11,
        'filename': 'letter.pdf',
        'saved': False,
    }
    extract.assert_called_once_with(b'%PDF-test', '.pdf')


def test_single_user_mode_keeps_existing_behavior(extraction_client, monkeypatch):
    client, extract = extraction_client
    monkeypatch.setattr(jobs, 'MULTI_USER_ENABLED', False)
    assert upload(client).status_code == 200
    extract.assert_called_once()
