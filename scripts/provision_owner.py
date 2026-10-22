"""Assign legacy unowned jobs to the owner account.

Usage:
  python scripts/provision_owner.py --dry-run
  python scripts/provision_owner.py --apply

Required environment:
  DATABASE_URL   PostgreSQL connection string for the real database
  OWNER_EMAIL    Existing owner account email
"""
from __future__ import annotations

import argparse
import os
import sys

from psycopg import connect


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true', help='Show what would change without updating jobs')
    parser.add_argument('--apply', action='store_true', help='Assign unowned jobs to OWNER_EMAIL')
    args = parser.parse_args()

    if args.dry_run == args.apply:
        parser.error('Choose exactly one of --dry-run or --apply.')

    database_url = os.getenv('DATABASE_URL', '').strip()
    owner_email = os.getenv('OWNER_EMAIL', '').strip().lower()

    if not database_url:
        print('DATABASE_URL is required.', file=sys.stderr)
        return 2
    if not owner_email:
        print('OWNER_EMAIL is required.', file=sys.stderr)
        return 2

    with connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT id, email, email_verified_at FROM public.jt_users WHERE email = %s', (owner_email,))
            owner = cur.fetchone()
            if owner is None:
                print(f'Owner account not found: {owner_email}', file=sys.stderr)
                print('Register the owner account first, then run this script again.', file=sys.stderr)
                return 1

            cur.execute('SELECT COUNT(*) FROM public.jobs WHERE user_id IS NULL')
            unowned_count = cur.fetchone()[0]
            print(f'Owner: {owner[1]} (id {owner[0]})')
            print(f'Unowned jobs: {unowned_count}')

            if args.dry_run:
                print('Dry run complete. No jobs were changed.')
                return 0

            if unowned_count:
                cur.execute(
                    """
                    UPDATE public.jobs
                    SET user_id = %s
                    WHERE user_id IS NULL
                    """,
                    (owner[0],),
                )
                print(f'Assigned {cur.rowcount} job(s) to {owner_email}.')
            else:
                print('No unowned jobs to assign.')

        conn.commit()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
