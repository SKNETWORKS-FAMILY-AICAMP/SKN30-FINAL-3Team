from __future__ import annotations

import asyncio
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from brokerage_ai import ProviderError
from brokerage_ai.f2 import (
    EmptyTranscriptionError,
    F2Pipeline,
    F2PipelineError,
    F2PipelineRequest,
    F2PipelineResult,
    LedgerType,
)
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.routing import APIRoute
from pydantic import TypeAdapter
from pydantic import ValidationError as PydanticValidationError

from api.schemas.f2 import F2AnalysisResponse
from core.config import Config
from core.errors import (
    F2BusyError,
    F2ProcessingError,
    F2UnavailableError,
    PrivacyConsentRequiredError,
    ValidationError,
)
from domain.authentication.dependencies import get_current_user, require_csrf
from domain.authentication.models import CurrentUser
from domain.session import get_app_config


def _release_slot(request: Request, task: asyncio.Task[F2PipelineResult] | None) -> None:
    # A disconnected caller may no longer await the result; never log its private payload.
    if task is not None and not task.cancelled():
        task.exception()
    request.app.state.f2_analysis_task = None
    request.app.state.f2_analysis_busy = False


class F2AnalysisRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def admitted(request: Request):
            # Claim before multipart parsing: concurrent uploads must not fill the /tmp disk.
            # One API process/event loop, with no await between checking and claiming.
            if request.app.state.f2_analysis_busy:
                raise F2BusyError()
            request.app.state.f2_analysis_busy = True
            try:
                return await handler(request)
            finally:
                task = request.app.state.f2_analysis_task
                if task is not None and not task.done():
                    task.add_done_callback(lambda done: _release_slot(request, done))
                else:
                    _release_slot(request, task)

        return admitted


router = APIRouter(prefix="/f2", tags=["voice-analysis"], route_class=F2AnalysisRoute)

SUPPORTED_EXTENSIONS = {".wav", ".mp3", ".m4a"}
SUPPORTED_CONTENT_TYPES = {
    "application/octet-stream",
    "audio/mp3",
    "audio/mp4",
    "audio/mpeg",
    "audio/wav",
    "audio/x-m4a",
    "audio/x-wav",
}
FIELD_VALUES = TypeAdapter(dict[str, str | None])


def get_f2_pipeline(request: Request) -> F2Pipeline:
    pipeline: F2Pipeline | None = getattr(request.app.state, "f2_pipeline", None)
    if pipeline is None:
        raise F2UnavailableError()
    return pipeline


def _parse_current_fields(raw: str) -> dict[str, str | None]:
    if len(raw.encode("utf-8")) > 64 * 1024:
        raise ValidationError("current_fields is too large")
    try:
        decoded: Any = json.loads(raw)
        return FIELD_VALUES.validate_python(decoded)
    except (json.JSONDecodeError, PydanticValidationError):
        raise ValidationError("current_fields must be a JSON object of string values") from None


def _validate_audio(upload: UploadFile) -> str:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValidationError("audio must be a WAV, MP3, or M4A file")
    if upload.content_type and upload.content_type not in SUPPORTED_CONTENT_TYPES:
        raise ValidationError("audio content type is not supported")
    return suffix


async def _copy_limited(upload: UploadFile, destination: Any, limit: int) -> None:
    total = 0
    while chunk := await upload.read(1024 * 1024):
        total += len(chunk)
        if total > limit:
            raise ValidationError(f"audio must not exceed {limit} bytes")
        destination.write(chunk)
    if total == 0:
        raise ValidationError("audio must not be empty")
    destination.flush()


async def _run_and_cleanup(pipeline: F2Pipeline, analysis: F2PipelineRequest) -> F2PipelineResult:
    try:
        return await pipeline.run(analysis)
    finally:
        analysis.audio_path.unlink(missing_ok=True)


@router.post("/analyses", response_model=F2AnalysisResponse)
async def analyze_voice_memo(
    request: Request,
    audio: Annotated[UploadFile, File()],
    privacy_confirmed: Annotated[bool, Form()],
    current_fields: Annotated[str, Form()] = "{}",
    current_ledger_type: Annotated[LedgerType | None, Form()] = None,
    # 기존 Frontend가 배포된 동안의 하위 호환 입력. 신규 호출은 current_ledger_type을 쓴다.
    ledger_type: Annotated[LedgerType | None, Form()] = None,
    _user: CurrentUser = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
    config: Config = Depends(get_app_config),
    pipeline: F2Pipeline = Depends(get_f2_pipeline),
) -> F2AnalysisResponse:
    if not privacy_confirmed:
        raise PrivacyConsentRequiredError()
    if (
        current_ledger_type is not None
        and ledger_type is not None
        and current_ledger_type is not ledger_type
    ):
        raise ValidationError("current_ledger_type and ledger_type must match")

    suffix = _validate_audio(audio)
    parsed_fields = _parse_current_fields(current_fields)
    temp_path: Path | None = None
    task: asyncio.Task[F2PipelineResult] | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix="f2-audio-", suffix=suffix, delete=False) as temp:
            temp_path = Path(temp.name)
            await _copy_limited(audio, temp, config.f2.max_audio_bytes)

        task = asyncio.create_task(
            _run_and_cleanup(
                pipeline,
                F2PipelineRequest(
                    audio_path=temp_path,
                    current_ledger_type=current_ledger_type or ledger_type,
                    current_fields=parsed_fields,
                ),
            )
        )
        request.app.state.f2_analysis_task = task
        # STT runs in a thread. Caller cancellation must not delete its file or free its slot.
        result = await asyncio.shield(task)
        return F2AnalysisResponse.from_result(
            result,
            privacy_confirmed_at=datetime.now(UTC),
        )
    except EmptyTranscriptionError:
        raise ValidationError("음성에서 분석 가능한 텍스트를 찾지 못했습니다.") from None
    except ProviderError as error:
        # The public exception keeps only a private cause for safe type/location diagnostics.
        # The response and log never copy the Provider message or payload.
        raise F2UnavailableError() from error
    except F2PipelineError as error:
        raise F2ProcessingError() from error
    finally:
        try:
            if task is None and temp_path is not None:
                temp_path.unlink(missing_ok=True)
        finally:
            await audio.close()
