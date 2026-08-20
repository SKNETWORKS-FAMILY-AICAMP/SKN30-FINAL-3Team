"""F2 파이프라인에서 호출자가 구분해 처리할 수 있는 오류."""


class F2PipelineError(Exception):
    """F2 처리 실패의 기본 오류."""


class AudioInputError(F2PipelineError):
    """음성 파일이 없거나 읽을 수 없을 때 발생한다."""


class EmptyTranscriptionError(F2PipelineError):
    """STT가 분석 가능한 텍스트를 만들지 못했을 때 발생한다."""


class F2DependencyError(F2PipelineError):
    """선택한 모델 실행에 필요한 선택 의존성이 없을 때 발생한다."""
