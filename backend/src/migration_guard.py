from __future__ import annotations

import os
import subprocess
import urllib.parse
from pathlib import Path

import psycopg

LOCK_ID = 7_330_300_001


def psycopg_url(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def require_ssl_root_certificate(url: str) -> None:
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    sslmode = query.get("sslmode", [""])[0]
    if sslmode not in {"verify-ca", "verify-full"}:
        return

    raw_path = query.get("sslrootcert", [""])[0]
    if raw_path == "system":
        return
    certificate = Path(urllib.parse.unquote(raw_path))
    if not certificate.is_file():
        raise SystemExit(f"RDS root certificate is not readable: {certificate}")


def main() -> None:
    migration_url = os.environ.get("DB_MIGRATION_URL", "").strip()
    if not migration_url:
        raise SystemExit("DB_MIGRATION_URL is required for migration")
    require_ssl_root_certificate(migration_url)

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
