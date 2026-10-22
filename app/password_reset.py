"""Single-use password reset tokens. Callers own transactions."""
from __future__ import annotations

from app.accounts import normalize_email
from app.auth_security import hash_password, new_session_token, session_token_hash


def create_password_reset_token(conn, email: str):
    """Create a reset token only when the account exists. Return raw token or None."""
    try:
        email = normalize_email(email)
    except ValueError:
        return None

    raw_token = new_session_token()
    token_hash = session_token_hash(raw_token)

    with conn.cursor() as cur:
        cur.execute("SELECT id FROM public.jt_users WHERE email = %s AND is_active", (email,))
        row = cur.fetchone()
        if row is None:
            return None

        user_id = row[0]
        cur.execute(
            """
            DELETE FROM public.jt_email_tokens
            WHERE user_id = %s
              AND purpose = 'password_reset'
              AND used_at IS NULL
            """,
            (user_id,),
        )
        cur.execute(
            """
            INSERT INTO public.jt_email_tokens
                (token_hash, user_id, purpose, expires_at)
            VALUES (%s, %s, 'password_reset', NOW() + INTERVAL '1 hour')
            """,
            (token_hash, user_id),
        )

    return raw_token


def reset_password(conn, raw_token: str, new_password: str):
    """Consume a valid reset token, change the password, and revoke sessions."""
    if not isinstance(new_password, str) or not 8 <= len(new_password) <= 20:
        raise ValueError("Password must be 8 to 20 characters.")

    try:
        token_hash = session_token_hash(raw_token)
    except ValueError:
        raise ValueError("Invalid or expired reset link.") from None

    encoded = hash_password(new_password)

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE public.jt_email_tokens
            SET used_at = NOW()
            WHERE token_hash = %s
              AND purpose = 'password_reset'
              AND used_at IS NULL
              AND expires_at > NOW()
            RETURNING user_id
            """,
            (token_hash,),
        )
        token_row = cur.fetchone()
        if token_row is None:
            raise ValueError("Invalid or expired reset link.")

        user_id = token_row[0]
        cur.execute(
            """
            UPDATE public.jt_users
            SET password_hash = %s
            WHERE id = %s AND is_active
            RETURNING email
            """,
            (encoded, user_id),
        )
        user_row = cur.fetchone()
        if user_row is None:
            raise ValueError("Invalid or expired reset link.")

        cur.execute("DELETE FROM public.jt_sessions WHERE user_id = %s", (user_id,))

    return {"id": user_id, "email": user_row[0]}
