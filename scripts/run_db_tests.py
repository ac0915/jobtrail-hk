"""Prompt locally; run integration tests against disposable loopback databases."""
import getpass
import os
from pathlib import Path
import subprocess
import sys


def main():
    password = getpass.getpass('Local PostgreSQL postgres password: ')
    env = os.environ.copy()
    for key in tuple(env):
        if key.upper().startswith('PG'):
            del env[key]
    env['PGPASSWORD'] = password
    env['TEST_DATABASE_URL'] = 'host=127.0.0.1 port=5432 dbname=postgres user=postgres sslmode=disable connect_timeout=5'
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, '-m', 'pytest', '-m', 'integration', '-q', '--tb=short'], cwd=root, env=env)
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
