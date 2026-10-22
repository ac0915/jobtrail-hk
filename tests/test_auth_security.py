"""Unit tests for the staged authentication primitives, not integration tests."""
import hashlib
import unittest
from app.auth_security import (
    hash_password, verify_password, validate_new_password,
    new_session_token, session_token_hash,
)


class AuthSecurityTests(unittest.TestCase):
    def test_password_boundaries(self):
        for size in (8, 20):
            self.assertEqual(validate_new_password("a" * size), "a" * size)
        for value in ("a" * 7, "a" * 21, "", None):
            with self.assertRaises(ValueError):
                validate_new_password(value)

    def test_password_whitespace_is_not_trimmed(self):
        password = " abcdefg "
        encoded = hash_password(password)
        self.assertTrue(verify_password(password, encoded))
        self.assertFalse(verify_password(password.strip(), encoded))

    def test_roundtrip_and_wrong_password(self):
        encoded = hash_password("correct-password")
        self.assertTrue(verify_password("correct-password", encoded))
        self.assertFalse(verify_password("incorrect-password", encoded))

    def test_random_salts(self):
        self.assertNotEqual(hash_password("password123"), hash_password("password123"))

    def test_existing_owner_hash_format(self):
        password = "legacy-owner-password-over-20-characters"
        salt = "0123456789abcdef0123456789abcdef"
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt),
                                n=16384, r=8, p=1, dklen=32).hex()
        self.assertTrue(verify_password(password, f"scrypt${salt}${digest}"))

    def test_malformed_hashes_fail_closed(self):
        for encoded in (None, "", "plaintext", "scrypt$x$y", "argon2$x$y",
                        "scrypt$" + "0" * 32 + "$" + "g" * 64):
            self.assertFalse(verify_password("password123", encoded))

    def test_invalid_password_inputs(self):
        encoded = hash_password("password123")
        for password in (None, "", "a" * 257):
            self.assertFalse(verify_password(password, encoded))

    def test_unicode_password(self):
        password = "測試密碼abcdefgh"
        self.assertTrue(verify_password(password, hash_password(password)))

    def test_session_tokens(self):
        first, second = new_session_token(), new_session_token()
        self.assertNotEqual(first, second)
        digest = session_token_hash(first)
        self.assertEqual(len(digest), 64)
        self.assertEqual(digest, session_token_hash(first))
        self.assertNotEqual(digest, first)
        self.assertNotEqual(digest, session_token_hash(second))

    def test_invalid_session_tokens(self):
        for token in (None, "", "x" * 42, "x" * 44, "!" * 43):
            with self.assertRaises(ValueError):
                session_token_hash(token)


if __name__ == "__main__":
    unittest.main()
