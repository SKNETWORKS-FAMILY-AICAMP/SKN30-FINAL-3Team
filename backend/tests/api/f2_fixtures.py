"""F2 HTTP tests share only the external pipeline boundary and app assembly."""

from __future__ import annotations

from pathlib import Path

from brokerage_ai.f2 import (
    ConsultationType,
    F2PipelineRequest,
    F2PipelineResult,
    FieldProposal,
    LedgerType,
    ProposalStatus,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.f2 import get_f2_pipeline
from domain.authentication.dependencies import get_current_user, require_csrf
from domain.authentication.models import CurrentUser, UserRole
from main import create_app


class FakePipeline:
    def __init__(
        self,
        error: Exception | None = None,
        *,
        consultation_type: ConsultationType = ConsultationType.SELL_REQUEST,
    ) -> None:
        self.request: F2PipelineRequest | None = None
        self.audio_bytes = b""
        self.temp_path: Path | None = None
        self.error = error
        self.consultation_type = consultation_type

    async def run(self, request: F2PipelineRequest) -> F2PipelineResult:
        self.request = request
        self.temp_path = request.audio_path
        self.audio_bytes = request.audio_path.read_bytes()
        if self.error is not None:
            raise self.error
        recommended_ledger = (
            LedgerType.PROPERTY
            if self.consultation_type is ConsultationType.SELL_REQUEST
            else LedgerType.BUYER
            if self.consultation_type is ConsultationType.BUY_REQUEST
            else None
        )
        return F2PipelineResult(
            transcript="한강아파트를 12억에 매도합니다.",
            transcription_model="openai/whisper-large-v3-turbo",
            ledger_type=recommended_ledger,
            consultation_type=self.consultation_type,
            ledger_mismatch=(
                request.current_ledger_type is not None
                and recommended_ledger is not None
                and request.current_ledger_type is not recommended_ledger
            ),
            proposals=(
                FieldProposal(
                    field_name="매매가",
                    current_value=None,
                    proposed_value="12억",
                    evidence="12억에 매도",
                    status=ProposalStatus.CONFIRMED,
                    selected_by_default=True,
                ),
            ),
            uncertainties=(),
            consultation_log_draft="한강아파트 12억 매도 의뢰.",
        )


def app_with_pipeline(config, pipeline: FakePipeline) -> FastAPI:
    app = create_app(config=config, readiness_probe=lambda request: True)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=1,
        brokerage_id=1,
        login_id="f2-test",
        display_name="F2 검증",
        role=UserRole.OWNER,
    )
    app.dependency_overrides[require_csrf] = lambda: None
    app.dependency_overrides[get_f2_pipeline] = lambda: pipeline
    return app


def client_with_pipeline(config, pipeline: FakePipeline) -> TestClient:
    return TestClient(app_with_pipeline(config, pipeline))
