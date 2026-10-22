# Disposable local browser testing

Keep the normal application configuration unchanged. These scripts use the confirmed local PostgreSQL server at 127.0.0.1:5432 and prompt for its postgres password.

## Automated checks

Run `python scripts/run_db_tests.py`. The integration suite now contains 18 tests. New checks cover independent accounts saving the same URL, rejecting duplicates inside one account, duplicate URL edits, and database-enforced uniqueness. Passing must be confirmed locally.

## Browser sandbox

Run `python scripts/run_browser_test.py` with the virtual environment active. It creates a random temporary database, installs the base schema, detail columns, and migrations 001 and 002, then starts main_ui:app at 127.0.0.1:8001 without reload. Multi-user mode is enabled only for the child process. No .env file is edited.

Open http://127.0.0.1:8001/login in a dedicated private window. Register first@example.com with a test-only 8–20 character password. Registration and login should redirect to My Jobs. Manually save a job with URL https://example.com/shared-job. A second save inside this account should be rejected.

Logout using the sidebar. Register second@example.com. Its list should start empty and it should be able to save the same URL. Each account must see only its own job. There is no email delivery or verification yet.

Use port 8001 throughout. Cookies on 127.0.0.1 can be shared across ports. Press Ctrl+C to stop the sandbox and delete its generated database; abrupt terminal termination can prevent cleanup. Do not enter real CVs or personal records.

## Migration safety and release blockers

Migration 002 is staged for reviewed multi-user cutover, not production execution now. It replaces the global URL index with per-user uniqueness plus a separate index for NULL-owner legacy rows. Existing records are not reassigned. After different users save the same URL, recreating the old global index requires data reconciliation. Disabling the feature flag is NOT a safe rollback or a supported public fallback: legacy mode has unscoped queries.

Email verification, owner provisioning/backfill, stronger production rate limiting, complete CSRF enforcement, and deployment checks still need work. These tests do not certify production security.
