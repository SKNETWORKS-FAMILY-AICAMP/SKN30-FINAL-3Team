from __future__ import annotations

import os
import subprocess

import psycopg

LOCK_ID = 7_330_300_001


def psycopg_url(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def main() -> None:
    migration_url = os.environ.get("DB_MIGRATION_URL", "").strip()
    if not migration_url:
        raise SystemExit("DB_MIGRATION_URL is required for migration")

    with psycopg.connect(psycopg_url(migration_url), autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_lock(%s)", (LOCK_ID,))
        try:
            result = subprocess.run(["yoyo", "apply", "--batch"], check=False)
            if result.returncode != 0:
                raise SystemExit(result.returncode)
        finally:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", (LOCK_ID,))


if __name__ == "__main__":
    main()
