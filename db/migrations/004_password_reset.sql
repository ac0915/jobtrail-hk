-- Allows the shared single-use token table to issue password-reset links.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

ALTER TABLE public.jt_email_tokens
    DROP CONSTRAINT IF EXISTS jt_email_tokens_purpose_check;

ALTER TABLE public.jt_email_tokens
    ADD CONSTRAINT jt_email_tokens_purpose_check
    CHECK (purpose IN ('email_verification', 'password_reset'));

COMMIT;
