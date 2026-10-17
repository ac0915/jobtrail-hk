# JobTrail HK

A Hong Kong-focused **job application tracker** — not a job board. You find roles on JobsDB, Indeed, or company sites, then track them here: status, applied date, notes, and (later) cover-letter versions.

## Milestone status

| Milestone | Scope | In this repo |
| --- | --- | --- |
| **1** Stabilise backend | Validation, statuses, duplicates, schema, tests, setup docs | **Yes** (this API) |
| **2** Usable frontend | My Jobs, add/edit/delete, layout | Built in Grok App Builder preview (not in this repo yet) |
| **3** Application tracking | Status workflow, applied date, filters, dashboard | Domain rules in this API (`status`, `applied_at`); full UI was in App Builder |
| **4** Link import | Prefill from JobsDB/Indeed links | Not started |
| **5+** Cover letters, follow-ups, accounts | — | Not started |

### Allowed statuses

`saved` → `applied` → `interview` → `offer`  
          ↘ `rejected`  
Any stage → `closed`

These are available values, not a forced path through every stage.

## Local setup

### 1. Python environment

```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Database

```bash
# Create DB (example)
createdb jobtrail_hk

# Fresh install
psql -d jobtrail_hk -f db/schema.sql

# Or migrate an existing jobs table
psql -d jobtrail_hk -f db/migrate_existing.sql
```

### 3. Environment

```bash
cp .env.example .env
# Edit DATABASE_URL to match your PostgreSQL user/password/host
```

### 4. Run the API

```bash
uvicorn main:app --reload
```

- Health: http://127.0.0.1:8000/
- Interactive docs: http://127.0.0.1:8000/docs

### 5. Tests (no database required)

```bash
pytest tests/test_validation.py -q
```

API integration tests against a live database can be added later with `DATABASE_URL` set.

## API overview

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/jobs` | List jobs (newest first) |
| `GET` | `/jobs/{id}` | One job, or 404 |
| `POST` | `/jobs` | Create; rejects empty title/company; 409 on duplicate URL |
| `PATCH` | `/jobs/{id}` | Partial update; cannot clear title/company/status |
| `DELETE` | `/jobs/{id}` | Delete |
| `GET` | `/jobs/meta/statuses` | Allowed status values |

**Create body (example)**

```json
{
  "title": "Junior Software Developer",
  "company": "Harbour & Co",
  "url": "https://hk.jobsdb.com/job/123",
  "location": "Kwun Tong",
  "salary": "HK$22,000–28,000",
  "source": "JobsDB",
  "status": "saved",
  "notes": "Hybrid two days."
}
```

Duplicate URL response is **409** with:

```json
{
  "detail": {
    "code": "duplicate_url",
    "message": "You already saved this listing: … at ….",
    "existing_id": 1
  }
}
```

## Product direction

Everyday flow: find a job → paste link or enter manually → save → attach cover letter version → mark applied → track interview / offer / rejection.

Next planned work: **Milestone 4** (link import with editable preview) and a durable frontend in this repository once the App Builder UI is ported or rebuilt here.
