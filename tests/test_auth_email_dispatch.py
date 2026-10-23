"""Regression tests for auth email dispatch without a real DB or email service."""
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app import auth_routes as routes


def run_endpoint(endpoint, row=None, token="A" * 43, delivered=True):
    events = []
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = row
    conn.commit.side_effect = lambda: events.append("commit")
    pool = MagicMock()

    @contextmanager
    def connection(**kwargs):
        events.append("acquire")
        try:
            yield conn
        finally:
            events.append("release")

    pool.connection.side_effect = connection

    def send(*args):
        assert events[-1] == "release"
        events.append("send")
        return {"delivered": delivered, "provider": "test"}

    payload = SimpleNamespace(email="Friend@Example.com", password="password123")
    with (
        patch.object(routes, "_json_body_size"),
        patch.object(routes, "_rate_limit"),
        patch.object(routes, "_pool", return_value=pool),
        patch.object(routes, "create_user", return_value={"id": 2, "email": "friend@example.com"}),
        patch.object(routes, "create_verification_token", return_value=token) as verification,
        patch.object(routes, "create_password_reset_token", return_value=token) as reset,
        patch.object(routes, "_send_email", side_effect=send) as dispatch,
    ):
        args = (payload, MagicMock(), MagicMock()) if endpoint == "register" else (payload, MagicMock())
        result = getattr(routes, endpoint)(*args)
    return SimpleNamespace(events=events, conn=conn, cursor=cursor, verification=verification,
                           reset=reset, dispatch=dispatch, result=result)


def test_resend_uses_real_column_tuple_rows_and_normalized_email():
    case = run_endpoint("resend_verification", row=(2, "friend@example.com", None))
    sql, params = case.cursor.execute.call_args.args
    assert "email_verified_at" in sql
    assert "AND is_active" in sql
    assert params == ("friend@example.com",)
    case.verification.assert_called_once_with(case.conn, 2)
    case.dispatch.assert_called_once_with(routes.send_verification_email, "friend@example.com", "A" * 43)
    assert case.events == ["acquire", "commit", "release", "send"]


def test_resend_missing_account_does_not_send():
    case = run_endpoint("resend_verification")
    case.verification.assert_not_called()
    case.dispatch.assert_not_called()
    assert case.events == ["acquire", "release"]


def test_resend_verified_account_does_not_send():
    case = run_endpoint("resend_verification", row=(2, "friend@example.com", datetime.now(timezone.utc)))
    case.verification.assert_not_called()
    case.dispatch.assert_not_called()


def test_resend_response_does_not_disclose_account_state():
    missing = run_endpoint("resend_verification")
    unverified = run_endpoint("resend_verification", row=(2, "friend@example.com", None))
    failed = run_endpoint("resend_verification", row=(2, "friend@example.com", None), delivered=False)
    assert missing.result == unverified.result == failed.result


def test_register_releases_connection_before_send():
    case = run_endpoint("register")
    assert case.events == ["acquire", "commit", "commit", "release", "send"]
    assert "Check your email" in case.result["message"]


def test_register_reports_delivery_failure():
    case = run_endpoint("register", delivered=False)
    assert "could not be sent" in case.result["message"]


def test_forgot_password_normalizes_recipient_and_releases_connection():
    case = run_endpoint("forgot_password")
    case.reset.assert_called_once_with(case.conn, "friend@example.com")
    case.dispatch.assert_called_once_with(routes.send_password_reset_email, "friend@example.com", "A" * 43)
    assert case.events == ["acquire", "commit", "release", "send"]


def test_forgot_password_unknown_account_does_not_send():
    case = run_endpoint("forgot_password", token=None)
    case.dispatch.assert_not_called()
    assert case.events == ["acquire", "commit", "release"]
