# Disposable local browser testing

Keep the normal application configuration unchanged. These scripts use the confirmed local PostgreSQL server at 127.0.0.1:5432 and prompt for its postgres password. Do not use a production password.

## Automated checks

Run `python scripts/run_db_tests.py`. The integration suite now contains 15 tests, including four job-isolation tests. Tests are not considered passed until executed locally.

## Browser sandbox

Run `python scripts/run_browser_test.py` from the project directory with the virtual environment active. This creates a new randomly named database, installs the base schema, required detail columns and staged multi-user migration, and starts `main_ui:app` on 127.0.0.1:8001 without reload. It enables multi-user mode only in that child process. No .env file is edited.

Open http://127.0.0.1:8001/login. Register first@example.com using a test-only password of 8–20 characters. There is no email delivery or ownership verification yet. Create a job without a URL, logout, register second@example.com, and verify that its job list is empty. Login again as the first account and verify its job remains. Use port 8001 throughout; cookies on 127.0.0.1 may also be shared with other local ports, so prefer a dedicated private browser window.

Press Ctrl+C to stop the server and delete its generated database. Closing or killing the terminal abruptly can prevent cleanup and leave a disposable database behind. Do not enter real CVs or sensitive personal information.

## Known release blockers

The old global URL-unique index still prevents different users from saving the same nonblank URL. This sandbox does not change it. The browser test uses blank URLs until a reviewed per-user-index migration is added.

This is not a production release. Email verification, owner provisioning/backfill, stronger production rate limiting, and complete CSRF enforcement still need work. The tests here validate job isolation, not overall production security.
