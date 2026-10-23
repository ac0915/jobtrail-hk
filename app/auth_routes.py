"""Authentication endpoints, wired only when multi-user mode is enabled."""
from __future__ import annotations

import logging
import os
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from psycopg import errors
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.accounts import authenticate_user, create_session, create_user, resolve_session, revoke_session
from app.auth_limits import AttemptLimiter, RateLimited
from app.database import get_pool
from app.email import send_password_reset_email, send_verification_email
from app.email_verification import create_verification_token, verify_email_token
from app.password_reset import create_password_reset_token, reset_password

logger = logging.getLogger(__name__)

SESSION_COOKIE = "jt_session"
CSRF_COOKIE = "jt_csrf"
CSRF_HEADER = "X-CSRF-Token"
RESERVED_OWNER_EMAIL = "owner@example.com"
MAX_BODY_BYTES = 4096
MAX_ATTEMPTS = 5
ATTEMPT_WINDOW_SECONDS = 900


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=20)

    @field_validator("email")
    @classmethod
    def strip_email(cls, value: EmailStr) -> EmailStr:
        return value.strip()


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def strip_email(cls, value: EmailStr) -> EmailStr:
        return value.strip()


class VerifyEmailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=32, max_length=128)


class ResendVerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr = Field(min_length=3, max_length=254)

    @field_validator("email")
    @classmethod
    def strip_email(cls, value: EmailStr) -> EmailStr:
        return value.strip()


class ForgotPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr = Field(min_length=3, max_length=254)

    @field_validator("email")
    @classmethod
    def strip_email(cls, value: EmailStr) -> EmailStr:
        return value.strip()


class ResetPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=32, max_length=128)
    password: str = Field(min_length=8, max_length=20)


class AuthUser(BaseModel):
    id: int
    email: str
    email_verified: bool = False


router = APIRouter(prefix="/auth", tags=["Authentication"])
_limiter = AttemptLimiter(limit=MAX_ATTEMPTS, window=ATTEMPT_WINDOW_SECONDS)
_attempts = _limiter.attempts


def _client_key(request: Request, action: str):
    return (request.client.host if request.client else "unknown"), action


def _rate_limit(request: Request, action: str) -> None:
    try:
        _limiter.check(_client_key(request, action))
    except RateLimited as exc:
        raise HTTPException(429, "Too many attempts. Try again later.", headers={"Retry-After": str(exc.retry_after)}) from None


def _json_body_size(request: Request) -> None:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Request body too large.")


def _pool() -> ConnectionPool:
    return get_pool()


def _issue_session(response: Response, conn, user_id: int) -> None:
    token = create_session(conn, user_id)
    csrf = os.urandom(24).hex()
    secure = os.getenv("APP_ENV", "development") == "production"
    response.set_cookie(SESSION_COOKIE, token, max_age=12 * 60 * 60, httponly=True, secure=secure, samesite="lax", path="/")
    response.set_cookie(CSRF_COOKIE, csrf, max_age=12 * 60 * 60, httponly=False, secure=secure, samesite="lax", path="/")


def _send_email(message, email: str, raw_token: str) -> dict:
    try:
        return message(email, raw_token)
    except Exception:
        logger.exception("Could not send email to %s.", email)
        return {"delivered": False, "provider": "error"}


def _require_csrf(request: Request) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    cookie = request.cookies.get(CSRF_COOKIE, "")
    header = request.headers.get(CSRF_HEADER, "")
    if not cookie or not header or not secrets_compare_digest(cookie, header):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid CSRF token.")


def secrets_compare_digest(left: str, right: str) -> bool:
    import hmac
    return hmac.compare_digest(left.encode("ascii", "ignore"), right.encode("ascii", "ignore"))


def current_user(request: Request) -> AuthUser:
    token = request.cookies.get(SESSION_COOKIE, "")
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in.")
    with _pool().connection(timeout=30) as conn:
        user = resolve_session(conn, token)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in.")
    return AuthUser(id=user["id"], email=user["email"], email_verified=user["email_verified"])


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, request: Request, response: Response):
    _json_body_size(request)
    _rate_limit(request, "register")
    try:
        with _pool().connection(timeout=30) as conn:
            user = create_user(conn, payload.email, payload.password, reserved_email=RESERVED_OWNER_EMAIL)
            conn.commit()
            raw_token = create_verification_token(conn, user["id"])
            conn.commit()
            delivery = _send_email(send_verification_email, user["email"], raw_token)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except errors.UniqueViolation as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists.") from exc
    if delivery.get("delivered"):
        message_text = "Account created. Check your email and click the verification link."
    else:
        message_text = "Account created, but the verification email could not be sent. Please contact support."
    return {"message": message_text, "user": {"id": user["id"], "email": user["email"]}}


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response):
    _json_body_size(request)
    _rate_limit(request, "login")
    try:
        with _pool().connection(timeout=30) as conn:
            user = authenticate_user(conn, payload.email, payload.password)
            if user is None:
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password.")
            if not user.get("email_verified", False):
                raise HTTPException(status.HTTP_403_FORBIDDEN, "Please verify your email address before signing in.")
            conn.commit()
            _issue_session(response, conn, user["id"])
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"message": "Signed in", "user": {"id": user["id"], "email": user["email"]}}


@router.get("/me")
def me(user: AuthUser = Depends(current_user)):
    return {"user": user.model_dump()}


@router.post("/verify-email")
def verify_email(payload: VerifyEmailRequest, request: Request):
    _json_body_size(request)
    _rate_limit(request, "verify_email")
    with _pool().connection(timeout=30) as conn:
        user = verify_email_token(conn, payload.token)
        if user is None:
            conn.rollback()
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired verification link.")
        conn.commit()
    return {"message": "Email verified", "user": {"id": user["id"], "email": user["email"]}}


@router.post("/resend-verification")
def resend_verification(payload: ResendVerificationRequest, request: Request):
    _json_body_size(request)
    _rate_limit(request, "resend_verification")
    with _pool().connection(timeout=30) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, email, email_verified FROM public.jt_users WHERE email = %s",
                (payload.email,),
            )
            user = cur.fetchone()
            if user is not None and not user["email_verified"]:
                raw_token = create_verification_token(conn, user["id"])
                conn.commit()
                _send_email(send_verification_email, user["email"], raw_token)
    return {"message": "If that email has an unverified account, a verification link has been sent."}


@router.post("/forgot-password")
def forgot_password(payload: ForgotPasswordRequest, request: Request):
    _json_body_size(request)
    _rate_limit(request, "forgot_password")
    with _pool().connection(timeout=30) as conn:
        raw_token = create_password_reset_token(conn, payload.email)
        conn.commit()
        if raw_token is not None:
            _send_email(send_password_reset_email, payload.email, raw_token)
    return {"message": "If that email has an account, a reset link has been sent."}


@router.post("/reset-password")
def reset_password_endpoint(payload: ResetPasswordRequest, request: Request):
    _json_body_size(request)
    _rate_limit(request, "reset_password")
    try:
        with _pool().connection(timeout=30) as conn:
            user = reset_password(conn, payload.token, payload.password)
            conn.commit()
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"message": "Password updated. Please sign in again.", "user": {"id": user["id"], "email": user["email"]}}


@router.post("/logout")
def logout(request: Request, response: Response, user: AuthUser = Depends(current_user)):
    _require_csrf(request)
    token = request.cookies.get(SESSION_COOKIE, "")
    with _pool().connection(timeout=30) as conn:
        revoke_session(conn, token)
        conn.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return {"message": "Signed out"}
