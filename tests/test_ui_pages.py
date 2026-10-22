"""UI route tests; browser interactions still require a manual smoke test."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.ui import install_ui, render_auth_page


def make_client(tmp_path, enabled):
    (tmp_path / 'auth.html').write_text('<html><head></head><body><main class="card">Login<form id="auth-form"></form></main></body></html>', encoding='utf-8')
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
    for path in ('/login', '/register'):
        response = client.get(path)
        assert response.status_code == 200
        assert 'auth-form' in response.text
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


def test_split_layout_and_original_artwork(tmp_path):
    response = make_client(tmp_path, False).get('/login')
    assert 'class="auth-layout"' in response.text
    assert 'class="auth-brand"' in response.text
    assert 'jobtrail-art-title' in response.text
    assert '@media(max-width:800px)' in response.text
    assert 'Your next opportunity starts here.' in response.text


def test_url_sync_script_is_included(tmp_path):
    html = make_client(tmp_path, False).get('/register').text
    assert 'history.pushState' in html
    assert "addEventListener('popstate'" in html
    assert "location.pathname === '/register'" in html


def test_layout_preserves_existing_auth_script():
    original = '<html><head></head><body><main class="card">form</main><script>existingAuth();</script></body></html>'
    rendered = render_auth_page(original)
    assert '<script>existingAuth();</script>' in rendered
    assert rendered.index('existingAuth();') < rendered.index('syncFromUrl')
    assert rendered.count('class="auth-layout"') == 1
