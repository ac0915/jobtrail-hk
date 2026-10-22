"""Single-use email verification tokens. Callers own transactions."""
from __future__ import annotations

from app.auth_security import new_session_token, session_token_hash


def create_verification_token(conn, user_id: int) -> str:
    """Create a raw token, invalidating prior unused verification tokens."""
    raw_token = new_session_token()
    token_hash = session_token_hash(raw_token)
    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM public.jt_email_tokens
            WHERE user_id = %s
              AND purpose = 'email_verification'
              AND used_at IS NULL
            """,
            (user_id,),
        )
        cur.execute(
            """
            INSERT INTO public.jt_email_tokens
                (token_hash, user_id, purpose, expires_at)
            VALUES (%s, %s, 'email_verification', NOW() + INTERVAL '24 hours')
            """,
            (token_hash, user_id),
        )
    return raw_token


def verify_email_token(conn, raw_token: str):
    """Consume a valid token and mark its user verified. Return user info or None."""
    try:
        token_hash = session_token_hash(raw_token)
    except ValueError:
        return None

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE public.jt_email_tokens
            SET used_at = NOW()
            WHERE token_hash = %s
              AND purpose = 'email_verification'
              AND used_at IS NULL
              AND expires_at > NOW()
            RETURNING user_id
            """,
            (token_hash,),
        )
        token_row = cur.fetchone()
        if token_row is None:
            return None

        user_id = token_row[0]
        cur.execute(
            """
            UPDATE public.jt_users
            SET email_verified_at = COALESCE(email_verified_at, NOW())
            WHERE id = %s
            RETURNING id, email
            """,
            (user_id,),
        )
        user_row = cur.fetchone()

    return {"id": user_row[0], "email": user_row[1]} if user_row else None
