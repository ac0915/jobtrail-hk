-- Optional migration if you already created a simpler jobs table.
-- Review your data first: SELECT DISTINCT status FROM jobs;

-- Add applied_at if missing
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS applied_at DATE;

-- Tighten status values (fails if unexpected statuses exist)
UPDATE jobs
SET status = lower(btrim(status))
WHERE status IS NOT NULL;

UPDATE jobs
SET status = 'saved'
WHERE status IS NULL OR status = '';

ALTER TABLE jobs DROP CONSTRAINT IF EXISTS jobs_status_check;
ALTER TABLE jobs
    ADD CONSTRAINT jobs_status_check
    CHECK (status IN ('saved', 'applied', 'interview', 'offer', 'rejected', 'closed'));

CREATE UNIQUE INDEX IF NOT EXISTS jobs_url_unique
    ON jobs (url)
    WHERE url IS NOT NULL AND btrim(url) <> '';

CREATE INDEX IF NOT EXISTS jobs_status_idx ON jobs (status);
CREATE INDEX IF NOT EXISTS jobs_created_at_idx ON jobs (created_at DESC);

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS posted_at DATE;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS apply_by DATE;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS responsibilities TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS requirements TEXT;
