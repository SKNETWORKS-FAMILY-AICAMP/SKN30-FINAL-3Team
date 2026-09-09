---
status: 결정
updated: 2026-09-04
---

# F3 Backend–AI 공통 계약

이 문서는 F3 공통 버전·책임·진단·개인정보·오류 규칙의 정본이다. [포지션 카드](f3-ai-position-card.md) 또는 [중개 판정](f3-ai-brokerage.md) 중 현재 작업에 필요한 계약을 함께 읽는다.

모듈 경계 자체는 [ADR-0006](../decisions/ADR-0006-ai-backend-boundary.md)이 소유하며 이 계약은
그 경계 안의 구체 규격이다. HTTP 계약은 [contracts/api.md](api.md)에 있고 여기서 바꾸지 않는다.

코드 정본:

| 대상 | 위치 |
|---|---|
| 어휘와 DTO | `ai/src/brokerage_ai/f3/contracts.py` |
| 생성 Protocol | `ai/src/brokerage_ai/f3/ports.py` |
| 요청·결과 교차 검증 | `ai/src/brokerage_ai/f3/validation.py` |
| 모델 구조화 출력 schema | `ai/src/brokerage_ai/f3/model_output.py` |
| 프롬프트와 prompt version | `ai/src/brokerage_ai/f3/prompts.py` |
| 생성 구현과 workflow version | `ai/src/brokerage_ai/f3/generator.py` |
| Backend 앵커 종류 | `backend/src/domain/agent_execution/models.py` (`AnchorType`) |
| Backend cache key | `backend/src/domain/agent_execution/cache_key.py` |
| Backend 합성 입력 조립 | `backend/src/domain/agent_execution/snapshot.py` |
| Backend 생성·저장 유스케이스 | `backend/src/domain/agent_execution/anchor_card.py` |
| Backend 후보 카드 단계 | `backend/src/domain/agent_execution/candidate_cards.py` |
| 카드·가격·근거 ORM | `backend/src/domain/agent_execution/models.py` |
| 중개 판정 어휘와 DTO | `ai/src/brokerage_ai/f3/judgment_contracts.py` |
| 중개 판정 생성 Protocol | `ai/src/brokerage_ai/f3/judgment_ports.py` |
| 중개 판정 요청·결과 교차 검증 | `ai/src/brokerage_ai/f3/judgment_validation.py` |
| 중개 판정 모델 출력 schema | `ai/src/brokerage_ai/f3/judgment_model_output.py` |
| 중개 판정 프롬프트 | `ai/src/brokerage_ai/f3/judgment_prompts.py` |
| 중개 판정 생성 구현 | `ai/src/brokerage_ai/f3/judgment_generator.py` |
| Backend 중개 판정 조립·저장 유스케이스 | `backend/src/domain/agent_execution/judgment.py` |
| Backend 후보 판정·근거 ORM | `backend/src/domain/agent_execution/models.py` |

## 버전 축

| 축 | 값 | 의미 | 소유 |
|---|---|---|---|
| 계약 버전 | `position-card:v1` | DTO와 의미 규격의 버전 | AI |
| Prompt 버전 | `position-card-prompt:v1` | 프롬프트 원문의 버전 | AI |
| Workflow 버전 | `position-card-workflow:v1` | 생성 절차의 버전 | AI |
| Cache key 버전 | `position-card:v3` | 캐시 키 계산 방식의 버전 | Backend |
| 판정 계약 버전 | `brokerage-judgment:v1` | 중개 판정 DTO와 의미 규격의 버전 | AI |
| 판정 Prompt 버전 | `brokerage-judgment-prompt:v1` | 중개 판정 프롬프트 원문의 버전 | AI |
| 판정 Workflow 버전 | `brokerage-judgment-workflow:v1` | 중개 판정 절차의 버전 | AI |

각 값은 서로 다른 것을 버전하며 독립적으로 올라간다. 번호가 다른 것은 정상이다.

prompt·workflow 버전은 모델을 부르기 전에 cache key 입력으로 사용할 수 있어야 한다.
`PositionCardGenerator.versions`가 프레임워크 중립 `PositionCardGeneratorVersions`로 두 값을
먼저 제공하며 Provider SDK 객체와 DB의 모델 설정 식별자는 이 DTO에 담지 않는다.

## 책임 경계

Backend가 소유한다.

- 인증, brokerage 격리, lease와 attempt fencing
- F1 장부·상담 로그 조회와 Provider 전달용 입력 snapshot 조립
- 실사용 데이터의 개인정보 제거와 입력 privacy mode 표시
- 날짜 신호 계산
- cache key 계산과 캐시 조회
- AI 결과의 DB 현재 상태 재검증, 인용 offset 계산, 트랜잭션과 카드 저장
- 실행 상태 전이

AI가 소유한다.

- 프롬프트와 모델 구조화 출력
- 포지션 카드 요청·결과 DTO와 어휘
- 생성 facade의 공개 Protocol
- 요청·결과 교차 검증의 순수 규칙
- 모델 Provider와 모델 선택

Backend는 프롬프트 원문을 소유하지 않고 LangGraph를 import하지 않으며 Provider나 모델 ID를
직접 고르지 않는다. AI는 DB, SQLAlchemy, SQLModel, Session, Repository, FastAPI와 Backend의
`AgentRun` ORM 모델을 알지 않는다.

## 진단과 버전

`ProviderDiagnostics`를 재사용한다. `provider`, `model`, `request_id`, `latency_ms`,
`usage`(input/output/total token)만 담는다.

- Backend는 Provider와 모델을 직접 고르지 않는다.
- local·dev 합성 프로필은 [ADR-0027](../decisions/ADR-0027-bedrock-gpt56-luna-dev-poc.md)가
  정한다. runtime은 OpenAI와 기존 F2 vLLM을 alias 없이, 범용 Bedrock·vLLM·llama.cpp를
  provider·`endpoint_alias` exact match로 routing한다.
  등록되지 않은 조합은 다른 endpoint로 fallback하지 않는다.
- prod 최종 모델·통과 기준은 평가 전까지 미확정이다.
- SDK 자동 재시도 정책은 바꾸지 않는다 (AI ADR-0001).
- 프롬프트 원문과 전체 모델 응답은 diagnostics에 넣지 않는다.
- Secret, token, 인증 헤더는 넣지 않는다.

`prompt_version`과 `workflow_version`은 AI가 소유하는 문자열이며 비어 있을 수 없다. 현재 값은
각각 `position-card-prompt:v1`, `position-card-workflow:v1`이다. Backend는 이 두 값을 cache key
입력으로만 쓰고 의미를 해석하지 않는다.

## 개인정보 경계

수집 목적: 장부와 상담 로그를 바탕으로 당사자의 협상 포지션을 구조화한다.

| 구분 | 항목 |
|---|---|
| Backend → AI 전달 가능 | 내부 anchor·card ID, 구조화된 매물·구입 조건, 날짜 신호, Provider 전달용 상담 내용과 검증된 카드 근거 인용, 내부 `interaction_id`, source identity, 입력 privacy mode |
| 전달 금지 | 실사용자 성명, 로그인 ID, 전화번호, 이메일, 생년월일, 인증·세션·CSRF 정보, `requested_by`, 치환 대응표, Secret, 프롬프트 원문 전체, 반대편 당사자 데이터. 실제 인물과 무관한 합성 케이스는 ADR-0014 예외를 따름 |
| 저장 | Backend가 검증한 구조화 포지션 카드, 필요한 근거 인용, 안전한 모델 진단, 버전 정보 |
| 로그 금지 | 전체 프롬프트, 전체 모델 원문 응답, 상담 로그 전체 원문, 성명·연락처, 토큰·인증 헤더 |

실행 제어 값(`run_id`, `lease_owner`, `lease_expires_at`, `attempt_count`)과 DB 객체
(Session, Repository, `AgentRun`, SQLModel)는 Backend 내부 정보이며 AI 공개 계약에 넣지 않는다.

### 외부 Provider 전송

합성·비식별 local·dev에서는 ADR-0026·0027의 allowlist 프로필을 사용할 수 있다.
local은 직접 OpenAI `gpt-5.6-luna`를 사용하고, 공유 dev는 Bedrock doctor 통과 뒤
`dev-bedrock-gpt56-luna`를 명시 적용하고 합성 smoke로 검증한다. 실패 시 OpenAI key와
runtime이 배포된 환경에서만 `local-openai`를 명시 재적용하고, 그렇지 않으면 Worker를
정지한다. Qwen 프로필은 GPU endpoint 배포 전에 활성하지
않는다. 요청·응답 원문을 로깅하지 않는 기존 제약은 유지한다.

Bedrock dev는 서울 `bedrock-runtime`에 SigV4로 요청하지만 모델은
`global.openai.gpt-5.6-luna` Global cross-Region inference profile이다. 실제 처리 위치를 서울로
한정할 수 없으므로 합성·비식별 입력만 허용한다. Structured Outputs를 지원하지 않는 Provider
출력은 AI가 JSON 지시 후 Pydantic으로 재검증하며 계약 위반은 제한된 repair 뒤 fail closed한다.

실제 개인정보는 서울 리전 자체 호스팅 vLLM이나 Bedrock이라도 즉시 허용되지 않는다. prod
인증·접근 통제, 종단 간 TLS, 전송·저장 암호화, 원문 비로깅, 보존·삭제 정책이
모두 승인되어야 한다. Global cross-Region Provider를 쓰는 경우에는 목적지 리전과 계정 수준
보존 모드도 승인해야 한다. 외부 Provider를 쓰는 경우에는 이 조건에 더해 Backend가
개인정보를 제거한 `MASKED` 입력만 전달한다 (F3-SE-02).

### 원문 보관 요구와의 충돌

- 요구사항 출처 F3-SE-03에는 프롬프트 원문과 응답을 실행 로그로 보관하라는 요구가 있다.
- 현재 승인된 [개인정보 정책](../privacy/policy.md)은 전체 프롬프트를 로그에 남기지 않는다.
- **승인된 개인정보 정책을 우선한다.** 전체 프롬프트와 전체 모델 응답을 보관하지 않는다.
- 재현에 필요한 정보는 구조화·redacted snapshot, 모델·프롬프트·워크플로 버전,
  token/latency metadata로 제한한다.
- 이 정책을 바꾸려면 별도 개인정보 결정이 필요하다.

## 오류와 재시도 경계

- Provider 오류는 AI의 `ProviderError` 계층으로 표현하고 `retryable` 여부를 함께 준다.
- 결과가 요청과 맞지 않으면 `PositionCardContractError` 또는
  `BrokerageJudgmentContractError`이며 재시도로 해결되지 않는다.
- 재시도 횟수와 backoff는 Worker가 소유한다. AI SDK 자동 재시도는 꺼져 있다.
- 검증에 실패한 결과로 카드를 저장하지 않는다. 조용히 근거를 지우고 성공으로 위장하지 않는다.
