"""Static checks for the mint theme stylesheet and route."""
from pathlib import Path

from fastapi.testclient import TestClient

from main import app

THEME = Path(__file__).resolve().parents[1] / 'web/mint-theme.css'


def test_mint_theme_uses_login_palette():
    css = THEME.read_text(encoding='utf-8')
    assert '#41b9bc' in css
    assert '#f5fffd' in css
    assert '#c5e9e4' in css
    assert '#657671' in css


def test_mint_theme_is_served_as_css():
    with TestClient(app) as client:
        response = client.get('/mint-theme.css')
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('text/css')
    assert '#41b9bc' in response.text
