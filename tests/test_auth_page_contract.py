"""Static regression checks; redirects also need a browser smoke test."""
from pathlib import Path

PAGE = Path(__file__).resolve().parents[1] / 'web/auth.html'


def test_auth_page_has_no_intermediate_welcome_controls():
    html = PAGE.read_text(encoding='utf-8')
    assert 'id="signed-in"' not in html
    assert 'id="logout"' not in html
    assert 'Go to My Jobs' not in html
    assert 'Signed in as' not in html


def test_auth_success_uses_fixed_my_jobs_destination():
    html = PAGE.read_text(encoding='utf-8')
    assert "window.location.replace('/profile/my-jobs')" in html
    assert "await api('/auth/me');signedIn();" in html
    assert "registering?'register':'login'" in html
    assert 'if(!redirecting)' in html


def test_auth_page_links_to_forgot_password():
    html = PAGE.read_text(encoding='utf-8')
    assert '<a class="link" href="/forgot-password">Forgot password?</a>' in html
