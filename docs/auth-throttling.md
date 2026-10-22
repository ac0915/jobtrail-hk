# Authentication throttling

This patch limits validated login and registration requests to five per client address per action per 15 minutes. Both successful and failed requests count; successful authentication no longer erases the counter. HTTP 429 includes Retry-After in seconds.

State is bounded to 2048 client/action buckets, protected by a thread lock. On capacity exhaustion, new keys are denied until a bucket expires rather than evicting active protection. Busy shared networks may hit the IP limit; this is a conservative development policy, not a final public traffic policy.

The application does not read X-Forwarded-For directly. It uses request.client.host, which can already have been rewritten by the ASGI server. Production must explicitly configure trusted proxy addresses, never blindly trust arbitrary forwarding headers, and verify behavior behind the actual hosting proxy.

This limiter is single-process and resets on process restart. Multiple workers or replicas require shared rate-limit state or a properly configured upstream limiter before public release. Invalid payloads rejected before the handler and request-body streaming limits are not addressed by this patch.

Local checks: python -m pytest -q, followed by python scripts/run_db_tests.py. Browser testers who exceed five registrations or logins in 15 minutes should wait for the window or restart the disposable sandbox; restarting deletes its test data. CSRF hardening and email verification remain separate release blockers.
