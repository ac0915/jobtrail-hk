# Staged multi-user migrations

Do not execute these files against production yet. The multi-user release is incomplete.

## 001_multi_user_expand.sql

Adds jt_users, jt_sessions and a nullable jobs.user_id foreign key. Session storage accepts SHA-256 token digests, not raw browser tokens. Password storage accepts the existing scrypt format. Email syntax validation and password policy still belong in the application.

This is additive schema preparation, NOT data isolation. It contains no RLS policies and no application authorization. Existing records remain unassigned and the old global URL uniqueness rule remains in place. No data is deleted or assigned to a new registrant.

The script is transactional and intentionally not idempotent: rerunning a successful migration fails rather than silently accepting an unknown existing schema. A SQL client must stop on errors. With psql use ON_ERROR_STOP, for example on a disposable test database only:

```sh
psql "$TEST_DATABASE_URL" -v ON_ERROR_STOP=1 -f db/migrations/001_multi_user_expand.sql
```

Never put a connection string or password in source control. Do not run db/schema.sql as a substitute for this migration.

## Remaining cutover requirements

1. Inspect the actual target schema and all unique indexes/constraints; the checked-in schema is not proof of production structure.
2. Back up existing records and verify restoration. Test migrations with a restricted runtime role and separate migration credentials.
3. Provision the existing owner explicitly using the existing OWNER_EMAIL and OWNER_PASSWORD_HASH; never give old jobs to the first public registrant.
4. During controlled cutover, stop old-version writes, backfill all unassigned jobs to that owner, enforce jobs.user_id NOT NULL and replace global URL uniqueness with per-owner uniqueness.
5. Add and test application ownership filters, database policies, transaction-local identity and restricted role privileges before permitting other users.
6. Add registration, persistent session lookup/revocation/expiry, throttling and origin checks. Define email verification and recovery before public release.
7. Test cross-user reads/writes/deletes, duplicate URLs, imports, cover letters, logout, expiry and reused pool connections.
8. Plan rollback without dropping users or owned records. Do not revert to an unscoped single-owner API after other users have stored data.

Validation status: source-reviewed only. Not executed against PostgreSQL; database integration and migration/rollback tests are pending. No Render or Neon settings are changed by committing these files.
