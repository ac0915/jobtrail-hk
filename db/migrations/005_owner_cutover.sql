-- FINAL CUTOVER ONLY: run after provisioning the owner and assigning legacy jobs.
-- This makes user ownership mandatory for every job.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM public.jobs WHERE user_id IS NULL
    ) THEN
        RAISE EXCEPTION 'Cannot enforce job ownership while unowned jobs remain.';
    END IF;
END $$;

ALTER TABLE public.jobs
    ALTER COLUMN user_id SET NOT NULL;

COMMIT;
