"""Staged account storage. Caller owns transactions; not connected to routes yet."""
import re
from app.auth_security import hash_password, verify_password, new_session_token, session_token_hash

# Match the cost of a normal password check when the account does not exist.
_DUMMY_HASH = hash_password("dummy-password")


def normalize_email(value):
    if not isinstance(value, str):
        raise ValueError("Invalid email.")
    email = value.strip().lower()
    if len(email) > 254 or not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:[.][a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+", email):
        raise ValueError("Invalid email.")
    local = email.split("@", 1)[0]
    if len(local) > 64 or local.startswith(".") or local.endswith(".") or ".." in local:
        raise ValueError("Invalid email.")
    return email


def create_user(conn, email, password, *, reserved_email):
    """Reserve the legacy owner address until explicit owner provisioning is complete.

    UniqueViolation is intentionally left to the caller's transaction boundary.
    This helper does not verify email ownership or grant access to legacy jobs.
    """
    email = normalize_email(email)
    if email == normalize_email(reserved_email):
        raise ValueError("This address is reserved for the existing owner.")
    encoded = hash_password(password)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO public.jt_users (email, password_hash) VALUES (%s, %s) RETURNING id, email", (email, encoded))
        row = cur.fetchone()
    return {"id": row[0], "email": row[1]}


def authenticate_user(conn, email, password):
    try:
        email = normalize_email(email)
    except ValueError:
        verify_password(password, _DUMMY_HASH)
        return None
    with conn.cursor() as cur:
        cur.execute("SELECT id, email, password_hash, is_active FROM public.jt_users WHERE email = %s", (email,))
        row = cur.fetchone()
    valid = verify_password(password, row[2] if row else _DUMMY_HASH)
    if not row or not valid or not row[3]:
        return None
    return {"id": row[0], "email": row[1]}


def create_session(conn, user_id):
    """Return a raw token only to the caller setting the browser cookie."""
    token = new_session_token()
    with conn.cursor() as cur:
        cur.execute("INSERT INTO public.jt_sessions (token_hash, user_id, expires_at) SELECT %s, id, NOW() + INTERVAL '12 hours' FROM public.jt_users WHERE id = %s AND is_active RETURNING user_id", (session_token_hash(token), user_id))
        if cur.fetchone() is None:
            raise ValueError("Account unavailable.")
    return token


def resolve_session(conn, token):
    try:
        digest = session_token_hash(token)
    except ValueError:
        return None
    with conn.cursor() as cur:
        cur.execute("SELECT u.id, u.email FROM public.jt_sessions s JOIN public.jt_users u ON u.id = s.user_id WHERE s.token_hash = %s AND s.expires_at > NOW() AND u.is_active", (digest,))
        row = cur.fetchone()
    return {"id": row[0], "email": row[1]} if row else None


def revoke_session(conn, token):
    try:
        digest = session_token_hash(token)
    except ValueError:
        return
    with conn.cursor() as cur:
        cur.execute("DELETE FROM public.jt_sessions WHERE token_hash = %s", (digest,))


def delete_expired_sessions(conn):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM public.jt_sessions WHERE expires_at <= NOW()")
