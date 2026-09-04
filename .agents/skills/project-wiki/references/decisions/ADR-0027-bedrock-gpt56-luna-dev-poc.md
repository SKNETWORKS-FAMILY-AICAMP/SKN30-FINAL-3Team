---
status: 결정
updated: 2026-09-04
---

# ADR-0027: 범용 생성 모델은 Bedrock GPT-5.6 Luna로 dev POC한다

- 상태: 승인됨·코드 구현, AWS 미적용
- 결정일: 2026-09-04
- 부분 대체: [ADR-0026](ADR-0026-general-ai-provider-and-model-profiles.md)의 환경별 활성
  Provider, GPU Infra 우선순위와 IMDSv2 hop limit 1 조항
- 관련 계약: [F3 AI 계약](../contracts/f3-ai.md),
  [개인정보 정책](../privacy/policy.md)

## 맥락

F3는 이미 OpenAI Responses 기반 구조화 생성과 제한된 repair 경로를 사용한다. AWS 잔여 금액과
2026-09-23 종료 시점을 고려하면 범용 모델의 첫 공유 dev POC는 GPU EC2를 새로 구성하는 것보다
Bedrock의 관리형 온디맨드 모델을 사용하는 편이 빠르다. Amazon Bedrock은 GPT-5.6 Luna를
`bedrock-runtime`의 OpenAI-compatible Responses API로 제공하지만 서울 리전에서는
`global.openai.gpt-5.6-luna` Global cross-Region inference profile을 사용한다.

Bedrock의 GPT-5.6 Luna는 Structured Outputs를 지원하지 않는다. 따라서 OpenAI 직접 호출의
`responses.parse()`와 같은 서버측 schema 강제를 그대로 기대할 수 없고, JSON 생성 지시와
로컬 검증·repair가 필요하다.

## 결정

### 환경과 모델

capability별 활성 모델 하나, provider·endpoint alias exact routing, 자동 fallback 금지 계약은
유지한다.

| 환경 | 활성 경로 | 상태 |
|---|---|---|
| local | OpenAI `gpt-5.6-luna` | 개발 기본값 |
| 공유 dev | Bedrock `global.openai.gpt-5.6-luna` | Infra apply·doctor 후 명시적 seed로 전환하고 합성 smoke로 검증 |
| dev 비교 | Qwen llama.cpp·vLLM 프로필 | 코드와 seed만 보존, GPU Infra 보류 |
| prod | 미확정 | 품질·지연·비용·개인정보 gate 통과 전 승격 금지 |

새 `dev-bedrock-gpt56-luna` seed 프로필은 `bedrock` Provider,
`global.openai.gpt-5.6-luna` 모델, `general-dev-bedrock` endpoint alias를 사용한다.
기존 Qwen BnB·GGUF provenance와 allowlist 프로필은 삭제하지 않는다.

### 인증과 runtime

- dev 애플리케이션 EC2 Instance Role로 요청마다 AWS SigV4 서명한다. 정적 Bedrock API key는
  생성·저장·주입하지 않는다.
- `AI_LLM_ENDPOINTS`의 Bedrock 항목은 alias, provider와 AWS 리전만 받는다. runtime은 공식
  `bedrock-runtime` URL을 조립하며 임의 host와 Secret 필드를 거절한다.
- Bedrock adapter는 비스트리밍 Responses 요청에 항상 `store=false`를 명시한다.
- output schema는 모델 지시에 포함하고 응답 JSON을 Pydantic으로 재검증한다. JSON·schema
  위반은 AI ADR-0003의 최대 3회 생성 repair에 포함하고 끝까지 실패하면 fail closed한다.
- `ProviderDiagnostics.provider`는 OpenAI-compatible wire format과 무관하게 `bedrock`으로 남긴다.
- 서울 dev EC2의 IMDSv2 token 필수 설정은 유지하고 hop limit은 2로 올린다. 같은 EC2의
  컨테이너가 Instance Role에 접근할 수 있는 위험을 수용하므로 role은 Luna 비스트리밍 호출에
  필요한 최소 권한만 추가한다. 이 예외는 합성 dev에만 허용하며 prod identity 결정이 아니다.
- Launch Template 변경은 기존 ASG 인스턴스를 자동 교체하지 않는다. Terraform apply 후
  공유 dev 중단을 확인하고 `dev-stop` → `dev-start`로 새 EC2를 만든 뒤 Backend를 배포하고
  hop limit 2·SSM Online을 확인해야 `bedrock-doctor`를 실행할 수 있다.

### 적용과 개인정보 gate

Terraform과 애플리케이션 배포만으로 DB 활성 모델을 자동 변경하지 않는다. Instance Role로 실행한
`bedrock-doctor`가 성공하면 운영자가 Bedrock seed 프로필을 명시 적용한 뒤 합성 F3 smoke로
실제 추론·JSON 검증·repair 경로를 확인한다. 실패하면 기존 OpenAI key와 runtime이
배포된 환경에서만 OpenAI 프로필을 명시 재적용해 수동 rollback한다. OpenAI가 준비되지
않았다면 Worker를 정지하고 Bedrock 설정을 복구하며 요청 중 자동 fallback하지 않는다.

Global cross-Region inference는 요청을 다른 상용 AWS 리전에서 처리할 수 있다. 공유 dev에는
실제 인물과 연결되지 않는 합성·비식별 입력만 허용한다. 실제 개인정보를 사용하는 prod는
목적지 리전, 계정 수준 데이터 보존 모드, Backend `MASKED` 입력, 인증·종단 간 TLS·암호화,
원문 비로깅과 보존·삭제 정책을 모두 승인하기 전까지 차단한다.

## 구현 범위

반영한다.

- AI Bedrock Provider, SigV4 Responses adapter와 provider별 endpoint 설정
- Backend route 검증과 합성 seed Bedrock 프로필
- dev EC2 최소 Bedrock IAM, IMDSv2 hop limit 2와 공개 endpoint 설정
- renderer의 OpenAI key 무조건 요구 제거와 합성 Bedrock doctor
- 계약·개인정보·환경·운영 문서

반영하지 않는다.

- GPU EC2·EBS cache와 llama.cpp·vLLM endpoint 배포
- F2 RunPod lifecycle 변경
- Bedrock 자동 fallback, A/B 분배와 streaming
- prod Provider 승인과 실제 개인정보 사용

## 근거

- [Amazon Bedrock GPT-5.6 Luna model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-56-luna.html)
- [Amazon Bedrock Responses API](https://docs.aws.amazon.com/bedrock/latest/userguide/bedrock-mantle.html)
- [Amazon Bedrock API keys](https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys.html)
- [Amazon Bedrock global cross-Region inference](https://docs.aws.amazon.com/bedrock/latest/userguide/global-cross-region-inference.html)
- [Amazon Bedrock data retention](https://docs.aws.amazon.com/bedrock/latest/userguide/data-retention.html)
- [OpenAI GPT-5.6 Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna)

## 결과

local과 dev가 같은 Luna 계열 모델을 사용하면서도 실제 provider와 인증·출력 보장 차이를
진단값과 adapter 경계에 보존한다. Bedrock POC는 별도 GPU 수명주기 없이 기존 dev EC2에서
수행할 수 있지만, Global 처리와 hop limit 2를 승인한 것은 합성 dev 범위뿐이다.
