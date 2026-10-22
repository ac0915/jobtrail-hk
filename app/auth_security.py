"""Authentication primitives; no routes or database changes on import."""
import hashlib
import hmac
import re
import secrets


def validate_new_password(password: str) -> str:
    """Preserve the requested 8-20 character registration policy."""
    if not isinstance(password, str) or not 8 <= len(password) <= 20:
        raise ValueError("Use 8-20 characters.")
    return password


def hash_password(password: str) -> str:
    validate_new_password(password)
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt),
                            n=16384, r=8, p=1, dklen=32).hex()
    return f"scrypt${salt}${digest}"


def verify_password(password: str, encoded: str) -> bool:
    """Accept existing personal.py hashes, including legacy long passwords."""
    if not isinstance(password, str) or not 1 <= len(password) <= 256:
        return False
    if not isinstance(encoded, str):
        return False
    if not re.fullmatch(r"scrypt\$[0-9a-f]{32}\$[0-9a-f]{64}", encoded):
        return False
    _, salt, expected = encoded.split("$")
    actual = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt),
                            n=16384, r=8, p=1, dklen=32).hex()
    return hmac.compare_digest(actual, expected)


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def session_token_hash(token: str) -> str:
    """Only this digest, never the raw cookie token, belongs in session storage."""
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        raise ValueError("Invalid session token.")
    return hashlib.sha256(token.encode("ascii")).hexdigest()
