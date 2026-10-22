-- STAGED ONLY: review and test on a disposable database before executing.
-- This does NOT implement authorization or enable registration.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

CREATE TABLE public.jt_users (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT jt_users_email_normalized CHECK (
        email = lower(btrim(email)) AND char_length(email) BETWEEN 3 AND 254
        AND position('@' IN email) > 1
    ),
    CONSTRAINT jt_users_hash_format CHECK (
        password_hash ~ '^scrypt\$[0-9a-f]{32}\$[0-9a-f]{64}$'
    )
);

CREATE TABLE public.jt_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES public.jt_users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT jt_sessions_token_hash_format CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT jt_sessions_expiry CHECK (expires_at > created_at)
);
CREATE INDEX jt_sessions_user_idx ON public.jt_sessions(user_id);
CREATE INDEX jt_sessions_expiry_idx ON public.jt_sessions(expires_at);

-- Nullable during expansion so the old single-owner app can still insert rows.
-- A later cutover must backfill, enforce NOT NULL and require authenticated ownership.
ALTER TABLE public.jobs ADD COLUMN user_id BIGINT
    REFERENCES public.jt_users(id) ON DELETE RESTRICT;
CREATE INDEX jobs_user_created_idx ON public.jobs(user_id, created_at DESC);

-- Deliberately preserve existing jobs_url_unique until ownership backfill and API changes.
-- Deliberately do not create a public registration route or seed an owner implicitly.
COMMIT;
