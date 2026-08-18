# Brokerage AI

Backend에서 사용하는 Python 3.13 기반 AI 라이브러리입니다. 독립적으로 실행하는 서버나 CLI는 없습니다.

## 설치

[uv](https://docs.astral.sh/uv/)를 준비한 뒤 의존성을 설치합니다.

```bash
cd ai
uv sync --frozen
```

모델 API 비밀값이 필요한 경우 [`.env.example`](.env.example)에 선언된 변수 이름을 참고해 Git에서 제외된 `ai/.env` 또는 실행 프로세스 환경변수로 주입합니다.

## F2 음성메모 파이프라인

`brokerage_ai.f2`에는 다음 실행 흐름을 연결하는 프레임워크 중립 파이프라인이 있습니다.

```text
음성 파일 → Transcriber → STT 텍스트 → ConsultationAnalyzer
→ 상담 유형·근거 기반 필드 추출 → 사용자 검토용 제안
```

- `FasterWhisperTranscriber`는 로컬 `faster-whisper` 구현입니다. 무거운 선택 의존성이므로
  실제 STT 실행 환경에서 별도로 설치하며, 설치되지 않은 경우 명확한 오류를 반환합니다.
- `LlmConsultationAnalyzer`는 기존 `LlmProvider`를 사용합니다. 로컬 vLLM에 올린 Qwen 모델을
  사용할 때는 `ProviderKind.VLLM`의 `ModelRoute`를 주입합니다.
- Qwen 모델 ID는 파이프라인에 고정하지 않습니다. 모델 비교 후 원본 Qwen 또는 QLoRA 모델
  경로를 `ModelRoute.model`에 지정합니다.
- 파이프라인은 DB를 수정하지 않습니다. 현재값 비교와 기본 선택 여부를 포함한 제안만 반환하고,
  사용자 승인·타입 검증·중복 검사·저장은 Backend가 수행합니다.

테스트에서는 실제 모델 대신 fake STT와 fake 분석기를 주입하므로 모델 다운로드 없이 전체 연결과
안전 규칙을 검증할 수 있습니다.
