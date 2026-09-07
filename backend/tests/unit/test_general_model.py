from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import general_model as module
from conftest import config_values
from core.config import bind_config


def test_local_activation_cannot_target_dev() -> None:
    config = bind_config(config_values(APP_ENV="local", DB_TARGET="development"))
    with pytest.raises(ValueError, match="cannot target shared dev"):
        module.activate_general(config, 1, apply=True, shared_dev=True, workloads_stopped=True)


def test_dev_activation_requires_explicit_target() -> None:
    config = bind_config(config_values(APP_ENV="dev", DB_TARGET="development"))
    with pytest.raises(ValueError, match="shared-dev"):
        module.activate_general(config, 1, apply=True, shared_dev=False, workloads_stopped=True)


def test_activation_changes_only_model_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    config = bind_config(config_values(APP_ENV="dev", DB_TARGET="development"))
    cursor = MagicMock()
    cursor.fetchone.side_effect = [(1,), (0,), None, None]
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.cursor.return_value.__enter__.return_value = cursor
    monkeypatch.setattr(module.psycopg, "connect", lambda *args, **kwargs: connection)
    monkeypatch.setattr(
        module,
        "load_ai_config",
        lambda *_: SimpleNamespace(llm_endpoints=[SimpleNamespace(alias=module.ALIAS)]),
    )
    module.activate_general(config, 1, apply=True, shared_dev=True, workloads_stopped=True)
    statements = [call.args[0].strip().upper() for call in cursor.execute.call_args_list]
    mutations = [query for query in statements if not query.startswith("SELECT")]
    assert len(mutations) == 4
    assert all(
        query.startswith(("UPDATE AI_MODEL_CONFIG", "INSERT INTO AI_MODEL_CONFIG"))
        for query in mutations
    )
    assert not any("DELETE" in query or "TRUNCATE" in query for query in statements)


def test_pending_runs_prevent_model_change(monkeypatch: pytest.MonkeyPatch) -> None:
    config = bind_config(config_values(APP_ENV="dev", DB_TARGET="development"))
    cursor = MagicMock()
    cursor.fetchone.side_effect = [(1,), (2,)]
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.cursor.return_value.__enter__.return_value = cursor
    monkeypatch.setattr(module.psycopg, "connect", lambda *args, **kwargs: connection)
    monkeypatch.setattr(
        module,
        "load_ai_config",
        lambda *_: SimpleNamespace(llm_endpoints=[SimpleNamespace(alias=module.ALIAS)]),
    )
    with pytest.raises(ValueError, match="queued/in-progress"):
        module.activate_general(config, 1, apply=True, shared_dev=True, workloads_stopped=True)
    assert all(call.args[0].startswith("SELECT") for call in cursor.execute.call_args_list)
