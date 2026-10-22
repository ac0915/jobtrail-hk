"""Local disposable UI server. Test accounts disappear on normal shutdown."""
import getpass
import os
import subprocess
import sys

from local_sandbox import ROOT, sandbox


def main():
    password = getpass.getpass('Local PostgreSQL postgres password: ')
    with sandbox(password) as connection:
        env = os.environ.copy()
        for key in tuple(env):
            if key.upper().startswith('PG'):
                del env[key]
        env.update(DATABASE_URL=connection, MULTI_USER_ENABLED='true', APP_ENV='development')
        print('Disposable browser test: http://127.0.0.1:8001/login')
        print('Use test-only credentials. Ctrl+C stops the server and deletes its temporary database.')
        child = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'main_ui:app', '--host', '127.0.0.1', '--port', '8001'], cwd=ROOT, env=env)
        try:
            return child.wait()
        except KeyboardInterrupt:
            return 0
        finally:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()


if __name__ == '__main__':
    raise SystemExit(main())
