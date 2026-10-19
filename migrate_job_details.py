"""Add missing job-detail and cover-letter columns."""

from app.database import close_pool, get_pool, open_pool


COLUMNS = {
    "posted_at": "DATE",
    "apply_by": "DATE",
    "responsibilities": "TEXT",
    "requirements": "TEXT",
    "description": "TEXT",
    "cover_letter": "TEXT",
}


def main():
    try:
        open_pool()

        with get_pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SET LOCAL lock_timeout = '5s'")

                for name, data_type in COLUMNS.items():
                    cur.execute(
                        f"""
                        ALTER TABLE public.jobs
                        ADD COLUMN IF NOT EXISTS {name} {data_type}
                        """
                    )

        print(
            "Migration completed. "
            "Existing records were preserved."
        )
    finally:
        close_pool()


if __name__ == "__main__":
    main()