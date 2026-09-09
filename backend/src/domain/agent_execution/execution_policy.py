"""Persisted run state to execution step, shared by dispatch and capability assembly.

This selects work only. Lease, input validation and the ledger-save promotion race
are enforced transactionally by the application use cases and repository.
"""

from enum import StrEnum

from domain.agent_execution.models import (
    ANCHOR_READY_STATUS,
    CANDIDATE_CARDS_READY_STATUS,
    CANDIDATES_READY_STATUS,
    JUDGING_STATUS,
    RUNNING_STATUS,
)


class ExecutionStep(StrEnum):
    ANCHOR_CARD = "ANCHOR_CARD"
    CANDIDATE_SELECTION = "CANDIDATE_SELECTION"
    CANDIDATE_CARDS = "CANDIDATE_CARDS"
    JUDGMENT = "JUDGMENT"
    IDLE = "IDLE"


def next_step(status: str) -> ExecutionStep:
    """Unknown and terminal states never start model work."""
    return {
        RUNNING_STATUS: ExecutionStep.ANCHOR_CARD,
        ANCHOR_READY_STATUS: ExecutionStep.CANDIDATE_SELECTION,
        CANDIDATES_READY_STATUS: ExecutionStep.CANDIDATE_CARDS,
        CANDIDATE_CARDS_READY_STATUS: ExecutionStep.JUDGMENT,
        JUDGING_STATUS: ExecutionStep.JUDGMENT,
    }.get(status, ExecutionStep.IDLE)
