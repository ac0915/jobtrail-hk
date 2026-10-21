"""Single-owner JobTrail login.
Setup: python personal.py --setup
Run: python -m uvicorn personal:app --reload
Render: python -m uvicorn personal:app --host 0.0.0.0 --port $PORT
Set APP_ORIGIN to the exact HTTPS website origin when deploying.
Sessions last 12 hours, reset on restart, and require one worker/instance.
main:app remains unprotected: always deploy personal:app.
"""
import hashlib
import hmac
import os
import secrets
import sys
import threading
import time
from collections import deque
from getpass import getpass
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

ENV = Path(__file__).resolve().parent / '.env'


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt),
                            n=16384, r=8, p=1, dklen=32).hex()
    return f'scrypt${salt}${digest}'


def verify(password, encoded):
    try:
        kind, salt, digest = encoded.split('$')
        return kind == 'scrypt' and hmac.compare_digest(hash_password(password, salt), encoded)
    except (ValueError, TypeError):
        return False


def setup():
    email = input('Owner email: ').strip().lower()
    if '@' not in email or any(c in email for c in "\r\n'\""):
        raise SystemExit('Invalid email.')
    password = getpass('Password (8-20 characters): ')
    if not 8 <= len(password) <= 20:
        raise SystemExit('Use 8-20 characters.')
    if password != getpass('Confirm password: '):
        raise SystemExit('Passwords do not match.')
    values = {'OWNER_EMAIL': email, 'OWNER_PASSWORD_HASH': hash_password(password)}
    old = ENV.read_text(encoding='utf-8-sig') if ENV.exists() else ''
    lines = [line for line in old.splitlines()
             if line.split('=', 1)[0].strip() not in values]
    lines.extend(f"{key}='{value}'" for key, value in values.items())
    ENV.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('Owner configured in .env; existing DATABASE_URL retained. Do not commit .env.')


if __name__ == '__main__':
    if sys.argv[1:] != ['--setup']:
        raise SystemExit('Use: python personal.py --setup')
    setup()
else:
    from fastapi import Request
    from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
    from main import app

    load_dotenv(dotenv_path=ENV)
    EMAIL = os.getenv('OWNER_EMAIL', '').strip().lower()
    HASH = os.getenv('OWNER_PASSWORD_HASH', '')
    ORIGIN = os.getenv('APP_ORIGIN', 'http://127.0.0.1:8000').rstrip('/')
    parsed = urlsplit(ORIGIN)
    if not EMAIL or not HASH.startswith('scrypt$'):
        raise RuntimeError('Configure login first: python personal.py --setup')
    if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.path or parsed.query or parsed.fragment:
        raise RuntimeError('APP_ORIGIN must be an origin without a path, query or fragment.')
    SECURE = parsed.scheme == 'https'
    if not SECURE and parsed.hostname not in ('localhost', '127.0.0.1', '::1'):
        raise RuntimeError('Public deployments require an HTTPS APP_ORIGIN.')
    COOKIE = 'jobtrail_session'
    TTL = 43200
    sessions = {}
    attempts = deque()
    lock = threading.Lock()

    def page(message=''):
        return HTMLResponse('''<!doctype html><html lang="zh-Hant"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Login | JobTrail HK</title><style>body{font-family:system-ui;background:#eef2f8;color:#233047}main{max-width:380px;margin:12vh auto;background:white;padding:30px;border-radius:18px}label{display:block;margin-top:18px}input,button{box-sizing:border-box;width:100%;padding:12px;margin-top:8px}button{background:#2855c5;color:white;border:0;cursor:pointer}p{color:#ad2639}</style>
<main><h1>JobTrail HK</h1><p>''' + message + '''</p>
<form method="post" action="/auth/login"><label>Email</label>
<input name="email" type="email" autocomplete="username" maxlength="254" required>
<label>Password</label><input name="password" type="password" autocomplete="current-password" maxlength="256" required>
<button type="submit">登入</button></form></main></html>''')

    @app.middleware('http')
    async def personal_access(request: Request, call_next):
        path, method = request.url.path, request.method
        now = time.monotonic()
        if method not in ('GET', 'HEAD', 'OPTIONS') and request.headers.get('origin') != ORIGIN:
            return JSONResponse({'detail': 'Invalid request origin.'}, status_code=403)
        if path == '/healthz' and method == 'GET':
            return JSONResponse({'status': 'ok'})
        if path == '/login' and method == 'GET':
            response = page()
        elif path == '/auth/login' and method == 'POST':
            raw = await request.body()
            if len(raw) > 8192:
                return JSONResponse({'detail': 'Request too large.'}, status_code=413)
            with lock:
                while attempts and attempts[0] <= now - 60:
                    attempts.popleft()
                limited = len(attempts) >= 10
                if not limited:
                    attempts.append(now)
            if limited:
                response = page('Too many attempts. Please wait one minute.')
                response.status_code = 429
                response.headers['Retry-After'] = '60'
            else:
                try:
                    form = await request.form(max_fields=4, max_files=0)
                    email = str(form.get('email', '')).strip().lower()
                    password = str(form.get('password', ''))
                    valid = len(password) <= 256 and verify(password, HASH)
                except Exception:
                    email, valid = '', False
                if valid and hmac.compare_digest(email.encode(), EMAIL.encode()):
                    token = secrets.token_urlsafe(32)
                    key = hashlib.sha256(token.encode()).hexdigest()
                    with lock:
                        for old in list(sessions):
                            if sessions[old] <= now:
                                del sessions[old]
                        if len(sessions) >= 100:
                            del sessions[next(iter(sessions))]
                        sessions[key] = now + TTL
                    response = RedirectResponse('/profile/my-jobs', status_code=303)
                    response.set_cookie(COOKIE, token, max_age=TTL, httponly=True,
                                        secure=SECURE, samesite='strict', path='/')
                else:
                    response = page('Email or password is incorrect.')
                    response.status_code = 401
        else:
            key = hashlib.sha256(request.cookies.get(COOKIE, '').encode()).hexdigest()
            with lock:
                authenticated = sessions.get(key, 0) > now
                if not authenticated:
                    sessions.pop(key, None)
            if not authenticated:
                if method == 'GET' and 'text/html' in request.headers.get('accept', ''):
                    response = RedirectResponse('/login', status_code=303)
                else:
                    response = JSONResponse({'detail': 'Please log in.'}, status_code=401)
            elif path == '/logout' and method == 'GET':
                response = HTMLResponse('<h1>JobTrail HK</h1><form method="post" action="/auth/logout"><button>確認登出 / Log out</button></form>')
            elif path == '/auth/logout' and method == 'POST':
                with lock:
                    sessions.pop(key, None)
                response = RedirectResponse('/login', status_code=303)
                response.delete_cookie(COOKIE, path='/', secure=SECURE, httponly=True, samesite='strict')
            else:
                response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response
