"""Gmail transport tests; no real credentials or network traffic."""
import base64
import os
import unittest
from email import policy
from email.parser import BytesParser
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from app import email as mail


class GmailEmailTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"GMAIL_TOKEN_FILE": "private-token.json", "APP_BASE_URL": "https://jobs.example.com"}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        mail._load_credentials.cache_clear()
        self.addCleanup(mail._load_credentials.cache_clear)

    def send(self):
        return mail.send_verification_email("recipient@example.com", "A" * 43)

    def test_success_preserves_multipart_and_verification_url(self):
        credentials = SimpleNamespace(valid=True, token="fake-access")
        with patch.object(mail, "_load_credentials", return_value=credentials), patch.object(mail.httpx, "post", return_value=httpx.Response(200, json={"id": "message-1"})) as post:
            result = self.send()
        self.assertEqual(result, {"delivered": True, "provider": "gmail_api", "message_id": "message-1"})
        self.assertEqual(post.call_args.args, (mail.GMAIL_SEND_URL,))
        self.assertEqual(post.call_args.kwargs["timeout"], 20)
        self.assertFalse(post.call_args.kwargs["follow_redirects"])
        message = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(post.call_args.kwargs["json"]["raw"]))
        self.assertEqual(message["To"], "recipient@example.com")
        self.assertEqual(message["Subject"], "Verify your JobTrail HK email")
        self.assertEqual(message.get_content_type(), "multipart/alternative")
        for part in message.iter_parts():
            self.assertIn("https://jobs.example.com/verify-email?token=", part.get_content())

    def test_refresh_before_send(self):
        credentials = SimpleNamespace(valid=False, token=None)
        def refresh(value):
            value.valid = True
            value.token = "refreshed-access"
        with patch.object(mail, "_load_credentials", return_value=credentials), patch.object(mail, "_refresh_credentials", side_effect=refresh) as refresh_mock, patch.object(mail.httpx, "post", return_value=httpx.Response(200, json={"id": "message-2"})) as post:
            self.send()
        refresh_mock.assert_called_once_with(credentials)
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer refreshed-access")

    def test_missing_or_ambiguous_configuration_never_calls_network(self):
        for configuration in ({}, {"GMAIL_TOKEN_FILE": "a", "GMAIL_TOKEN_JSON": "b"}):
            with self.subTest(configuration=configuration), patch.dict(os.environ, configuration, clear=True), patch.object(mail.httpx, "post") as post:
                with self.assertRaises(RuntimeError):
                    self.send()
                post.assert_not_called()

    def test_refresh_failure_is_sanitized_and_does_not_send(self):
        credentials = SimpleNamespace(valid=False, token=None)
        with patch.object(mail, "_load_credentials", return_value=credentials), patch.object(mail, "_refresh_credentials", side_effect=RuntimeError("PRIVATE-TOKEN")), patch.object(mail.httpx, "post") as post:
            with self.assertRaises(RuntimeError) as error:
                self.send()
        self.assertNotIn("PRIVATE-TOKEN", str(error.exception))
        post.assert_not_called()

    def test_api_errors_do_not_return_success_or_retry(self):
        for code in (401, 403, 429, 500):
            with self.subTest(code=code), patch.object(mail, "_load_credentials", return_value=SimpleNamespace(valid=True, token="fake")), patch.object(mail.httpx, "post", return_value=httpx.Response(code, text="PRIVATE-RESPONSE")) as post:
                with self.assertRaises(RuntimeError) as error:
                    self.send()
                self.assertNotIn("PRIVATE-RESPONSE", str(error.exception))
                self.assertIn(str(code), str(error.exception))
                post.assert_called_once()

    def test_network_timeout_does_not_retry(self):
        with patch.object(mail, "_load_credentials", return_value=SimpleNamespace(valid=True, token="fake")), patch.object(mail.httpx, "post", side_effect=httpx.ReadTimeout("private")) as post:
            with self.assertRaises(RuntimeError):
                self.send()
        post.assert_called_once()

    def test_missing_message_id_is_not_success(self):
        with patch.object(mail, "_load_credentials", return_value=SimpleNamespace(valid=True, token="fake")), patch.object(mail.httpx, "post", return_value=httpx.Response(200, json={})):
            with self.assertRaises(RuntimeError):
                self.send()

    def test_reset_template_uses_same_transport(self):
        with patch.object(mail, "_send", return_value={"delivered": True}) as send:
            mail.send_password_reset_email("recipient@example.com", "A" * 43)
        self.assertIn("/reset-password?token=", send.call_args.args[2])
        self.assertIn("1 hour", send.call_args.args[2])

    def test_production_requires_https_base_url(self):
        for value in ("", "http://jobs.example.com"):
            with self.subTest(value=value), patch.dict(os.environ, {"APP_ENV": "production", "APP_BASE_URL": value}):
                with self.assertRaises(ValueError):
                    mail._base_url(None)

    def test_rejects_link_formatted_recipient(self):
        with self.assertRaises(ValueError):
            mail._send("[recipient@example.com](mailto:recipient@example.com)", "Subject", "Text", "<p>Text</p>")
