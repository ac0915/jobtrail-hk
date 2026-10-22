-- STAGED: multi-user cutover only. Test on disposable databases first.
-- Do not apply to production or treat disabling the feature flag as a rollback.
-- Legacy NULL-owner rows retain uniqueness among themselves.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

CREATE UNIQUE INDEX jobs_user_url_unique
    ON public.jobs (user_id, url)
    WHERE user_id IS NOT NULL AND url IS NOT NULL AND btrim(url) <> '';

CREATE UNIQUE INDEX jobs_legacy_url_unique
    ON public.jobs (url)
    WHERE user_id IS NULL AND url IS NOT NULL AND btrim(url) <> '';

-- Create replacement protections before dropping the old global index.
DROP INDEX public.jobs_url_unique;
COMMIT;
