"""Create and drop only a newly generated loopback sandbox database."""
from contextlib import contextmanager
from pathlib import Path
import secrets

from psycopg import connect, sql
from psycopg.conninfo import make_conninfo

ROOT = Path(__file__).resolve().parents[1]
DETAIL_COLUMNS = 'ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS description TEXT, ADD COLUMN IF NOT EXISTS cover_letter TEXT'


@contextmanager
def sandbox(password):
    params = dict(host='127.0.0.1', hostaddr='127.0.0.1', port=5432, dbname='postgres', user='postgres', password=password, sslmode='disable', connect_timeout=5)
    name = 'jobtrail_browser_' + secrets.token_hex(12)
    with connect(**params, autocommit=True) as conn:
        conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    try:
        connection = make_conninfo(**{**params, 'dbname': name})
        with connect(connection, autocommit=True) as conn:
            conn.execute((ROOT / 'db/schema.sql').read_text(encoding='utf-8'))
            conn.execute(DETAIL_COLUMNS)
            conn.execute((ROOT / 'db/migrations/001_multi_user_expand.sql').read_text(encoding='utf-8'))
        yield connection
    finally:
        with connect(**params, autocommit=True) as conn:
            conn.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
