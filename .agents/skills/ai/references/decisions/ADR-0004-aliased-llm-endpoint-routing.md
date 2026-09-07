---
status: 결정
updated: 2026-09-03
---

# ADR-0004: 범용 생성 Provider는 endpoint alias로 정확히 routing한다

- 상태: 부분 대체됨·코드 구현
- 결정일: 2026-09-03
- 상위 결정: [프로젝트 ADR-0026](../../../project-wiki/references/decisions/ADR-0026-general-ai-provider-and-model-profiles.md)
- 부분 대체: [ADR-0001](ADR-0001-ai-runtime-foundation.md)의 `ModelRoute(provider, model)`과
  Provider 종류별 단일 LLM 등록 계약
- 대체된 범위: Bedrock Provider와 SigV4 인증은
  [ADR-0005](ADR-0005-bedrock-sigv4-structured-generation.md) 적용

## 맥락

F2의 RunPod vLLM은 alias 없는 고정 SLLM·STT endpoint를 사용한다. F3와 향후 범용 생성 기능은
DB `ai_model_config`가 선택한 provider·model·`endpoint_alias`를 실제 endpoint에 연결해야 하며,
같은 provider 종류의 endpoint가 여럿이어도 자동 fallback 없이 정확히 하나를 찾아야 한다.

## 결정

- `ModelRoute`는 선택적 `endpoint_alias`를 포함한다. OpenAI는 alias를 쓰지 않고 llama.cpp는
  alias를 필수로 하며, vLLM은 기존 F2 호환을 위해 alias 없는 route도 허용한다.
- 범용 생성 endpoint 주소록은 `AI_LLM_ENDPOINTS` JSON 배열로 받는다. 각 항목은 고유 alias,
  `vllm` 또는 `llama_cpp` provider, base URL과 API key 환경변수 이름을 가진다.
- API key 원문은 주소록에 넣지 않는다. 참조한 `AI_*_API_KEY` 환경변수가 없으면 설정을
  거절하고 설정·오류 표현에 Secret을 포함하지 않는다. self-hosted base URL에도 userinfo,
  query와 fragment를 허용하지 않는다.
- LLM registry는 `(provider, endpoint_alias)` exact match만 허용한다. alias route가 없을 때
  alias 없는 같은 provider로 fallback하지 않는다.
- 기존 OpenAI와 F2 vLLM은 `(provider, None)`으로 유지하고 범용 endpoint만 aliased 등록한다.
  embedding registry와 F2 STT 경로는 변경하지 않는다.
- llama.cpp는 OpenAI-compatible Chat Completions에 Pydantic JSON Schema를 전달하고 반환 문자열을
  Pydantic으로 다시 검증한다. 빈 본문·JSON/schema 위반은 기존 구조화 출력 repair 대상이며,
  diagnostics provider는 `llama_cpp`를 보존한다.
- SDK 자동 재시도와 생성기 최대 3회 repair 계약은 바꾸지 않는다.

## 결과

F2 RunPod 경로를 이관하지 않고도 F3가 OpenAI, aliased llama.cpp와 aliased vLLM을 같은 공개
계약으로 선택할 수 있다. 잘못된 provider·alias 조합은 네트워크 호출 전에 실패하며 다른
endpoint로 우회하지 않는다. GPU endpoint·Secret 주입과 shared dev 프로필 전환은 Infra 후속
작업이다.
