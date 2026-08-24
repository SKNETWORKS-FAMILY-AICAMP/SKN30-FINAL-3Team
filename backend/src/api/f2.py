from __future__ import annotations

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
    LedgerType,
)
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from pydantic import TypeAdapter
from pydantic import ValidationError as PydanticValidationError

from api.schemas.f2 import F2AnalysisResponse
from core.config import Config
from core.errors import (
    F2ProcessingError,
    F2UnavailableError,
    PrivacyConsentRequiredError,
    ValidationError,
)
from domain.authentication.dependencies import get_current_user, require_csrf
from domain.authentication.models import CurrentUser
from domain.session import get_app_config

router = APIRouter(prefix="/f2", tags=["voice-analysis"])

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


@router.post("/analyses", response_model=F2AnalysisResponse)
async def analyze_voice_memo(
    audio: Annotated[UploadFile, File()],
    ledger_type: Annotated[LedgerType, Form()],
    current_fields: Annotated[str, Form()],
    privacy_confirmed: Annotated[bool, Form()],
    _user: CurrentUser = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
    config: Config = Depends(get_app_config),
    pipeline: F2Pipeline = Depends(get_f2_pipeline),
) -> F2AnalysisResponse:
    if not privacy_confirmed:
        raise PrivacyConsentRequiredError()

    suffix = _validate_audio(audio)
    parsed_fields = _parse_current_fields(current_fields)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix="f2-audio-", suffix=suffix, delete=False) as temp:
            temp_path = Path(temp.name)
            await _copy_limited(audio, temp, config.f2.max_audio_bytes)

        result = await pipeline.run(
            F2PipelineRequest(
                audio_path=temp_path,
                ledger_type=ledger_type,
                current_fields=parsed_fields,
            )
        )
        return F2AnalysisResponse.from_result(
            result,
            privacy_confirmed_at=datetime.now(UTC),
        )
    except EmptyTranscriptionError:
        raise ValidationError("음성에서 분석 가능한 텍스트를 찾지 못했습니다.") from None
    except ProviderError:
        raise F2UnavailableError() from None
    except F2PipelineError:
        raise F2ProcessingError() from None
    finally:
        await audio.close()
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
