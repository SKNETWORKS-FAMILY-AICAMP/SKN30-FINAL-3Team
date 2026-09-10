"""Model changes remain explicit, scoped, versioned and never overwrite run snapshots."""

from typing import cast
from unittest.mock import MagicMock

import pytest
from brokerage_ai.core.model_catalog import GeneralSelection
from sqlmodel import Session

from model_selection import Capability, apply_selection


def session_with_results(*values):
    session = MagicMock(spec=Session)
    results = [MagicMock(), MagicMock(), MagicMock()]
    for value in values:
        result = MagicMock()
        result.scalar_one.return_value = value
        result.scalar_one_or_none.return_value = value
        result.one_or_none.return_value = value
        result.all.return_value = [value] if isinstance(value, tuple) else []
        results.append(result)
    session.execute.side_effect = results
    return session


@pytest.mark.parametrize("values", [(None,), (1, 1), (1, 0, 1)])
def test_missing_brokerage_or_pending_work_prevents_writes(values):
    session = session_with_results(*values)
    with pytest.raises(ValueError):
        apply_selection(cast(Session, session), 7, Capability.POSITION_CARD, GeneralSelection())
    assert all(
        str(call.args[0]).startswith(("SELECT", "SET LOCAL", "LOCK TABLE"))
        for call in session.execute.call_args_list
    )


def test_same_selection_is_idempotent():
    session = session_with_results(7, 0, 0, ("openai", "gpt-5.6-luna", None, None))
    apply_selection(cast(Session, session), 7, Capability.POSITION_CARD, GeneralSelection())
    assert len(session.execute.call_args_list) == 7


def test_change_inserts_new_version_only_for_selected_capability():
    session = session_with_results(
        7, 0, 0, ("vllm", "old-model", "old-revision", "general-dev-gpu"), 8, None, None
    )
    apply_selection(cast(Session, session), 7, Capability.BROKERAGE_JUDGMENT, GeneralSelection())
    writes = session.execute.call_args_list[-2:]
    assert str(writes[0].args[0]).startswith("UPDATE ai_model_config SET is_active=FALSE")
    assert "capability=:capability" in str(writes[0].args[0])
    assert str(writes[1].args[0]).startswith("INSERT INTO ai_model_config")
    assert writes[1].args[1]["version"] == 8
    assert writes[1].args[1]["capability"] == "BROKERAGE_JUDGMENT"
    assert writes[1].args[1]["id"] == 7
    assert all(
        not str(c.args[0]).startswith(("DELETE", "UPDATE agent_run"))
        for c in session.execute.call_args_list
    )
