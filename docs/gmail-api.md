# Gmail API transactional email

Applies to the `multi-user` branch. This implementation replaces SMTP; there is no automatic SMTP fallback. Existing verification and password-reset entry points and MIME templates are retained.

## Private configuration

1. Install `requirements.txt` in the website runtime.
2. Supply exactly one of `GMAIL_TOKEN_FILE` (absolute path to a mounted secret) or `GMAIL_TOKEN_JSON` (full JSON in a private environment secret).
3. Use the **authorized-user token** produced by local setup (`gmail_token.json`), not the client-only `credentials.json`. The token JSON must contain `refresh_token`, `client_id`, and `client_secret`. If scopes are present, only `https://www.googleapis.com/auth/gmail.send` is accepted.
4. Set `EMAIL_FROM=JobTrail HK <jobtrialhk@gmail.com>` and ensure the authorizing account is that mailbox or permits the selected send-as alias. The app does not query Gmail profile/read scopes to verify mailbox identity.
5. Set `APP_BASE_URL` to the real backend website, not the GitHub Pages information site. For production, set `APP_ENV=production` and an HTTPS base URL. Missing/HTTP production base URLs fail before creating email links.
6. Enable `MULTI_USER_ENABLED=true` only after required migrations and account-isolation checks. This change does not modify that feature flag or apply migrations.
7. Restart/redeploy from `multi-user` after configuring secrets. No browser authorization flow runs on the server.

The token JSON contains secrets. Do not commit it, paste it into chat, copy it into the Docker image, or put it in publicly served directories. A mounted secret should be readable only by the runtime account. Keep local setup files outside the repository. Restart workers after rotating secret contents because credentials are cached per process.

## Delivery behavior

Google `google-auth` refreshes access tokens when needed; refresh operations are protected by a per-process lock. Access tokens stay in process memory. Token files/environment variables are not rewritten. HTTP calls have a 20-second timeout per request. A Gmail HTTP 200 response with a message ID means API acceptance, not guaranteed inbox delivery. The returned `delivered` field is retained for existing route compatibility.

No automatic resend occurs after a timeout or API error, avoiding duplicate messages when acceptance is uncertain. Failures return through the existing route error handling. No raw token, credential JSON or Gmail response body is included in transport exceptions.

Testing-mode external OAuth refresh tokens with Gmail scopes expire after 7 days. This code does not remove that Google policy limitation. Resolve the appropriate production publishing/verification arrangement before relying on unattended long-term email.

This patch does not add durable retry/outbox delivery, change verification-token invalidation, or fix every production-hardening item. It does not deploy the website or change Google Cloud settings.

## Verification

Run `python -m pytest tests/test_gmail_email.py tests/test_auth_email_dispatch.py` after installing dependencies. These are mocked tests, not real Gmail or PostgreSQL integration tests. Run the full suite separately; older authentication tests must be reconciled with current email-verification behavior.

On a staging backend with real private configuration, test registration, received verification link, resend, login, password reset and session invalidation. Do not use production accounts or data for destructive tests. Keep OAuth credentials out of test reports.

References: https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/send and https://developers.google.com/identity/protocols/oauth2
