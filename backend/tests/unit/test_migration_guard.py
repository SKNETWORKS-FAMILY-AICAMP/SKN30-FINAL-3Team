from pathlib import Path

import pytest

from migration_guard import require_ssl_root_certificate


def test_verify_full_requires_existing_root_certificate(tmp_path: Path) -> None:
    missing = tmp_path / "missing-rds-ca.pem"
    url = f"postgresql+psycopg://user:password@db.example/brokerage?sslmode=verify-full&sslrootcert={missing}"

    with pytest.raises(SystemExit, match="RDS root certificate is not readable"):
        require_ssl_root_certificate(url)


def test_verify_full_accepts_existing_root_certificate(tmp_path: Path) -> None:
    certificate = tmp_path / "rds ca.pem"
    certificate.write_text("certificate", encoding="utf-8")
    encoded = str(certificate).replace(" ", "%20")
    url = f"postgresql+psycopg://user:password@db.example/brokerage?sslmode=verify-full&sslrootcert={encoded}"

    require_ssl_root_certificate(url)


def test_non_verifying_connection_does_not_require_certificate() -> None:
    require_ssl_root_certificate(
        "postgresql+psycopg://user:password@localhost/brokerage?sslmode=disable"
    )
