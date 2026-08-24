---
status: 결정
updated: 2026-08-24
---

# F3 포지션 카드·중개 판정 Backend–AI 계약

이 문서가 F3 포지션 카드와 중개 판정의 어휘, 입력, 결과, 근거와 개인정보 경계의 정본이다.
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

### 후보 카드 재사용 경계

후보 포지션 카드는 별도 AI 계약이나 생성기를 만들지 않고 앵커 카드와 같은
`PositionCardGenerator`와 검증·저장 경로를 쓴다. 다른 것은 실행의 앵커가 아닌 결정적 SQL
후보 snapshot의 상위 15건을 대상으로 하고, 앵커와 반대인 `negotiation_side`를 쓴다는 점뿐이다.

- 각 후보의 현재 `row_version`, 상담 범위 identity와 입력 fingerprint를 준비·저장 시점에
  다시 확인한다.
- 같은 대상·입력·모델·프롬프트·워크플로의 유효한 캐시가 있으면 모델을 호출하지 않는다.
- 후보 카드는 child 실행을 만들지 않고 루트 `agent_run`에 귀속한다.
- 후보를 순차 처리하고 전부 확보한 뒤에만 `CANDIDATE_CARDS_READY`로 전이한다. 중간에 실패하면
  이미 저장된 카드는 유효한 캐시로 남지만 상태는 `CANDIDATES_READY`를 유지한다.
- 후보가 0건이면 모델을 호출하지 않고 빈 카드 목록을 기록한 뒤 상태를 전이한다.

이 단계도 ADR-0014의 `SYNTHETIC_PROTOTYPE` 입력만 허용한다. 실사용 F1 마스킹이나 외부
Provider 전송을 새로 승인하지 않는다.

## 요청 계약

`PositionCardGenerationRequest`

| 필드 | 의미 |
|---|---|
| `contract_version` | `position-card:v1` 고정 |
| `input_privacy_mode` | `SYNTHETIC_PROTOTYPE` 또는 `MASKED`. Provider 전달 안전성의 근거 |
| `negotiation_side` | 대리하는 측 |
| `anchor_id` | 대상 식별자. `anchor`의 대상 ID와 같아야 한다 |
| `target_label` | Backend가 구조화 장부값으로 만든 비식별 표시 라벨 |
| `source` | `SourceIdentity`. Backend가 준 입력 snapshot 신원 |
| `anchor` | `LISTING`/`REQUIREMENT` 중 하나의 context |
| `date_signals` | Backend가 계산한 날짜 신호 |
| `consultation_logs` | Provider 전달용 상담 로그. `interaction_id`는 중복될 수 없다 |

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
| `party_roles` | 현재 유효한 세대 관계의 비식별 역할·대표·공동명의 여부 |
| `client_party_role` | 의뢰인의 세대 관계상 역할. 식별자는 싣지 않음 |

| REQUIREMENT context 필드 | F1 출처 |
|---|---|
| `requirement_id`, `demand_type`, `status`, `received_at` | `property_requirement` |
| `classification`, `workflow_stage` | `property_requirement` |
| `min_budget_amount`, `max_budget_amount`, `budget_raw_text` | `property_requirement` |
| `desired_pyeongs`, `min_area_sqm`, `max_area_sqm`, `area_requirement_raw_text` | `property_requirement` |
| `desired_move_in_date`, `move_in_date_raw_text` | `property_requirement` |
| `request_expiry_date`, `current_tenancy_expiry_date` | `property_requirement` |
| `desired_complex_names` | `property_requirement_complex` + `property_complex.name` |
| `has_co_broker` | 공동중개인 존재 여부. 식별자는 싣지 않음 |

`PartyRoleContext`는 결정권 제약을 판단하기 위한 비식별 역할 정보다. `party_id`, 성명과 연락처는
담지 않으며, 임차인·공동명의·비결정권자 제약은 별도 출력 어휘를 늘리지 않고 `inflexible`에
근거와 함께 표현한다.

`memo`, `custom_fields`와 대출 금액은 계약에 넣지 않는다. 자유 메모에는 성명·연락처가 섞일
수 있고 대출 금액은 판정에 필요한 최소 항목이 아니다 (F3-SE-01). `*_raw_text`는 사용자 입력
원문이다. `MASKED` 모드에서는 Backend가 상담 내용과 같은 마스킹을 적용한 뒤 전달하고,
`SYNTHETIC_PROTOTYPE` 모드에서는 실제 인물과 연결되지 않는 합성 원문만 그대로 전달한다.

`demand_type`, `status`, `classification`, `workflow_stage`, `listing_status`,
`tenancy_status`, `unit_type`, `lifecycle_status`는 F1이 아직 값 목록을 확정하지 않은 장부
표기값이라 문자열로 통과시킨다. 카드 판정 어휘가 아니다.

### 상담 로그 입력

`ConsultationLogInput`은 `interaction_id`, `interaction_at`, `channel`,
`counterparty_role`, `interaction_result`, `masked_content`를 담는다. 각각
`client_interaction`의 `id`, `interaction_at`, `interaction_channel`, `counterparty_role`,
`interaction_result`, `interaction_content`에서 온다.

`masked_content`는 **Provider 전달용 본문**이다. `MASKED` 모드에서는 Backend가 AI 호출 전에
성명, 전화번호, 이메일, 로그인 ID와 생년월일을 치환하거나 마스킹한 결과만 전달한다. 프로토타입의
`SYNTHETIC_PROTOTYPE` 모드에서는 실제 인물을 나타내지 않는 합성 본문을 변환 없이 전달할 수 있다.
치환 대응표는 요청, 결과, 로그와 DB snapshot 어디에도 넣지 않는다.

합성 모드는 [ADR-0014](../decisions/ADR-0014-f3-prototype-synthetic-input.md)에 따른 임시
예외다. 요청에 모드를 표시하는 것만으로는 부족하며 `LlmPositionCardGenerator` 조립 지점에서
`allow_synthetic_prototype=True`를 명시해야 한다. 기본값은 false다.

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

`negotiation_side`, `anchor_id`, `target_label`, `data_version`, `interaction_count`,
`last_interaction_at`, `max_interaction_id`, `cache_key`, `generated_at`은 모델이 만들거나
고치는 값이 아니다.

- `PositionCardTarget`은 `PositionCardTarget.from_request()`로 요청에서 결정적으로 복사한다.
- 모델 구조화 출력이 대상 ID·라벨이나 source identity를 만들게 하지 않는다.
- 장부 표기 금액도 모델 출력 schema에서 제외하고 요청의 구조화 값으로 조립한다.
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
- Backend가 저장 전에 `quote_text`가 해당 Provider 전달용 상담 로그에 실제로 존재하는지 확인하고,
  실제 원문 기준 offset을 계산해 `negotiation_position_evidence`에 넣는다.

구조 validation과 요청·결과 간 validation을 구분한다.

| 계층 | 위치 | 확인 |
|---|---|---|
| 구조 | Pydantic DTO | 어휘, 필수값, 빈 문자열, 음수, extra field, kind별 필수값 |
| 요청·결과 | `validate_generation_result()` | 계약 버전, 대상과 side 일치, source identity 일치, hard deadline이 Backend 날짜 신호와 같은지, 인용 로그가 요청 범위 안인지, 인용문이 Provider 전달용 본문에 실재하는지, price_kind가 해당 측과 활성 거래 유형에 허용되는지, 표기 금액이 장부와 같은지 |
| DB 현재 상태 | Backend | lease 소유권과 attempt fencing, 입력 버전·상담 범위·source identity·입력 fingerprint 재대조, tenant 격리, offset 계산 |

`LlmPositionCardGenerator`는 조립한 결과를 경계 밖으로 반환하기 전에
`validate_generation_result()`를 반드시 호출한다. 따라서 호출자는 요청 범위를 위반한 모델
결과를 정상 결과로 받을 수 없다. Backend는 저장 직전에 DB 현재 상태를 검증하고 필요하면 이
순수 검증을 방어적으로 다시 호출한다. `validate_generation_result()`는 Session이나 Repository를
받지 않는다.

## 진단과 버전

`ProviderDiagnostics`를 재사용한다. `provider`, `model`, `request_id`, `latency_ms`,
`usage`(input/output/total token)만 담는다.

- Backend는 Provider와 모델을 직접 고르지 않는다.
- 실제 모델 ID와 운영 Provider는 이번 작업에서 확정하지 않았다. AI-OQ-001, AI-OQ-002,
  AI-OQ-003은 그대로 미해결이다.
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

이번 작업은 외부 Provider 전송을 승인하지 않는다. 실제 Provider, 리전과 저장 여부는
AI-OQ-001~003과 별도 운영 결정 전까지 미확정이다. 합성 프로토타입 예외도 외부 Provider 선택을
승인하지 않는다. 실제 개인정보가 포함될 수 있는 입력에 외부 Provider를 쓰게 되면 Backend가
개인정보를 제거한 `MASKED` 입력만 전달한다는 조건을 적용한다 (F3-SE-02).

### 원문 보관 요구와의 충돌

- 요구사항 출처 F3-SE-03에는 프롬프트 원문과 응답을 실행 로그로 보관하라는 요구가 있다.
- 현재 승인된 [개인정보 정책](../privacy/policy.md)은 전체 프롬프트를 로그에 남기지 않는다.
- **승인된 개인정보 정책을 우선한다.** 전체 프롬프트와 전체 모델 응답을 보관하지 않는다.
- 재현에 필요한 정보는 구조화·redacted snapshot, 모델·프롬프트·워크플로 버전,
  token/latency metadata로 제한한다.
- 이 정책을 바꾸려면 별도 개인정보 결정이 필요하다.

## 중개 판정 계약

앵커 포지션 카드 1장과 반대편 후보 카드 N장을 **한 번의 구조화 출력 호출**로 판정한다
(F3-BR-01, F3-BR-02, F3-NF-04). 후보를 개별 호출하지 않고 앵커를 후보 수만큼 반복 전송하지
않는다. 후보가 0건이면 요청을 만들지 않으며 모델도 부르지 않는다. Backend는 저장된 앵커·후보
카드에서 요청을 조립하고, 판정 호출 전 `JUDGING`, 검증된 결과의 원자 저장 뒤 `COMPLETED`를
기록한다.

### 등급과 행동 어휘

| 계약값 | 화면 한국어 | 의미 |
|---|---|---|
| `STRONG` | 강함 | 지금 연결할 만함 |
| `WEAK` | 약함 | 조건이 움직이면 가능함 |
| `REJECTED` | 기각 | 현재 조건으로 성사 불가 |

같은 의미의 `HIGH`, `LOW`, `EXCLUDED`나 한국어 화면 표기를 계약값으로 쓰지 않는다. 행동 제안의
접촉 경로는 `CALL`, `MESSAGE`, `IN_PERSON` 세 값이며 F1의 아직 미확정인
`client_interaction.interaction_channel`과 다른 F3 판정 어휘다.

### 요청 계약

`BrokerageJudgmentRequest`는 다음 필드를 갖는다.

| 필드 | 의미 |
|---|---|
| `contract_version` | `brokerage-judgment:v1` 고정 |
| `input_privacy_mode` | `SYNTHETIC_PROTOTYPE` 또는 `MASKED` |
| `anchor` | `JudgmentCard` 1장 |
| `candidates` | 반대편 `JudgmentCard` 1~15장 |

`JudgmentCard`는 내부 `card_id`, `negotiation_side`, 비식별 `target_label`과 포지션 카드 계약의
`PositionCardAnalysis`를 그대로 담는다. 별도 카드 표현을 만들지 않는다. 후보 ID는 중복될 수
없고 앵커가 후보로 들어올 수 없으며 후보는 모두 앵커의 반대편 측면이어야 한다.

카드 안의 근거 인용도 Provider 입력에 포함되므로 ADR-0014의 개인정보 통제를 그대로 적용한다.
`SYNTHETIC_PROTOTYPE` 요청은 생성기 조립 지점의 `allow_synthetic_prototype=True`가 함께 있어야
하며 기본 생성기는 Provider를 호출하기 전에 거절한다. 이 구현은 외부 Provider·리전·저장 여부를
승인하지 않는다.

### 결과 계약

`BrokerageJudgmentResult`는 계약 버전, 요청에서 결정적으로 복사한 `target`, 후보별 판정,
prompt·workflow 버전과 안전한 diagnostics를 담는다. 모델 출력 schema에는 계약 버전, 실행·사무소
식별자, 앵커 target과 후보 집합 같은 서버 소유 필드를 두지 않는다.

후보별 `CandidateJudgment`는 다음을 담는다.

| 필드 | 의미 |
|---|---|
| `card_id` | 후보 카드 ID |
| `grade` | `STRONG`·`WEAK`·`REJECTED` |
| `rank` | 전체 후보의 1부터 N까지 연속 순위 |
| `comparison_basis` | 다른 후보와 비교해 먼저 보여줄 이유 |
| `primary_obstacle` | 결정적 가격·시점·조건 차이 |
| `possible_concession` | 누가 무엇을 얼마나 움직일지 |
| `recommended_action` | 접촉 측면·경로·한 문장 행동 제안 |
| `rejection_reason` | 기각 사유. `REJECTED`에서만 필수 |
| `evidence` | 카드에서 유래한 근거 1건 이상 |

기각 후보도 결과에서 제거하지 않는다. 실제 발송 문안은 만들지 않고 `recommended_action.message`는
먼저 꺼낼 말에 대한 500자 이하 제안으로 제한한다.

### 근거와 교차 검증

판정 단계에는 상담 원문이 없다. `QUOTE`는 해당 앵커 또는 **그 후보 카드가 이미 보유한**
`(interaction_id, quote_text)` 쌍만 허용한다. 카드에 없는 인용은 거절하며 카드 값을 비교한
판단은 `INFERENCE`로 표시한다.

`validate_judgment_result()`는 다음을 강제한다.

- 요청·결과 계약 버전, 앵커 카드 ID·측면과 후보 카드 집합의 정확한 일치
- 요청 후보 전건 판정, 후보 누락·추가·중복 금지
- 순위가 중복이나 구멍 없이 1부터 N까지 연속
- 기각 사유 유무와 후보별 근거 1건 이상
- 인용이 해당 카드가 가진 근거 범위 안에 존재

`LlmBrokerageJudgmentGenerator`는 이 검증을 **결과를 반환하기 전에 직접 호출**한다. 호출자가
검증을 빠뜨려도 잘못된 모델 결과가 공개 생성 경계 밖으로 나가지 않는다. Backend도 저장 직전에
tenant, lease, 판정 바인딩, 앵커 버전, 후보 snapshot과 카드의 현재 유효성을 별도로 재검증한다.

### LangGraph 적용 범위

중개 판정 자체는 요구사항상 구조화 출력 1회이므로 현재 LangGraph를 씌우지 않는다. 단일 노드
wrapper는 재개 지점을 만들지 않는다. 전체 F3 단계 진행과 재선점은 Backend DB 상태가 담당하고,
한 AI 호출 내부에 도구 호출·분기·재질의가 생길 때 production graph 도입을 다시 검토한다.
checkpoint 저장 계약은 AI-OQ-004로 계속 미확정이다.

## 오류와 재시도 경계

- Provider 오류는 AI의 `ProviderError` 계층으로 표현하고 `retryable` 여부를 함께 준다.
- 결과가 요청과 맞지 않으면 `PositionCardContractError` 또는
  `BrokerageJudgmentContractError`이며 재시도로 해결되지 않는다.
- 재시도 횟수와 backoff는 Worker가 소유한다. AI SDK 자동 재시도는 꺼져 있다.
- 검증에 실패한 결과로 카드를 저장하지 않는다. 조용히 근거를 지우고 성공으로 위장하지 않는다.

## 구현 범위

### 이번 구현 범위 (`구현됨`)

- `negotiation_side`, intent, urgency, contactability, evidence, price_kind 어휘
- 계약 버전 `position-card:v1`
- 요청·결과 DTO와 LISTING/REQUIREMENT 입력 격리
- `PositionCardGenerator` Protocol
- `PositionCardGeneratorVersions`와 실제 prompt·workflow 버전
- `SYNTHETIC_PROTOTYPE`·`MASKED` 입력 모드와 합성 모드의 명시적 생성기 opt-in
- `LlmPositionCardGenerator` 구조화 출력 생성 구현
- 모델 출력에서 서버 소유 대상·source identity·장부 표기 금액을 제거한 내부 schema
- 대리 측면별 한국어 프롬프트와 전체 상담 로그 시간순 전달
- 주입한 fake Provider로 모델 요청·출력 조립을 검증하는 단위 테스트
- 생성 결과 반환 전 요청·결과 교차 검증을 강제하는 순수 함수
- Backend `AnchorType`과의 값 일치 계약 테스트
- 정본 등록과 OQ-012 종료를 강제하는 계약 테스트
- 합성 F1 장부·측면별 상담 로그를 `SYNTHETIC_PROTOTYPE` 요청 snapshot으로 조립
- 입력 전체 fingerprint와 상담 범위 identity를 포함하는 Backend cache key `position-card:v3`
- AI 호출 전후 transaction 분리와 lease·attempt·입력 버전·상담 범위·source identity 재검증
- 검증된 카드·거래 유형별 가격·근거 인용과 quote offset 저장
- cache hit 재사용과 저장 경합 단일화, `ANCHOR_READY` 상태 전이
- 결정적 SQL 후보 snapshot의 상위 15건에 대한 반대편 카드 순차 생성·캐시 재사용
- 후보 카드 ID snapshot 기록과 전건 성공 후 `CANDIDATE_CARDS_READY` 상태 전이
- 중개 판정 계약 `brokerage-judgment:v1`, 등급·행동·근거 어휘와 프레임워크 중립 Protocol
- 앵커 1장과 후보 1~15장을 한 번에 보내는 Provider 중립 구조화 출력 생성기
- 합성 입력 이중 opt-in과 생성 결과 반환 전 후보 집합·순위·근거 교차 검증
- 저장된 앵커·후보 카드의 판정 요청 조립과 `SYNTHETIC_PROTOTYPE` privacy mode 고정
- AI 호출 전후 transaction 분리와 lease·attempt·바인딩·앵커·후보 장부 버전·후보 집합 재검증
- 후보별 등급·순위·걸림돌·양보·행동·기각 사유·근거의 원자 저장
- `JUDGING`·`COMPLETED` 상태 전이와 만료된 `JUDGING` lease 재선점·재실행
- 후보 0건의 AI 호출 없는 빈 결과 완료
- RDS polling Worker와 저장 상태 기반 F3 handler 연결
- capability별 모델 설정의 단계별 lazy binding과 합성 프로토타입 이중 opt-in
- 일시 Provider 오류의 lease release·3회 상한 재시도, 입력 변경 `SUPERSEDED`, 영구 오류
  `FAILED_TERMINAL` 처리

### 아직 구현하지 않음 (`계획됨`)

- 실제 F1 사용자 데이터를 위한 상담 로그 마스킹과 `MASKED` 모드 전환
- 배포 환경의 `WORKER_ENABLED=true` 전환과 운영 Provider 선택. 실행 코드는 지원하지만 현재 Infra
  기본값은 `false`다
- F3 전체 production LangGraph와 checkpoint. 포지션 카드 1회 구조화 호출에는 이름뿐인 graph를
  덧씌우지 않는다

### 미확정

- 실제 모델 ID와 운영 Provider (AI-OQ-001, AI-OQ-002, AI-OQ-003)
- LangGraph checkpoint 저장 계약 (AI-OQ-004)
