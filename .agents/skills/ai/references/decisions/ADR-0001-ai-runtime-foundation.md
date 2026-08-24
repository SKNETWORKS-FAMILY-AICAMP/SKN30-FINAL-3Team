---
status: 결정
updated: 2026-08-24
---

# ADR-0001: AI 런타임 기반과 Provider 경계

- 상태: 부분 대체됨
- 결정일: 2026-08-17
- 대체 범위: 환경 profile 파일과 dotenv 우선순위는 [프로젝트 ADR-0015](../../../project-wiki/references/decisions/ADR-0015-environment-configuration-ownership.md)가 대체

## 맥락

Backend와 독립적으로 AI workflow를 개발·검증하면서도 Backend Worker가 설치형 dependency로 사용할
수 있는 Python 패키지가 필요하다. OpenAI와 OpenAI-compatible vLLM을 실험할 수 있어야 하지만,
운영 Provider·모델을 미리 확정하거나 SDK 타입을 모듈 경계로 누출해서는 안 된다.

## 결정

- `ai/`는 Python 3.13과 uv를 사용하는 독립 library 프로젝트이며 자체 `pyproject.toml`과 `uv.lock`을 소유한다.
- 배포 이름은 `brokerage-ai`, import 이름은 `brokerage_ai`로 하고 `src/brokerage_ai/` 패키지를 사용한다.
- `core/`가 환경 설정, 안전한 오류 계층과 Provider 중립 DTO를 소유한다.
- `providers/ports.py`의 async Protocol과 `ModelRoute(provider, model)`을 안정된 호출 계약으로 사용한다.
- OpenAI adapter는 Responses structured parse와 Embeddings API를, vLLM adapter는 OpenAI-compatible Chat Completions structured parse와 Embeddings API를 사용한다.
- vLLM 생성 endpoint와 embedding endpoint는 독립 설정한다.
- `runtime.py`는 검증된 `AiConfig`만 받고 SDK client의 중복 생성을 방지하며 async 종료를 책임진다.
- SDK 자동 재시도는 끄고 workflow·Worker가 실제 호출 수와 비용을 포함한 재시도 정책을 소유한다.
- 환경 파일 소유권과 로딩 규칙은 프로젝트 ADR-0015를 따른다. import 시 설정을 읽지 않는 경계는 유지한다.
- `brokerage_ai` 공개 진입점은 SDK·LangGraph 구체 타입과 adapter를 재노출하지 않는다.
- AI는 FastAPI·SQLAlchemy·DB client를 import하지 않고 Backend는 OpenAI SDK·LangGraph·프롬프트를 직접 import하지 않는다.
- 실제 workflow 책임이 생기기 전에는 `workflows/`, `graphs/`, `prompts/`, `agents/`, `capabilities/`, `checkpoints/`, `evals/`를 만들지 않는다.

## 결과

Backend는 로컬에서 `../ai` editable dependency로 타입이 있는 AI 계약을 설치할 수 있고, 배포에서는
저장소 루트 build context와 `uv sync --no-editable`을 사용할 수 있다. 두 모듈의 환경과 lock은
독립적으로 유지된다.

OpenAI와 vLLM adapter의 존재는 운영 Provider·모델 선택을 의미하지 않는다. LangGraph 전이 의존성에
LangSmith 패키지가 포함될 수 있지만 추적 서비스 연동이나 LangSmith 직접 의존은 활성화하지 않는다.
