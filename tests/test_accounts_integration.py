"""Real storage tests. Run with python scripts/run_db_tests.py."""
import pytest
from psycopg import errors
from app.accounts import authenticate_user, create_user, create_session, resolve_session, revoke_session, delete_expired_sessions
from app.auth_security import session_token_hash

pytestmark = pytest.mark.integration


def user(db):
    result = create_user(db, 'Friend@example.com', 'password123', reserved_email='owner@example.com')
    db.commit()
    return result


def session_account(account):
    return {
        'id': account['id'],
        'email': account['email'],
        'email_verified': False,
    }


def expire(db, token):
    db.execute(
        "UPDATE public.jt_sessions SET created_at = NOW() - INTERVAL '2 hours', expires_at = NOW() - INTERVAL '1 hour' WHERE token_hash = %s",
        (session_token_hash(token),),
    )
    db.commit()


def test_register_login_and_session_round_trip(db):
    account = user(db)
    assert account['email'] == 'friend@example.com'
    assert authenticate_user(db, ' FRIEND@EXAMPLE.COM ', 'password123') == account
    token = create_session(db, account['id'])
    db.commit()
    assert resolve_session(db, token) == session_account(account)
    row = db.execute('SELECT token_hash FROM public.jt_sessions').fetchone()
    assert row[0] == session_token_hash(token)
    assert row[0] != token


def test_duplicate_email_is_rejected_by_database(db):
    user(db)
    with pytest.raises(errors.UniqueViolation):
        create_user(db, 'FRIEND@example.com', 'password123', reserved_email='owner@example.com')
    db.rollback()


def test_wrong_password_and_disabled_account_fail(db):
    account = user(db)
    assert authenticate_user(db, account['email'], 'incorrect123') is None
    token = create_session(db, account['id'])
    db.commit()
    db.execute('UPDATE public.jt_users SET is_active = FALSE WHERE id = %s', (account['id'],))
    db.commit()
    assert authenticate_user(db, account['email'], 'password123') is None
    assert resolve_session(db, token) is None


def test_expired_session_cannot_resolve(db):
    account = user(db)
    token = create_session(db, account['id'])
    db.commit()
    expire(db, token)
    assert resolve_session(db, token) is None


def test_logout_and_expiry_cleanup(db):
    account = user(db)
    active = create_session(db, account['id'])
    expired = create_session(db, account['id'])
    db.commit()
    expire(db, expired)
    delete_expired_sessions(db)
    db.commit()
    assert resolve_session(db, active) == session_account(account)
    assert resolve_session(db, expired) is None
    revoke_session(db, active)
    db.commit()
    assert resolve_session(db, active) is None
    assert db.execute('SELECT COUNT(*) FROM public.jt_sessions').fetchone()[0] == 0


def test_owner_address_is_reserved(db):
    with pytest.raises(ValueError):
        create_user(db, 'owner@example.com', 'password123', reserved_email='owner@example.com')
    assert db.execute('SELECT COUNT(*) FROM public.jt_users').fetchone()[0] == 0


def test_jobs_user_id_foreign_key(db):
    account = user(db)
    db.execute('INSERT INTO public.jobs (title, company, user_id) VALUES (%s, %s, %s)', ('Engineer', 'Example', account['id']))
    db.commit()
    with pytest.raises(errors.ForeignKeyViolation):
        db.execute('INSERT INTO public.jobs (title, company, user_id) VALUES (%s, %s, %s)', ('Engineer', 'Example', -1))
    db.rollback()
    assert db.execute('SELECT user_id FROM public.jobs').fetchone()[0] == account['id']


def test_invalid_hash_format_is_rejected(db):
    with pytest.raises(errors.CheckViolation):
        db.execute('INSERT INTO public.jt_users (email, password_hash) VALUES (%s, %s)', ('bad@example.com', 'invalid'))
    db.rollback()


def test_caller_can_roll_back_registration(db):
    create_user(db, 'rollback@example.com', 'password123', reserved_email='owner@example.com')
    db.rollback()
    assert db.execute('SELECT COUNT(*) FROM public.jt_users').fetchone()[0] == 0
