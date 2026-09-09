"""Seed deterministic matching examples through the Infra-owned PG connection environment.

No provider keys, dotenv loading, SQL paths, or connection URLs are accepted on argv.
Shared dev callers must use the guarded IAM/SSM command in infra/justfile.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import ipaddress
import json
import os
import sys
from pathlib import Path

import psycopg
from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from synthetic_match_seed import complete_match_seed  # noqa: E402
from synthetic_seed import F3_MODEL_PROFILES, SyntheticSeedError  # noqa: E402


def loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def require_connection_environment() -> None:
    host = os.environ.get("PGHOST", "")
    if not host or not os.environ.get("PGDATABASE") or os.environ.get("APP_ENV") == "prod":
        raise SyntheticSeedError("an explicit local or guarded dev seed connection is required")
    hostaddr = os.environ.get("PGHOSTADDR", "")
    if loopback(host) and (not hostaddr or loopback(hostaddr)):
        return
    if loopback(host):
        raise SyntheticSeedError("local seed hostaddr must also be loopback")
    if not (
        loopback(os.environ.get("PGHOSTADDR", ""))
        and os.environ.get("PGSSLMODE") == "verify-full"
        and os.environ.get("PGSSLROOTCERT")
        and os.environ.get("PGOPTIONS") == "-c role=app_owner"
    ):
        raise SyntheticSeedError("shared dev seed requires the Infra IAM/SSM connection")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-synthetic-seed", action="store_true", required=True)
    parser.add_argument("--model-profile", choices=F3_MODEL_PROFILES, required=True)
    args = parser.parse_args()
    engine = None
    try:
        require_connection_environment()
        # libpq consumes PG* privately, including hostaddr, verified TLS and role options.
        engine = create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(""))
        with contextlib.redirect_stdout(io.StringIO()):
            result = complete_match_seed(engine, args.model_profile)
        print(json.dumps(result, ensure_ascii=False))
    except Exception:
        parser.exit(
            1, "Synthetic match seed failed; inspect local checks. Sensitive details withheld.\n"
        )
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    main()
