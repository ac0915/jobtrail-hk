# Multi-user upgrade: implementation checklist

Status: planning and partial source audit only. Registration and isolation are NOT implemented. Do not deploy this branch as a multi-user release yet.

## Verified findings

- app/jobs.py reads, updates and deletes public.jobs without an owner filter.
- check_duplicate searches all jobs and can disclose another user's job title, company and ID once registration is introduced.
- db/schema.sql defines jobs_url_unique on url globally. Replace it with a per-owner partial unique index in the actual migration.
- The checked-in fresh schema does not include cover_letter, although app/jobs.py selects it. Inspect all existing migrations and the deployed schema before changing tables.
- app/database.py uses a shared psycopg pool. Authenticated user context for RLS must be transaction-local and reset safely on pooled connections.

## Required implementation

- Audit personal.py, imports, cover-letter endpoints, frontend and tests before enabling registration.
- Add users and persistent, expiring server-side sessions; store password hashes and session-token hashes, not plaintext credentials.
- Preserve origin checks, secure HttpOnly cookies and login throttling; add registration throttling. Define email verification and password recovery scope explicitly.
- Derive owner identity from the authenticated session, never a client-supplied user_id.
- Scope every job read, insert, update, delete, duplicate check and related-resource operation to that owner.
- Add users.id references to owned rows. Backfill existing records to the explicitly provisioned owner, never to the first public registrant.
- Apply a unique partial index on (user_id, url) for nonblank URLs.
- Configure and test RLS with a restricted runtime database role; table owners and BYPASSRLS roles must not silently bypass the intended policy. Keep migration credentials separate.
- Set authenticated user context inside each database transaction, including sync endpoint execution; test pooled connection reuse across users.
- Keep secrets out of source control and frontend responses.

## Release gates

- Back up existing Neon data and verify restore before migration. Do not run a migration against production automatically.
- Test on a disposable database, not production. Inspect its actual schema before migration.
- A can create/list/read/update/delete A's jobs; B cannot read, modify or delete them by guessing IDs.
- A and B can each save the same URL, while duplicate URLs within one account are rejected.
- Anonymous requests are rejected; foreign resources return a non-disclosing response.
- Test related endpoints, malformed sessions, logout, expiry, restart persistence, rate limits and CSRF/origin checks.
- Verify existing owner records survive migration and appear only to the owner.
- Verify failed and repeated migrations do not leave partial state.
- Run the existing regression tests and new integration tests; report unrun tests explicitly.
- Review the complete code diff before merging to new, which is the deployed branch.

This checklist makes no changes to Render, Neon, runtime permissions or billing.
