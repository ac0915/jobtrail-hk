"""Mock-based storage tests. PostgreSQL integration is still required."""
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock
from app.accounts import normalize_email, create_user, authenticate_user, create_session, resolve_session, revoke_session, delete_expired_sessions
from app.auth_security import hash_password, session_token_hash, new_session_token


class AccountStorageTests(unittest.TestCase):
    def connection(self, row=None):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = row
        return conn, cur

    def test_email_normalization_and_rejection(self):
        self.assertEqual(normalize_email(" Person@Example.COM "), "person@example.com")
        for value in (None, "bad", "a@b", "a..b@example.com", ".a@example.com", "a@example.com\nInjected", "a@-example.com"):
            with self.assertRaises(ValueError):
                normalize_email(value)

    def test_create_user_hashes_password(self):
        conn, cur = self.connection((2, "friend@example.com"))
        user = create_user(conn, "Friend@example.com", "password123", reserved_email="owner@example.com")
        sql, params = cur.execute.call_args.args
        self.assertEqual(user, {"id": 2, "email": "friend@example.com"})
        self.assertIn("VALUES (%s, %s)", sql)
        self.assertEqual(params[0], "friend@example.com")
        self.assertTrue(params[1].startswith("scrypt$"))
        self.assertNotIn("password123", params[1])
        conn.commit.assert_not_called()

    def test_reserved_owner_cannot_register(self):
        conn, cur = self.connection()
        with self.assertRaises(ValueError):
            create_user(conn, "Owner@example.com", "password123", reserved_email="owner@example.com")
        cur.execute.assert_not_called()

    def test_authentication_and_disabled_account(self):
        encoded = hash_password("password123")
        verified_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        conn, cur = self.connection((2, "friend@example.com", encoded, True, verified_at))
        self.assertEqual(authenticate_user(conn, "friend@example.com", "password123"), {"id": 2, "email": "friend@example.com", "email_verified": True})
        self.assertIsNone(authenticate_user(conn, "friend@example.com", "incorrect123"))
        cur.fetchone.return_value = (2, "friend@example.com", encoded, True, None)
        self.assertEqual(authenticate_user(conn, "friend@example.com", "password123"), {"id": 2, "email": "friend@example.com", "email_verified": False})
        cur.fetchone.return_value = (2, "friend@example.com", encoded, False, verified_at)
        self.assertIsNone(authenticate_user(conn, "friend@example.com", "password123"))
        cur.fetchone.return_value = None
        self.assertIsNone(authenticate_user(conn, "missing@example.com", "password123"))

    def test_invalid_email_does_not_query(self):
        conn, cur = self.connection()
        self.assertIsNone(authenticate_user(conn, "invalid", "password123"))
        cur.execute.assert_not_called()

    def test_session_stores_digest_and_checks_active_user(self):
        conn, cur = self.connection((2,))
        token = create_session(conn, 2)
        sql, params = cur.execute.call_args.args
        self.assertEqual(params, (session_token_hash(token), 2))
        self.assertNotIn(token, params)
        self.assertIn("AND is_active", sql)
        self.assertIn("INTERVAL '12 hours'", sql)
        cur.fetchone.return_value = None
        with self.assertRaises(ValueError):
            create_session(conn, 99)

    def test_resolve_checks_expiry_and_active_user(self):
        conn, cur = self.connection((2, "friend@example.com", None))
        token = new_session_token()
        self.assertEqual(resolve_session(conn, token), {"id": 2, "email": "friend@example.com", "email_verified": False})
        sql, params = cur.execute.call_args.args
        self.assertEqual(params, (session_token_hash(token),))
        self.assertIn("s.expires_at > NOW()", sql)
        self.assertIn("u.is_active", sql)
        cur.fetchone.return_value = (2, "friend@example.com", "2026-01-01")
        self.assertEqual(resolve_session(conn, token), {"id": 2, "email": "friend@example.com", "email_verified": True})
        cur.fetchone.return_value = None
        self.assertIsNone(resolve_session(conn, token))

    def test_invalid_session_does_not_query(self):
        conn, cur = self.connection()
        self.assertIsNone(resolve_session(conn, "bad"))
        revoke_session(conn, "bad")
        cur.execute.assert_not_called()

    def test_revoke_uses_digest(self):
        conn, cur = self.connection()
        token = new_session_token()
        revoke_session(conn, token)
        self.assertEqual(cur.execute.call_args.args, ("DELETE FROM public.jt_sessions WHERE token_hash = %s", (session_token_hash(token),)))

    def test_expired_cleanup(self):
        conn, cur = self.connection()
        delete_expired_sessions(conn)
        cur.execute.assert_called_once_with("DELETE FROM public.jt_sessions WHERE expires_at <= NOW()")


if __name__ == "__main__":
    unittest.main()
