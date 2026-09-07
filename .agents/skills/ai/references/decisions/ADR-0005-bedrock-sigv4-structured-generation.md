---
status: 결정
updated: 2026-09-04
---

# ADR-0005: Bedrock 범용 생성은 SigV4 Responses와 로컬 검증을 사용한다

- 상태: 승인됨·코드 구현, AWS 미검증
- 결정일: 2026-09-04
- 상위 결정: [프로젝트 ADR-0027](../../../project-wiki/references/decisions/ADR-0027-bedrock-gpt56-luna-dev-poc.md)
- 부분 대체: [ADR-0004](ADR-0004-aliased-llm-endpoint-routing.md)의 범용 endpoint
  Provider·인증 목록

## 맥락

공유 dev의 첫 범용 모델 POC는 Bedrock GPT-5.6 Luna를 사용한다. Bedrock Runtime은
OpenAI-compatible Responses API를 제공하지만 OpenAI GPT-5.6 Luna의 Structured Outputs를
지원하지 않는다. OpenAI SDK는 Bedrock API key를 요구하므로 정적 key 없이 EC2 Instance Role을
사용하려면 HTTP 요청을 AWS SigV4로 직접 서명해야 한다.

## 결정

- `bedrock`을 실제 Provider 종류로 구분하며 DB route와 진단값에서 `openai`로 위장하지 않는다.
- `AI_LLM_ENDPOINTS`의 Bedrock 항목은 alias, `provider=bedrock`, AWS 리전만 받는다. 임의 URL,
  API key와 Secret 참조를 거절하고 공식
  `https://bedrock-runtime.<region>.amazonaws.com/openai/v1` URL을 runtime이 만든다.
- Bedrock adapter는 botocore 기본 credential chain에서 호출 시점의 임시 자격 증명을 읽고
  `bedrock` service와 설정 리전으로 Responses HTTP 요청을 SigV4 서명한다. 자격 증명 원문과
  Authorization header는 설정, 오류와 진단에 포함하지 않는다.
- 요청은 비스트리밍이며 `store=false`를 항상 보낸다. Pydantic JSON Schema는 모델 지시에
  포함하고 결과 문자열은 `model_validate_json()`으로 재검증한다.
- JSON·schema 위반과 incomplete 응답은 `ProviderOutputInvalidError`로 변환해 ADR-0003의 최대
  3회 repair에 포함한다. 전송 timeout, throttling과 일시 장애는 재시도 가능 오류로, HTTP
  인증·권한 실패는 설정 오류로, 모델의 content refusal과 잘못된 응답 구조는 각각 별도
  비재시도 오류로 안전하게 변환한다.
- 같은 runtime의 Bedrock alias들은 하나의 async HTTP client와 credential loader를 공유한다.
  provider·alias registry의 exact match와 자동 fallback 금지 계약은 유지한다.
- F2 vLLM, embedding, STT와 비활성 Qwen llama.cpp·vLLM 비교 경로는 변경하지 않는다.

## 결과

AI runtime은 정적 Bedrock API key 없이 Instance Role로 GPT-5.6 Luna를 호출할 수 있고, 서버측
Structured Outputs가 없는 환경에서도 기존 F3의 검증·repair·fail-closed 경계를 유지한다.
코드와 단위 테스트 완료는 실제 AWS model access, IAM, IMDS와 cross-Region 호출 성공을 뜻하지
않으며 이는 Infra doctor와 합성 smoke로 별도 확인한다.
