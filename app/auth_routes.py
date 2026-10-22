"""Authentication endpoints, wired only when multi-user mode is enabled."""
from __future__ import annotations

import os
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from psycopg import errors
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.accounts import authenticate_user, create_session, create_user, resolve_session, revoke_session
from app.auth_limits import AttemptLimiter, RateLimited
from app.database import get_pool

SESSION_COOKIE = 'jt_session'
CSRF_COOKIE = 'jt_csrf'
CSRF_HEADER = 'X-CSRF-Token'
RESERVED_OWNER_EMAIL = 'owner@example.com'
MAX_BODY_BYTES = 4096
MAX_ATTEMPTS = 5
ATTEMPT_WINDOW_SECONDS = 900


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: EmailStr = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=20)

    @field_validator('email')
    @classmethod
    def strip_email(cls, value: EmailStr) -> EmailStr:
        return value.strip()


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: EmailStr = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)

    @field_validator('email')
    @classmethod
    def strip_email(cls, value: EmailStr) -> EmailStr:
        return value.strip()


class AuthUser(BaseModel):
    id: int
    email: str


router = APIRouter(prefix='/auth', tags=['Authentication'])
_limiter = AttemptLimiter(limit=MAX_ATTEMPTS, window=ATTEMPT_WINDOW_SECONDS)
# Compatibility for isolated tests; never clear counters in live request handlers.
_attempts = _limiter.attempts


def _client_key(request: Request, action: str):
    # Only the ASGI server's validated client address; do not parse caller headers.
    return (request.client.host if request.client else 'unknown'), action


def _rate_limit(request: Request, action: str) -> None:
    try:
        _limiter.check(_client_key(request, action))
    except RateLimited as exc:
        raise HTTPException(429, 'Too many attempts. Try again later.', headers={'Retry-After': str(exc.retry_after)}) from None


def _json_body_size(request: Request) -> None:
    declared = request.headers.get('content-length')
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, 'Request body too large.')


def _pool() -> ConnectionPool:
    return get_pool()


def _issue_session(response: Response, conn, user_id: int) -> None:
    token = create_session(conn, user_id)
    csrf = os.urandom(24).hex()
    secure = os.getenv('APP_ENV', 'development') == 'production'
    response.set_cookie(SESSION_COOKIE, token, max_age=12 * 60 * 60, httponly=True, secure=secure, samesite='lax', path='/')
    response.set_cookie(CSRF_COOKIE, csrf, max_age=12 * 60 * 60, httponly=False, secure=secure, samesite='lax', path='/')


def _require_csrf(request: Request) -> None:
    if request.method in {'GET', 'HEAD', 'OPTIONS'}:
        return
    cookie = request.cookies.get(CSRF_COOKIE, '')
    header = request.headers.get(CSRF_HEADER, '')
    if not cookie or not header or not secrets_compare_digest(cookie, header):
        raise HTTPException(status.HTTP_403_FORBIDDEN, 'Invalid CSRF token.')


def secrets_compare_digest(left: str, right: str) -> bool:
    import hmac
    return hmac.compare_digest(left.encode('ascii', 'ignore'), right.encode('ascii', 'ignore'))


def current_user(request: Request) -> AuthUser:
    token = request.cookies.get(SESSION_COOKIE, '')
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, 'Not signed in.')
    with _pool().connection(timeout=30) as conn:
        user = resolve_session(conn, token)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, 'Not signed in.')
    return AuthUser(id=user['id'], email=user['email'])


@router.post('/register', status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, request: Request, response: Response):
    _json_body_size(request)
    _rate_limit(request, 'register')
    try:
        with _pool().connection(timeout=30) as conn:
            user = create_user(conn, payload.email, payload.password, reserved_email=RESERVED_OWNER_EMAIL)
            conn.commit()
            _issue_session(response, conn, user['id'])
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except errors.UniqueViolation as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, 'An account with this email already exists.') from exc
    return {'message': 'Account created', 'user': {'id': user['id'], 'email': user['email']}}


@router.post('/login')
def login(payload: LoginRequest, request: Request, response: Response):
    _json_body_size(request)
    _rate_limit(request, 'login')
    try:
        with _pool().connection(timeout=30) as conn:
            user = authenticate_user(conn, payload.email, payload.password)
            if user is None:
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, 'Invalid email or password.')
            conn.commit()
            _issue_session(response, conn, user['id'])
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {'message': 'Signed in', 'user': {'id': user['id'], 'email': user['email']}}


@router.get('/me')
def me(user: AuthUser = Depends(current_user)):
    return {'user': user.model_dump()}


@router.post('/logout')
def logout(request: Request, response: Response, user: AuthUser = Depends(current_user)):
    _require_csrf(request)
    token = request.cookies.get(SESSION_COOKIE, '')
    with _pool().connection(timeout=30) as conn:
        revoke_session(conn, token)
        conn.commit()
    response.delete_cookie(SESSION_COOKIE, path='/')
    response.delete_cookie(CSRF_COOKIE, path='/')
    return {'message': 'Signed out'}
