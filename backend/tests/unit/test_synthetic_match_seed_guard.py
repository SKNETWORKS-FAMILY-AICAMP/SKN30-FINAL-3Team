"""The shared dev adapter rejects accidental remote connections and hides failures."""

import importlib.util
from pathlib import Path

import pytest

from synthetic_seed import SyntheticSeedError

script = Path(__file__).resolve().parents[2] / "scripts" / "seed_match_results.py"
spec = importlib.util.spec_from_file_location("seed_match_script", script)
assert spec is not None and spec.loader is not None
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


@pytest.fixture(autouse=True)
def clean_connection_environment(monkeypatch):
    for key in (
        "PGHOST",
        "PGHOSTADDR",
        "PGDATABASE",
        "PGSSLMODE",
        "PGSSLROOTCERT",
        "PGOPTIONS",
        "APP_ENV",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("PGDATABASE", "brokerage")


def test_rejects_missing_host_and_production(monkeypatch):
    with pytest.raises(SyntheticSeedError):
        adapter.require_connection_environment()
    monkeypatch.setenv("PGHOST", "127.0.0.1")
    monkeypatch.setenv("APP_ENV", "prod")
    with pytest.raises(SyntheticSeedError):
        adapter.require_connection_environment()


def test_local_host_cannot_override_network_destination(monkeypatch):
    monkeypatch.setenv("PGHOST", "localhost")
    adapter.require_connection_environment()
    monkeypatch.setenv("PGHOSTADDR", "203.0.113.9")
    with pytest.raises(SyntheticSeedError):
        adapter.require_connection_environment()


def test_remote_hostname_requires_verified_tunnel_and_owner_role(monkeypatch):
    monkeypatch.setenv("PGHOST", "example.rds.amazonaws.com")
    for key, value in (
        ("PGHOSTADDR", "127.0.0.1"),
        ("PGSSLMODE", "verify-full"),
        ("PGSSLROOTCERT", "/tmp/test-ca.pem"),
        ("PGOPTIONS", "-c role=app_owner"),
    ):
        with pytest.raises(SyntheticSeedError):
            adapter.require_connection_environment()
        monkeypatch.setenv(key, value)
    adapter.require_connection_environment()


def test_script_requires_confirmation_before_connection(monkeypatch):
    monkeypatch.setattr(
        adapter.sys, "argv", ["seed_match_results.py", "--model-profile", "local-openai"]
    )
    monkeypatch.setattr(
        adapter, "create_engine", lambda *a, **k: pytest.fail("no connection allowed")
    )
    with pytest.raises(SystemExit) as error:
        adapter.main()
    assert error.value.code == 2


def test_failure_does_not_expose_database_error(monkeypatch, capsys):
    monkeypatch.setattr(
        adapter.sys,
        "argv",
        ["seed_match_results.py", "--confirm-synthetic-seed", "--model-profile", "local-openai"],
    )
    monkeypatch.setenv("PGHOST", "localhost")

    def fail(*args, **kwargs):
        raise RuntimeError("secret-fixture-credential")

    monkeypatch.setattr(adapter, "create_engine", fail)
    with pytest.raises(SystemExit) as error:
        adapter.main()
    assert error.value.code == 1
    output = capsys.readouterr()
    assert "secret-fixture-credential" not in output.err + output.out
    assert "Sensitive details withheld" in output.err
