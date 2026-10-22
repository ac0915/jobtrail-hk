-- Adds optional email verification and single-use verification tokens.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

ALTER TABLE public.jt_users
    ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS public.jt_email_tokens (
    token_hash TEXT PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES public.jt_users(id) ON DELETE CASCADE,
    purpose TEXT NOT NULL DEFAULT 'email_verification',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ,
    CONSTRAINT jt_email_tokens_purpose_check CHECK (purpose = 'email_verification'),
    CONSTRAINT jt_email_tokens_token_hash_format CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT jt_email_tokens_expiry_check CHECK (expires_at > created_at),
    CONSTRAINT jt_email_tokens_used_after_created_check CHECK (used_at IS NULL OR used_at >= created_at)
);

CREATE INDEX IF NOT EXISTS jt_email_tokens_user_purpose_idx
    ON public.jt_email_tokens(user_id, purpose);
CREATE INDEX IF NOT EXISTS jt_email_tokens_expiry_idx
    ON public.jt_email_tokens(expires_at);

COMMIT;
