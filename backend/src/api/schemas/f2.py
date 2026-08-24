from __future__ import annotations

from datetime import datetime

from brokerage_ai.f2 import F2PipelineResult, ProposalStatus
from pydantic import BaseModel, ConfigDict


class F2ProposalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_name: str
    current_value: str | None
    proposed_value: str
    evidence: str
    status: ProposalStatus
    selected_by_default: bool


class F2AnalysisResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    consultation_type: str
    ledger_mismatch: bool
    proposals: list[F2ProposalResponse]
    uncertainties: list[str]
    consultation_log_draft: str
    privacy_confirmed_at: datetime

    @classmethod
    def from_result(
        cls,
        result: F2PipelineResult,
        *,
        privacy_confirmed_at: datetime,
    ) -> F2AnalysisResponse:
        return cls(
            consultation_type=result.consultation_type.value,
            ledger_mismatch=result.ledger_mismatch,
            proposals=[
                F2ProposalResponse(
                    field_name=proposal.field_name,
                    current_value=proposal.current_value,
                    proposed_value=proposal.proposed_value,
                    evidence=proposal.evidence,
                    status=proposal.status,
                    selected_by_default=proposal.selected_by_default,
                )
                for proposal in result.proposals
            ],
            uncertainties=list(result.uncertainties),
            consultation_log_draft=result.consultation_log_draft,
            privacy_confirmed_at=privacy_confirmed_at,
        )
