"""UI route tests with no database connection."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.ui import install_ui


def make_client(tmp_path, enabled):
    (tmp_path / 'auth.html').write_text('<html><body>Login<form id="auth-form"></form></body></html>', encoding='utf-8')
    (tmp_path / 'index.html').write_text('<html><head></head><body>Tracker</body></html>', encoding='utf-8')
    (tmp_path / 'auth-nav.js').write_text('/* navigation fixture */', encoding='utf-8')
    app = FastAPI()

    @app.get('/')
    def original():
        return {'legacy': True}

    install_ui(app, tmp_path, enabled=enabled)
    return TestClient(app)


def test_login_and_register_pages(tmp_path):
    client = make_client(tmp_path, False)
    assert 'auth-form' in client.get('/login').text
    response = client.get('/register')
    assert response.status_code == 200
    assert '.click()' in response.text
    assert response.headers['cache-control'] == 'no-store'


def test_enabled_tracker_injects_navigation(tmp_path):
    client = make_client(tmp_path, True)
    for path in ('/', '/profile', '/profile/my-jobs', '/my-jobs'):
        response = client.get(path)
        assert response.status_code == 200
        assert '<script src="/ui/auth-nav.js"></script></head>' in response.text
        assert 'Tracker' in response.text


def test_disabled_tracker_is_unchanged(tmp_path):
    client = make_client(tmp_path, False)
    assert client.get('/').json() == {'legacy': True}


def test_navigation_asset(tmp_path):
    client = make_client(tmp_path, True)
    response = client.get('/ui/auth-nav.js')
    assert response.status_code == 200
    assert 'text/javascript' in response.headers['content-type']


def test_missing_auth_page(tmp_path):
    client = make_client(tmp_path, True)
    (tmp_path / 'auth.html').unlink()
    assert client.get('/login').status_code == 500
