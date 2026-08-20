---
status: 결정
updated: 2026-08-20
---

# F3 포지션 카드 Backend–AI 계약

이 문서가 F3 포지션 카드의 어휘, 입력, 결과, 근거와 개인정보 경계의 정본이다. 모듈 경계
자체는 [ADR-0006](../decisions/ADR-0006-ai-backend-boundary.md)이 소유하며 이 계약은 그
경계 안의 구체 규격이다. HTTP 계약은 [contracts/api.md](api.md)에 있고 여기서 바꾸지 않는다.

코드 정본:

| 대상 | 위치 |
|---|---|
| 어휘와 DTO | `ai/src/brokerage_ai/f3/contracts.py` |
| 생성 Protocol | `ai/src/brokerage_ai/f3/ports.py` |
| 요청·결과 교차 검증 | `ai/src/brokerage_ai/f3/validation.py` |
| Backend 앵커 종류 | `backend/src/domain/agent_execution/models.py` (`AnchorType`) |
| Backend cache key | `backend/src/domain/agent_execution/cache_key.py` |

## 두 버전 축

| 축 | 값 | 의미 | 소유 |
|---|---|---|---|
| 계약 버전 | `position-card:v1` | DTO와 의미 규격의 버전 | AI |
| Cache key 버전 | `position-card:v2` | 캐시 키 계산 방식의 버전 | Backend |

둘은 서로 다른 것을 버전하며 독립적으로 올라간다. 번호가 다른 것은 정상이다.

## negotiation_side 어휘

정본 값은 두 개다.

| 값 | 의미 |
|---|---|
| `LISTING` | 세대·매물 보유자 측을 대리하는 포지션 카드 |
| `REQUIREMENT` | 구입장 손님 측을 대리하는 포지션 카드 |

`CUSTOMER`, `BUYER`, `SELLER`, `PROPERTY`, `매물`, `손님`과 그 밖의 동의어는 쓰지 않는다.
저장값, cache key와 Backend–AI 계약값은 위 두 값으로 고정한다. 화면 한국어 표시는 별도
표시 매핑으로 처리하고 저장 어휘로 되돌리지 않는다.

Backend `AnchorType.LISTING`·`AnchorType.REQUIREMENT`와 값이 정확히 같아야 하며
`backend/tests/architecture/test_f3_ai_contract.py`가 이를 강제한다. 이 결정으로 OQ-012를
종료했다.

## 값 어휘와 화면 표기

DB 기본값(`negotiation_intent = 'UNKNOWN'`, `urgency = 'UNKNOWN'`,
`contactability_status = 'CAUTION'`)이 그대로 유효한 계약값이다. 같은 의미에 복수 동의어를
두지 않고, 자유 문자열로 받지 않으며, 잘못된 값은 Pydantic이 거절한다.

| 항목 | 계약값 | 화면 한국어 |
|---|---|---|
| intent | `PRESENT` | 있음 |
| intent | `ABSENT` | 없음 |
| intent | `WITHDRAWN` | 철회 |
| intent | `UNKNOWN` | 불명 |
| urgency | `URGENT` | 급함 |
| urgency | `NORMAL` | 보통 |
| urgency | `RELAXED` | 여유 |
| urgency | `UNKNOWN` | 불명 |
| contactability | `GOOD` | 양호 |
| contactability | `CAUTION` | 주의 |
| contactability | `UNREACHABLE` | 불가 |
| contactability | `UNKNOWN` | 불명 |
| evidence | `QUOTE` | 상담 로그 직접 인용 |
| evidence | `INFERENCE` | 추정 |

판단이 불가한 항목은 비우지 않고 `UNKNOWN`을 쓴다 (F3-PC-01). `UNKNOWN`은 누락이 아니라
명시적 판정이다.

`price_kind`는 어떤 장부 금액을 말하는지 고정한다. 새 금액 항목을 만들지 않는다.

| price_kind | 허용 측 | 장부 출처 |
|---|---|---|
| `SALE` | `LISTING` | `property_listing.sale_price` |
| `JEONSE` | `LISTING` | `property_listing.jeonse_deposit_amount` |
| `MONTHLY_RENT` | `LISTING` | `property_listing.monthly_rent_deposit_amount` + `monthly_rent_amount` |
| `BUDGET` | `REQUIREMENT` | `property_requirement.max_budget_amount` |

## 책임 경계

Backend가 소유한다.

- 인증, brokerage 격리, lease와 attempt fencing
- F1 장부·상담 로그 조회와 개인정보를 제거한 입력 snapshot 조립
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

## 요청 계약

`PositionCardGenerationRequest`

| 필드 | 의미 |
|---|---|
| `contract_version` | `position-card:v1` 고정 |
| `negotiation_side` | 대리하는 측 |
| `anchor_id` | 대상 식별자. `anchor`의 대상 ID와 같아야 한다 |
| `source` | `SourceIdentity`. Backend가 준 입력 snapshot 신원 |
| `anchor` | `LISTING`/`REQUIREMENT` 중 하나의 context |
| `date_signals` | Backend가 계산한 날짜 신호 |
| `consultation_logs` | 개인정보를 제거한 상담 로그. `interaction_id`는 중복될 수 없다 |

`SourceIdentity`는 `data_version`, `interaction_count`, `last_interaction_at`,
`max_interaction_id`를 담는다. 모델이 판단하는 값이 아니라 Backend가 제공하는 불변 snapshot
식별자이며 Backend cache key와 저장 단계 fencing이 같은 값을 쓴다. 시각 하나로는 과거 시각
로그 추가와 로그 무효화를 구분하지 못해 건수와 최대 ID를 함께 싣는다.

`consultation_logs`는 해당 snapshot의 유효 상담 로그 전량이다. 요청 DTO는 로그의 실제 건수,
최대 `interaction_id`, 마지막 `interaction_at`이 `SourceIdentity`와 정확히 같은지 검증한다.
따라서 일부 로그만 전달하면서 전체 snapshot의 신원을 붙이는 요청은 허용하지 않는다.

### LISTING과 REQUIREMENT 입력 격리

`anchor`는 `negotiation_side`를 discriminator로 쓰는 Pydantic discriminated union이다. 두
context는 서로의 필드를 갖지 않고 `extra="forbid"`이므로 반대편 값은 타입 수준에서 거절된다
(F3-LA-02, F3-CA-02).

| LISTING context 필드 | F1 출처 |
|---|---|
| `listing_id`, `unit_id`, `listing_status`, `received_at` | `property_listing` |
| `is_sale_available`, `sale_price` | `property_listing` |
| `is_jeonse_available`, `jeonse_deposit_amount` | `property_listing` |
| `is_monthly_rent_available`, `monthly_rent_deposit_amount`, `monthly_rent_amount` | `property_listing` |
| `price_raw_text`, `handover_condition` | `property_listing` |
| `building_number`, `unit_number`, `floor_number`, `orientation` | `property_unit` |
| `pyeong`, `exclusive_area_sqm`, `supply_area_sqm` | `property_unit` |
| `unit_type`, `lifecycle_status` | `property_unit` |
| `tenancy_status`, `current_deposit_amount`, `current_monthly_rent_amount` | `property_unit` |
| `tenancy_expiry_date`, `tenancy_raw_text` | `property_unit` |
| `complex_name` | `property_complex.name` |

| REQUIREMENT context 필드 | F1 출처 |
|---|---|
| `requirement_id`, `demand_type`, `status`, `received_at` | `property_requirement` |
| `classification`, `workflow_stage` | `property_requirement` |
| `min_budget_amount`, `max_budget_amount`, `budget_raw_text` | `property_requirement` |
| `desired_pyeongs`, `min_area_sqm`, `max_area_sqm`, `area_requirement_raw_text` | `property_requirement` |
| `desired_move_in_date`, `move_in_date_raw_text` | `property_requirement` |
| `request_expiry_date`, `current_tenancy_expiry_date` | `property_requirement` |
| `desired_complex_names` | `property_requirement_complex` + `property_complex.name` |

`memo`, `custom_fields`와 대출 금액은 계약에 넣지 않는다. 자유 메모에는 성명·연락처가 섞일
수 있고 대출 금액은 판정에 필요한 최소 항목이 아니다 (F3-SE-01). `*_raw_text`는 사용자 입력
원문이므로 Backend가 상담 내용과 같은 마스킹을 적용한 뒤 전달한다.

`demand_type`, `status`, `classification`, `workflow_stage`, `listing_status`,
`tenancy_status`, `unit_type`, `lifecycle_status`는 F1이 아직 값 목록을 확정하지 않은 장부
표기값이라 문자열로 통과시킨다. 카드 판정 어휘가 아니다.

### 상담 로그 입력

`ConsultationLogInput`은 `interaction_id`, `interaction_at`, `channel`,
`counterparty_role`, `interaction_result`, `masked_content`를 담는다. 각각
`client_interaction`의 `id`, `interaction_at`, `interaction_channel`, `counterparty_role`,
`interaction_result`, `interaction_content`에서 온다.

`masked_content`는 **DB 원문이 아니다.** Backend가 AI 호출 전에 성명, 전화번호, 이메일,
로그인 ID, 생년월일을 치환하거나 마스킹한 결과만 전달한다. 치환 대응표는 요청, 결과, 로그와
DB snapshot 어디에도 넣지 않는다.

### 날짜 신호

날짜 계산은 AI가 하지 않는다 (F3-SQ-05, F3-PC-04). Backend가 계산한 `DateSignals`를 전달한다.

`as_of`(기준 시각), `days_until_tenancy_expiry`, `days_until_desired_move_in`,
`days_until_request_expiry`, `days_since_last_contact`, `days_since_received`,
`hard_deadline_candidate`로 구성한다. 경과일은 이미 지난 기한을 뜻하는 음수를 허용한다.
현재 데이터로 계산할 수 없는 신호는 null이며 필수로 강제하지 않는다.

## 결과 계약

`PositionCardGenerationResult`는 `contract_version`, `target`, `analysis`,
`prompt_version`, `workflow_version`, `diagnostics`를 담는다.

`PositionCardAnalysis`는 F3-PC-01의 항목을 모두 표현한다.

| 항목 | 타입 |
|---|---|
| `intent` | `IntentAssessment` (값 + 근거 1건 이상) |
| `price` | `PriceAssessment` 튜플. `price_kind`는 중복될 수 없다 |
| `urgency` | `UrgencyAssessment` (값 + 근거 1건 이상) |
| `timing` | `TimingAssessment` (`constraints`, `hard_deadline`) |
| `flexible` | `PositionCondition` 튜플 |
| `inflexible` | `PositionCondition` 튜플 |
| `contactability` | `ContactabilityAssessment` (상태 + note + 근거 1건 이상) |

`PositionCondition`은 `description`과 근거 1건 이상을 함께 갖는다. 근거 없는 양보 조건과
시점 제약은 만들 수 없다 (F3-PC-05).

`contactability`는 연락처가 아니라 상담 이력과 최종 접촉 경과에 대한 판정이다 (F3-PC-06).
전화번호와 이메일은 결과 어느 필드에도 담지 않는다.

### target과 source 소유권

`negotiation_side`, `anchor_id`, `data_version`, `interaction_count`,
`last_interaction_at`, `max_interaction_id`, `cache_key`, `generated_at`은 모델이 만들거나
고치는 값이 아니다.

- `PositionCardTarget`은 `PositionCardTarget.from_request()`로 요청에서 결정적으로 복사한다.
- 모델 구조화 출력이 대상 ID나 source identity를 만들게 하지 않는다.
- `cache_key`는 Backend가 계산하며 결과 DTO에 없다.
- `generated_at`은 Backend 또는 DB가 저장 시점에 정하며 결과 DTO에 없다.

### 가격 불변식

- `stated_amount`(와 월세의 `stated_monthly_amount`)는 Backend 입력값이며 AI가 바꾸지 않는다.
- `estimated_amount`는 없을 수 있다.
- 추정가가 표기가와 다르면 `basis` 근거가 반드시 있어야 한다. 없으면 거절한다 (F3-PC-03).
- 금액은 원 단위 정수이고 음수를 허용하지 않는다.
- `*_monthly_amount`는 `MONTHLY_RENT`에서만 허용한다.
- LISTING의 `price_kind`는 대응하는 `is_sale_available`, `is_jeonse_available`,
  `is_monthly_rent_available`가 참인 거래 유형만 허용한다. 비활성 유형에 남은 과거 금액을
  포지션 카드 가격으로 사용하지 않는다.

### Timing 불변식

- `hard_deadline`은 Backend가 준 날짜 신호를 근거로 한다. AI가 임의 날짜 산수를 하지 않는다.
- 값이 있으면 `DateSignals.hard_deadline_candidate`와 정확히 같아야 하며, AI는 후보와 다른
  날짜를 만들 수 없다.
- `constraints`가 하나도 없으면 `hard_deadline`을 세울 수 없다.
- 날짜가 없으면 null이다.

## Evidence 규칙

| kind | 필수값 | 금지 |
|---|---|---|
| `QUOTE` | `interaction_id`, `quote_text` | — |
| `INFERENCE` | `note` | `interaction_id`, `quote_text` |

- 아무 근거도 없는 카드 항목은 거절한다 (F3-CM-02).
- AI는 quote offset을 만들지 않는다. `Evidence`에 offset 필드가 없다.
- Backend가 저장 전에 `quote_text`가 해당 마스킹 상담 로그에 실제로 존재하는지 확인하고,
  실제 원문 기준 offset을 계산해 `negotiation_position_evidence`에 넣는다.

구조 validation과 요청·결과 간 validation을 구분한다.

| 계층 | 위치 | 확인 |
|---|---|---|
| 구조 | Pydantic DTO | 어휘, 필수값, 빈 문자열, 음수, extra field, kind별 필수값 |
| 요청·결과 | `validate_generation_result()` | 계약 버전, 대상과 side 일치, source identity 일치, hard deadline이 Backend 날짜 신호와 같은지, 인용 로그가 요청 범위 안인지, 인용문이 마스킹 본문에 실재하는지, price_kind가 해당 측과 활성 거래 유형에 허용되는지, 표기 금액이 장부와 같은지 |
| DB 현재 상태 | Backend (후속 구현) | lease 소유권, 입력 버전, source identity 재대조, tenant 격리, offset 계산 |

`validate_generation_result()`는 Session이나 Repository를 받지 않는다.

## 진단과 버전

`ProviderDiagnostics`를 재사용한다. `provider`, `model`, `request_id`, `latency_ms`,
`usage`(input/output/total token)만 담는다.

- Backend는 Provider와 모델을 직접 고르지 않는다.
- 실제 모델 ID와 운영 Provider는 이번 작업에서 확정하지 않았다. AI-OQ-001, AI-OQ-002,
  AI-OQ-003은 그대로 미해결이다.
- SDK 자동 재시도 정책은 바꾸지 않는다 (AI ADR-0001).
- 프롬프트 원문과 전체 모델 응답은 diagnostics에 넣지 않는다.
- Secret, token, 인증 헤더는 넣지 않는다.

`prompt_version`과 `workflow_version`은 AI가 소유하는 문자열이며 비어 있을 수 없다. 실제
값 체계는 프롬프트가 생기는 다음 구현에서 정한다. Backend는 이 두 값을 cache key 입력으로만
쓰고 의미를 해석하지 않는다.

## 개인정보 경계

수집 목적: 장부와 상담 로그를 바탕으로 당사자의 협상 포지션을 구조화한다.

| 구분 | 항목 |
|---|---|
| Backend → AI 전달 가능 | 내부 anchor ID, 구조화된 매물·구입 조건, 날짜 신호, 개인정보를 제거한 상담 내용, 내부 `interaction_id`, source identity |
| 전달 금지 | 성명, 로그인 ID, 전화번호, 이메일, 생년월일, 인증·세션·CSRF 정보, `requested_by`, 치환 대응표, Secret, 프롬프트 원문 전체, 반대편 당사자 데이터 |
| 저장 | Backend가 검증한 구조화 포지션 카드, 필요한 근거 인용, 안전한 모델 진단, 버전 정보 |
| 로그 금지 | 전체 프롬프트, 전체 모델 원문 응답, 상담 로그 전체 원문, 성명·연락처, 토큰·인증 헤더 |

실행 제어 값(`run_id`, `lease_owner`, `lease_expires_at`, `attempt_count`)과 DB 객체
(Session, Repository, `AgentRun`, SQLModel)는 Backend 내부 정보이며 AI 공개 계약에 넣지 않는다.

### 외부 Provider 전송

이번 작업은 외부 Provider 전송을 승인하지 않는다. 실제 Provider, 리전과 저장 여부는
AI-OQ-001~003과 별도 운영 결정 전까지 미확정이다. 외부 Provider를 쓰게 되더라도 Backend가
개인정보를 제거한 입력만 전달한다는 조건은 유지한다 (F3-SE-02).

### 원문 보관 요구와의 충돌

- 요구사항 출처 F3-SE-03에는 프롬프트 원문과 응답을 실행 로그로 보관하라는 요구가 있다.
- 현재 승인된 [개인정보 정책](../privacy/policy.md)은 전체 프롬프트를 로그에 남기지 않는다.
- **승인된 개인정보 정책을 우선한다.** 전체 프롬프트와 전체 모델 응답을 보관하지 않는다.
- 재현에 필요한 정보는 구조화·redacted snapshot, 모델·프롬프트·워크플로 버전,
  token/latency metadata로 제한한다.
- 이 정책을 바꾸려면 별도 개인정보 결정이 필요하다.

## 오류와 재시도 경계

- Provider 오류는 AI의 `ProviderError` 계층으로 표현하고 `retryable` 여부를 함께 준다.
- 결과가 요청과 맞지 않으면 `PositionCardContractError`이며 재시도로 해결되지 않는다.
- 재시도 횟수와 backoff는 Worker가 소유한다. AI SDK 자동 재시도는 꺼져 있다.
- 검증에 실패한 결과로 카드를 저장하지 않는다. 조용히 근거를 지우고 성공으로 위장하지 않는다.

## 구현 범위

### 이번 구현 범위 (`구현됨`)

- `negotiation_side`, intent, urgency, contactability, evidence, price_kind 어휘
- 계약 버전 `position-card:v1`
- 요청·결과 DTO와 LISTING/REQUIREMENT 입력 격리
- `PositionCardGenerator` Protocol
- 요청·결과 교차 검증 순수 함수
- Backend `AnchorType`과의 값 일치 계약 테스트

### 아직 구현하지 않음 (`계획됨`)

- 프롬프트와 실제 모델 호출
- 포지션 카드 생성 알고리즘과 LangGraph workflow
- Backend의 F1 snapshot 조립과 상담 로그 마스킹
- 카드와 근거의 DB 저장, quote offset 계산
- `ANCHOR_READY` 상태 전이
- SQL 후보 추출, 후보 카드, 중개 판정
- Worker polling과 `WORKER_ENABLED=true`

### 미확정

- 실제 모델 ID와 운영 Provider (AI-OQ-001, AI-OQ-002, AI-OQ-003)
- `prompt_version`·`workflow_version`의 실제 값 체계
- LangGraph checkpoint 저장 계약 (AI-OQ-004)
