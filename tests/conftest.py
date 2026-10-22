"""Each integration test owns a fresh, randomly named local database."""
import os
import secrets
from pathlib import Path

import pytest
from psycopg import connect, sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_KEYS = {'host', 'port', 'dbname', 'user', 'password', 'sslmode', 'connect_timeout'}


def local_admin_parameters(value):
    try:
        params = conninfo_to_dict(value)
    except Exception:
        raise ValueError('Invalid test connection settings; credentials omitted.') from None
    if set(params) - ALLOWED_KEYS:
        raise ValueError('Unsupported test connection settings.')
    if params.get('host') != '127.0.0.1' or params.get('port') != '5432':
        raise ValueError('Tests require explicit host=127.0.0.1 port=5432.')
    if params.get('dbname') != 'postgres' or not params.get('user'):
        raise ValueError('Use the local postgres maintenance database and an explicit user.')
    params.update(sslmode='disable', connect_timeout='5')
    return params


@pytest.fixture()
def database_url():
    value = os.environ.get('TEST_DATABASE_URL', '').strip()
    if not value:
        pytest.skip('TEST_DATABASE_URL is unset; PostgreSQL integration tests skipped.')
    admin = local_admin_parameters(value)
    name = 'jobtrail_test_' + secrets.token_hex(12)
    with connect(**admin, autocommit=True) as conn:
        conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    try:
        yield make_conninfo(**{**admin, 'dbname': name})
    finally:
        with connect(**admin, autocommit=True) as conn:
            conn.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))


@pytest.fixture()
def db(database_url):
    with connect(database_url, autocommit=True) as conn:
        conn.execute((ROOT / 'db/schema.sql').read_text(encoding='utf-8'))
        conn.execute((ROOT / 'db/migrations/001_multi_user_expand.sql').read_text(encoding='utf-8'))
    with connect(database_url) as conn:
        try:
            yield conn
        finally:
            conn.rollback()
