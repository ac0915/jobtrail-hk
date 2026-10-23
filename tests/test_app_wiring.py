"""Test the real entrypoint in isolated interpreters without loading .env."""
import os
from pathlib import Path
import subprocess
import sys
import textwrap


def check_wiring(flag, enabled):
    env = os.environ.copy()
    env.pop('MULTI_USER_ENABLED', None)
    if flag is not None:
        env['MULTI_USER_ENABLED'] = flag
    code = textwrap.dedent('''
        from unittest.mock import patch
        with patch('dotenv.load_dotenv'):
            import main
        from fastapi.testclient import TestClient
        enabled = EXPECTED
        paths = main.app.openapi()['paths']
        for path in ('/auth/register', '/auth/login', '/auth/me', '/auth/logout'):
            assert (path in paths) == enabled, path
        assert '/jobs' in paths
        assert TestClient(main.app).get('/api-info').json()['multi_user_enabled'] is enabled
    ''').replace('EXPECTED', repr(enabled))
    result = subprocess.run(
        [sys.executable, '-c', code],
        cwd=Path(__file__).resolve().parents[1],
        env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_default_mode_hides_auth_routes():
    check_wiring(None, False)


def test_disabled_mode_hides_auth_routes():
    check_wiring('false', False)


def test_enabled_mode_exposes_auth_routes():
    check_wiring('true', True)
