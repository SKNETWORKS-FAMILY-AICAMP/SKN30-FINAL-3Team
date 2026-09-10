"""Explicit target review rejects drift and omitted incompatible DB configurations."""

from unittest.mock import MagicMock

import pytest
from brokerage_ai.core.model_catalog import GeneralSelection

import model_selection as models


def row(brokerage_id=7, *, compatible=False, pending=0, current=True):
    return dict(
        brokerage_id=brokerage_id,
        capability="CHATBOT",
        compatible=compatible,
        current=[{"id": 11}] if current else [],
        pending_work=pending,
    )


def snapshot(monkeypatch, *rows):
    monkeypatch.setattr(
        models, "list_targets", lambda *args: dict(snapshot="reviewed", targets=list(rows))
    )
    apply = MagicMock()
    monkeypatch.setattr(models, "apply_selection", apply)
    return apply


def test_stale_review_never_writes(monkeypatch):
    apply = snapshot(monkeypatch, row())
    with pytest.raises(ValueError, match="changed after review"):
        models.apply_targets(
            MagicMock(), GeneralSelection(), [(7, models.Capability.CHATBOT)], "stale"
        )
    apply.assert_not_called()


@pytest.mark.parametrize(
    "rows,targets,message",
    [
        ([row(), row(8)], [(7, models.Capability.CHATBOT)], "outside selected"),
        ([row(pending=1)], [(7, models.Capability.CHATBOT)], "queued/in-progress"),
        ([row()], [(9, models.Capability.CHATBOT)], "does not exist"),
    ],
)
def test_invalid_or_incomplete_scope_never_partially_applies(monkeypatch, rows, targets, message):
    apply = snapshot(monkeypatch, *rows)
    with pytest.raises(ValueError, match=message):
        models.apply_targets(MagicMock(), GeneralSelection(), targets, "reviewed")
    apply.assert_not_called()


def test_only_explicit_changed_targets_create_versions(monkeypatch):
    apply = snapshot(monkeypatch, row(), row(8, compatible=True), row(9, compatible=True))
    result = models.apply_targets(
        MagicMock(),
        GeneralSelection(),
        [(7, models.Capability.CHATBOT), (8, models.Capability.CHATBOT)],
        "reviewed",
    )
    assert result == {"applied": ["7:CHATBOT"], "skipped": ["8:CHATBOT"]}
    assert apply.call_count == 1
    assert apply.call_args.args[1:3] == (7, models.Capability.CHATBOT)


@pytest.mark.parametrize("value", ["0:CHATBOT", "7:UNKNOWN", "7", "x:CHATBOT"])
def test_target_enum_and_positive_id(value):
    with pytest.raises(ValueError, match="BROKERAGE_ID:CAPABILITY"):
        models.parse_target(value)
