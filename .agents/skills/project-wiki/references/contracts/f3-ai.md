---
status: 결정
updated: 2026-08-21
---

# F3 포지션 카드 Backend–AI 계약

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
| Backend snapshot 조립과 날짜 신호 | `backend/src/domain/agent_execution/snapshot.py` |
| Backend 마스킹 | `backend/src/domain/agent_execution/masking.py` |
| Backend 생성·저장 유스케이스, cache lookup, 바인딩 | `backend/src/domain/agent_execution/anchor_card.py` |
| Backend 모델 출력 개인정보 검사 | `backend/src/domain/agent_execution/pii_guard.py` |
| Backend 모델 입력 지문 | `backend/src/domain/agent_execution/fingerprint.py` |
| Backend 상담 로그 범위 | `backend/src/domain/agent_execution/repository.py` (`InteractionScope`) |
| 중개 판정 어휘와 DTO | `ai/src/brokerage_ai/f3/judgment_contracts.py` |
| 중개 판정 생성 Protocol | `ai/src/brokerage_ai/f3/judgment_ports.py` |
| 중개 판정 요청·결과 교차 검증 | `ai/src/brokerage_ai/f3/judgment_validation.py` |
| 중개 판정 모델 구조화 출력 schema | `ai/src/brokerage_ai/f3/judgment_model_output.py` |
| 중개 판정 프롬프트와 prompt version | `ai/src/brokerage_ai/f3/judgment_prompts.py` |
| 중개 판정 생성 구현과 workflow version | `ai/src/brokerage_ai/f3/judgment_generator.py` |

## 두 버전 축

| 축 | 값 | 의미 | 소유 |
|---|---|---|---|
| 계약 버전 | `position-card:v1` | DTO와 의미 규격의 버전 | AI |
| Prompt 버전 | `position-card-prompt:v1` | 프롬프트 원문의 버전 | AI |
| Workflow 버전 | `position-card-workflow:v1` | 생성 절차의 버전 | AI |
| Cache key 버전 | `position-card:v3` | 캐시 키 계산 방식의 버전 | Backend |
| 입력 지문 버전 | `position-card-input:v1` | 모델 입력 정규화 방식의 버전 | Backend |
| 로그 범위 버전 | `interaction-scope:v2` | 상담 로그 포함 정책의 버전 | Backend |
| 판정 계약 버전 | `brokerage-judgment:v1` | 중개 판정 DTO와 의미 규격의 버전 | AI |
| 판정 prompt 버전 | `brokerage-judgment-prompt:v1` | 중개 판정 프롬프트 원문의 버전 | AI |
| 판정 workflow 버전 | `brokerage-judgment-workflow:v1` | 중개 판정 절차의 버전 | AI |
| 후보 선정 버전 | `candidate-selection:v2` | 후보 snapshot 구조의 버전 | Backend |

서로 다른 것을 버전하며 독립적으로 올라간다. 번호가 다른 것은 정상이다.

prompt·workflow 버전은 AI가 소유하지만 Backend가 cache key를 계산할 때 필요하다. 모델을
부르기 전에 알 수 있어야 하므로 `PositionCardGenerator.versions`가 프레임워크 중립
`PositionCardGeneratorVersions`로 먼저 알려준다. Provider SDK 객체와 DB의 `model_config_id`는
이 값에 담지 않는다.

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
| `target_label` | 화면 표시용 라벨. Backend가 만들며 모델이 바꿀 수 없다 |
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
| `party_roles` | 현재 유효한 `property_unit_party_relation`의 `role`·`is_primary`·`is_co_owner` |
| `client_party_role` | 의뢰인(`property_listing.client_party_id`)의 위 관계상 역할 |

| REQUIREMENT context 필드 | F1 출처 |
|---|---|
| `requirement_id`, `demand_type`, `status`, `received_at` | `property_requirement` |
| `classification`, `workflow_stage` | `property_requirement` |
| `min_budget_amount`, `max_budget_amount`, `budget_raw_text` | `property_requirement` |
| `desired_pyeongs`, `min_area_sqm`, `max_area_sqm`, `area_requirement_raw_text` | `property_requirement` |
| `desired_move_in_date`, `move_in_date_raw_text` | `property_requirement` |
| `request_expiry_date`, `current_tenancy_expiry_date` | `property_requirement` |
| `desired_complex_names` | `property_requirement_complex` + `property_complex.name` |
| `has_co_broker` | `property_requirement.co_broker_party_id`의 존재 여부 |

`PartyRoleContext`는 결정권 판정(F3-LA-07)에만 쓰는 비식별 값이다. `party_id`, 성명, 연락처는
담지 않는다. 임차인이라 처분 결정권이 없거나 공동명의라 단독 결정이 불가한 상황, 의뢰인이 실질
결정권자가 아닌 상황은 별도 출력 enum을 만들지 않고 `inflexible`에 근거와 함께 적는다.

`memo`, `custom_fields`와 대출 금액은 계약에 넣지 않는다. 자유 메모에는 성명·연락처가 섞일
수 있고 대출 금액은 판정에 필요한 최소 항목이 아니다 (F3-SE-01). `*_raw_text`는 사용자 입력
원문이므로 Backend가 상담 내용과 같은 마스킹을 적용한 뒤 전달한다.

`demand_type`, `status`, `classification`, `workflow_stage`, `listing_status`,
`tenancy_status`, `unit_type`, `lifecycle_status`는 F1이 아직 값 목록을 확정하지 않은 장부
표기값이라 문자열로 통과시킨다. 카드 판정 어휘가 아니다.

### 대리 측면별 상담 로그 범위

같은 세대에 달린 로그라도 반대편 당사자의 말은 읽지 않는다 (F3-LA-02, F3-CA-02). 범위 정의는
`InteractionScope` **한 곳**에만 둔다. 목록 조회, source identity 계산, cache key와 저장 직전
재검증이 모두 같은 정의를 쓴다. 서로 다른 조건을 쓰면 AI에 넘긴 로그와 fencing이 어긋난다.

`counterparty_role` 문자열만 믿어 격리하지 않는다. F1의 tenant 복합 관계와 `party_id`로
판정한다.

| 측면 | 포함 조건 |
|---|---|
| `LISTING` | `requirement_id IS NULL` **그리고** 다음 중 하나<br>① `listing_id`가 앵커 매물과 일치 (당사자 무관)<br>② `listing_id IS NULL` 이고 `unit_id`가 앵커 세대와 일치하며 `party_id`가 허용 당사자 |
| `REQUIREMENT` | `requirement_id`가 앵커와 일치 **그리고** `party_id`가 NULL 이거나 허용 당사자 |

허용 당사자:

| 측면 | 집합 |
|---|---|
| `LISTING` | `property_unit_party_relation`에 이 세대와 관계를 맺은 적 있는 모든 `party_id` + `property_listing.client_party_id` |
| `REQUIREMENT` | `property_requirement.party_id` + `co_broker_party_id` |

`party_id IS NULL`인 로그의 처리가 측면마다 다르다.

- `REQUIREMENT`는 포함한다. `requirement_id`가 이미 측면을 확정하므로 당사자가 비어 있어도
  수요 측 기록이다.
- `LISTING`은 **매물 건에 명시적으로 달린 로그만** 포함한다. 세대에만 달리고 당사자도 없는
  로그는 구입장 연결 없이 기록된 수요 측 상담일 수 있어 제외한다. 반대편 정보가 한 건이라도
  섞이는 것보다 판단 재료가 한 건 줄어드는 쪽이 낫다 (F3-LA-02).

이 규칙은 이번 구현이 적용하는 보수적 데이터 격리 정책이며 팀이 별도로 승인한 요구사항이
아니다. 모호한 unit-only 로그를 매물 대리가 읽어야 한다는 판단이 서면 이 표를 먼저 바꾸고
`interaction-scope` 버전을 올린다.

판단 근거:

- 구입장이 달린 로그는 세대에도 연결돼 있어도 수요 측이다. 매물 대리 범위에서 제외한다.
- 관계가 **끝난**(`valid_to`가 찬) 과거 소유자·임차인의 말은 그 시점의 매물 측 진술이므로
  포함한다. 2018년 기록까지 남기는 F1 정책이 여기서 자산이 된다 (F3-LA-05). 화면에 보여줄
  현재 역할(`party_roles`)은 유효한 관계만 쓰므로 이와 별개다.
- 매수 희망자는 세대 관계 자체가 없어 어떤 경우에도 매물 측 범위에 들어오지 않는다.

사무소 격리와 `is_voided = false`는 그대로 유지하고, 허용 범위 안에서는 전량을
`interaction_at ASC, id ASC`로 전달한다. source identity는 실제로 전달되는 **필터링 완료**
로그 집합에서 계산한다.

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

현재 구현 규칙:

- 기준 시각을 한 번만 정하고 모든 신호가 그 값을 공유한다. 신호마다 시계를 다시 읽지 않는다.
- timezone-aware datetime만 사용한다.
- `hard_deadline_candidate`는 **직접 확인 가능한 날짜 중 가장 이른 값**이다. LISTING은
  `property_unit.tenancy_expiry_date`, REQUIREMENT는 `desired_move_in_date`,
  `request_expiry_date`, `current_tenancy_expiry_date` 중 최솟값이다.
- 영업일이나 준비 기간을 임의로 빼서 마감일을 앞당기지 않는다. 승인되지 않은 기간을 끼워 넣으면
  근거 없는 마감일이 만들어진다.

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
- 모델 구조화 출력이 대상 ID, 라벨이나 source identity를 만들게 하지 않는다.
- `cache_key`는 Backend가 계산하며 결과 DTO에 없다.
- `generated_at`은 Backend 또는 DB가 저장 시점에 정하며 결과 DTO에 없다.
- `validate_generation_result()`가 결과의 `target_label`이 요청값과 같은지 확인한다.

#### target label

Backend가 F1 구조화 값에서 결정적으로 만든다. 모델 출력 schema에는 존재하지 않는다.

| 측면 | 규칙 | 예 |
|---|---|---|
| `LISTING` | 단지명·동·호. 이미 계약에 실린 구조화 값만 쓴다 | `검증단지 101동 1801호` |
| `REQUIREMENT` | `구입장 #<requirement_id>`. 인물 이름을 쓰지 않는다 | `구입장 #91` |

성명, 연락처는 어느 측면에도 넣지 않는다. 단지·동·호는 인물이 아니라 부동산을 가리키므로
비개인정보 구조화 값으로 취급한다. `negotiation_position_analysis.target_label`이
`VARCHAR(200)`이라 길이를 넘으면 결정적으로 잘라 붙인다.

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
| DB 현재 상태 | Backend (`anchor_card.py`) | lease 소유권, 입력 버전, source identity 재대조, tenant 격리, offset 계산 |

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

## 실행 모델 바인딩

`GenerationBinding`은 cache key 계산에만 쓰이지 않는다. 준비 transaction에서 AI를 부르기 전에
실행에 실제로 기록한다.

기록하는 네 값: `agent_run.model_config_id`, `model_snapshot`, `prompt_version`,
`workflow_version`.

규칙:

- Backend는 Provider나 모델의 기본값을 만들지 않는다. 무엇을 쓸지는 호출 조립 지점이 정한다.
- 전달된 `model_config_id`가 **이 실행의 `brokerage_id`에 속한** 활성 `POSITION_CARD` 설정인지
  확인한다.
- 다른 tenant의 설정과 존재하지 않는 설정은 **같은 오류**로 거절한다. 구분해서 알리면 남의
  설정 존재 여부가 새어 나간다.
- `model_snapshot`은 DB 설정의 allowlist 필드로만 구성한다: `provider`, `model_name`,
  `model_version`, `config_key`, `config_version`. 호출자가 준 임의 dict를 저장하지 않는다.
- API key, token, 인증 헤더, Secret, 전체 endpoint URL은 넣지 않는다. `endpoint_alias`도
  allowlist에 없다.
- 미바인딩 상태는 **세 버전 컬럼이 NULL 이고 `model_snapshot`이 빈 JSON 객체**인 상태뿐이다.
  `agent_run.model_snapshot`은 `NOT NULL DEFAULT '{}'::jsonb`이므로 "네 값이 모두 NULL"이라는
  판정은 성립하지 않는다.
- 최초 기록은 lease fencing 조건과 위 미바인딩 조건 아래 원자적으로 한 번에 쓴다. `WHERE`에
  `model_snapshot::jsonb = '{}'::jsonb`를 포함한다. 바꾼 행이 1이 아니면 거절한다.
- 그 밖의 조합(snapshot만 채워짐, 버전 일부만 채워짐)은 손상된 바인딩으로 보고 덮어쓰지 않는다.
- 재시도에서는 네 값이 모두 기존 바인딩과 정확히 일치해야 한다. 하나라도 다르면
  `GenerationBindingError`다.
- 저장 직전에도 네 값을 다시 본다. `model_snapshot`은 실행에 기록된 값, 준비 단계가 확정한 값,
  지금 설정에서 다시 만든 안전한 snapshot 셋이 모두 같아야 한다. AI를 기다리는 사이 다른
  transaction이 `model_snapshot`을 바꾸면 결과를 저장하지 않는다.
- 일부 컬럼만 채워진 비정상 행은 새 바인딩으로 덮지 않고 거절한다. 어떤 구성으로 돌았는지
  확인할 수 없는 실행을 정상으로 만들면 감사 추적이 끊긴다.
- cache key는 영속화하고 검증한 바인딩과 같은 값으로 계산한다.
- cache hit의 `redacted_output_snapshot`에서도 계약·prompt·workflow 버전이 null이 되지 않는다.
  모델 진단이 없으므로 provider·model은 거짓 값을 만들지 않고 실행에 기록된 `model_snapshot`의
  허용 필드에서 가져온다.

## 상담 로그 마스킹

Backend가 AI 호출 **전에** 수행하는 순수 함수다 (`masking.py`). AI에는 DB 원문이 가지 않는다.

**순서가 중요하다.** 로그를 먼저 고르고, 그 로그의 당사자까지 secret에 넣은 뒤 마스킹한다.
현재 관계자만 모으면 관계가 끝난 과거 소유자의 이름이 원문에 남는다.

| 출처 | 마스킹할 값 |
|---|---|
| 허용 범위 party (관계자 + 의뢰인 + **실제로 선택된 로그의 `party_id`**) | `party.name`, `party.alternate_name`, `party_contact.contact_value`, `party_contact.normalized_contact_value` |
| `agent_run.requested_by` 사용자 | `app_user.login_id`, `app_user.display_name` |
| 앵커의 `assigned_user_id` (세대·매물·구입장) | 같음 |
| 로그를 작성·승인한 사용자 (`created_by`, `approved_by`) | 같음 |
| 원문 패턴 | 전화번호, 이메일, 생년월일, 주민등록번호 |

`requested_by`는 마스킹 목적으로만 `build_anchor_snapshot()`에 전달하며 AI 공개 DTO에는
들어가지 않는다.

적용 대상은 계약에 실리는 **모든 자유 문자열**이다: 상담 로그 `masked_content`,
`price_raw_text`, `handover_condition`, `tenancy_raw_text`, `budget_raw_text`,
`area_requirement_raw_text`, `move_in_date_raw_text`.

단지명, 동·호수, 면적처럼 업무상 필요한 비개인정보 구조화 값은 마스킹하지 않는다.

규칙:

- **길이를 보존한다.** 가려진 값은 같은 길이의 `*`로 바뀌고 `-`, `.`, `@`, `/`, 공백은 자리를
  지킨다.
- 알려진 값은 긴 것부터 처리한다. 짧은 값을 먼저 지우면 긴 값의 나머지가 남는다.
- 같은 입력은 항상 같은 결과가 된다.
- 치환 대응표를 만들지 않는다. AI 요청, 결과, DB snapshot, 로그 어디에도 저장하지 않는다.
- 마스킹 결과와 원문을 애플리케이션 로그에 출력하지 않는다.
- 마스킹을 보장할 수 없는 값은 계약에서 제외한다.

길이를 보존하는 이유는 근거 offset이다. AI는 마스킹된 본문에서 인용을 돌려주고 Backend는 그
인용의 위치를 마스킹된 본문에서 찾는다. 길이가 같아야 그 위치가 원본 상담 로그의 같은 문자
위치가 되고, 그래서 대응표를 영속화할 필요가 없다.

## 모델 출력 개인정보 검증

프롬프트에 "개인정보를 쓰지 말라"고 적는 것은 지시일 뿐 보장이 아니다. Backend가 저장 직전에
모델이 만든 자유 문자열을 직접 훑는다 (`pii_guard.py`).

검사 대상 (모델이 만든 자유 문자열만):

- intent·urgency·contactability·price basis의 모든 evidence `note`와 `quote_text`
- `PositionCondition.description` (timing constraints, flexible, inflexible)
- `ContactabilityAssessment.note`

`analysis_snapshot`은 검증을 통과한 결과를 그대로 직렬화하므로 위 검사가 곧 snapshot 검사다.

금지 조건:

- 전화번호, 이메일, 생년월일, 주민등록번호 형태의 패턴이 나타나면 거절한다.
- 요청을 조립할 때 가린 성명·별칭·`login_id`·`display_name`·연락처가 결과에 다시 나타나면
  거절한다. 마스킹된 본문만 봤는데 원문이 나왔다면 모델이 만들어 낸 것이다.

처리 규칙:

- **조용히 마스킹하고 성공 처리하지 않는다.** 가려서 넣으면 모델이 개인정보를 만들고 있다는
  사실이 아무 데도 남지 않는다. 저장 전체를 `ModelOutputPrivacyError`로 거절한다.
- 오류 메시지에 발견된 값을 넣지 않는다. 필드 위치와 종류만 알린다.
- 전체 모델 원문을 로그에 남기지 않는다.
- 구조화 필드(금액, 날짜, 어휘 enum)는 검사하지 않는다. `2026-11-30` 같은 정상 마감일을
  생년월일 패턴으로 오인해 정상 카드를 막으면 안 된다.
- 거절되면 카드·가격·근거가 하나도 남지 않고 실행은 `RUNNING`을 유지한다.

## 후보 카드 재사용

같은 계약과 같은 생성 경로가 후보 카드에도 쓰인다. 앵커 카드와 다른 것은 대상과 기대 실행
상태뿐이며, 후보 카드는 앵커의 **반대편** `negotiation_side`를 갖는다. 매물 앵커의 후보 카드는
`REQUIREMENT`, 구입장 앵커의 후보 카드는 `LISTING`이다.

- 후보 카드의 입력 버전은 그 후보 장부 행의 `row_version`이다. 실행의 `input_data_version`은
  앵커 것이므로 후보에 쓰지 않는다.
- cache key, cache lookup, 저장 직전 재검증, 모델 출력 개인정보 검사는 앵커와 같은 함수다.
  후보용 두 번째 구현을 만들지 않는다.
- 후보 카드는 루트 `AgentRun`에 직접 귀속한다. child run을 만들지 않는다.
- 후보 카드의 상담 로그 범위도 `InteractionScope` 하나로 정해진다. 후보가 구입장이면 그
  구입장 측 로그만 들어가므로 앵커 매물 소유자의 말은 후보 카드 입력에 없다.

Backend 저장 위치의 정본은
[온라인 실행 아키텍처](../../../../../docs/architecture/f3/online-runtime.md)의 후보 포지션 카드
절이다.

## 실행 흐름과 transaction 경계

AI를 기다리는 동안 DB transaction이나 row lock을 쥐고 있지 않는다. 흐름을 셋으로 나눈다.

| 단계 | transaction | 하는 일 |
|---|---|---|
| 1. 준비 | 연다 → 닫는다 | lease 확인, **모델 바인딩 확정·기록**, 앵커 버전 확인, snapshot 조립과 마스킹, cache lookup |
| 2. 생성 | **없음** | `generate_position_card()` await. cache hit이면 건너뛴다 |
| 3. 저장 | 연다 → commit | 재검증 후 카드·가격·근거·상태를 원자 저장 |

준비 단계는 **모든 예외에서** rollback한다. `SQLAlchemyError`뿐 아니라 lease·입력 버전·source·
바인딩·검증 오류에서도 열린 transaction을 남기지 않는다. 남기면 AI를 기다리는 동안 그 커넥션이
`idle in transaction`으로 잠긴다. 원래 예외 타입은 그대로 올린다.

3단계가 저장 직전에 다시 확인하는 것 (**cache hit과 miss 모두**):

- 같은 Worker가 여전히 유효한 lease를 쥐고 있는가 (`lease_owner`, `lease_expires_at`,
  `attempt_count`, `status`)
- 실행의 사무소가 준비 단계와 같은가
- 실행에 기록된 모델 바인딩 **네 값**이 그대로이고 지금 기대되는 값과 같은가
- 앵커 `row_version`이 그대로인가 (1차 검사)
- **현재 장부에서 범위를 다시 만들어** 범위 지문이 준비 시점과 같은가
- 그 현재 범위로 상담 로그를 다시 세어 source identity가 준비 시점과 같은가
- **입력 전체를 다시 조립해** 지문이 준비 시점과 같은가
- (cache hit만) 재사용할 카드가 아직 활성 상태로 그 자리에 있는가
- (cache miss만) `validate_generation_result()`를 통과하는가
- (cache miss만) 모델 출력에 개인정보가 없는가
- (cache miss만) 결과의 prompt·workflow 버전이 cache key에 쓴 값과 같은가

범위는 **준비 시점 객체를 재사용하지 않고 다시 만든다.** 준비 이후에 생긴 당사자 관계와 그
로그를 저장 단계가 영영 보지 못하기 때문이다. 준비 시점 범위는 지문으로만 비교한다.

하나라도 어긋나면 카드를 저장하지 않고 상태도 바꾸지 않는다. 앵커가 바뀌었으면
`InputVersionChangedError`, 상담 로그 집합이 바뀌었으면 `SourceChangedError`, lease를 잃었으면
`LeaseNotHeldError`, 바인딩이 어긋나면 `GenerationBindingError`, 재사용하려던 카드가 더 이상
유효하지 않으면 `CachedCardUnavailableError`다. 마지막 것은 다시 준비해서 생성하면 되는
재시도 가능한 오류다. 입력이 바뀐 오류(`InputVersionChangedError`, `SourceChangedError`)는
Worker가 `SUPERSEDED`로 기록한다.

`PreparedGeneration`은 cache hit에서도 `source`, 범위 지문, 입력 지문, 날짜 bucket을 항상 들고
있다. 마스킹 본문은 cache hit일 때 들고 다니지 않지만 이 값들은 남겨야 재사용 경로에도 fencing이
선다.

### 모델 입력 지문

`agent_run.input_data_version`은 앵커 **한 행**의 `row_version`이다. 그 값만으로는 세대 스펙,
단지명, 당사자 역할, 상담 로그 집합, 날짜 신호처럼 모델 입력에 실제로 들어가는 나머지가
바뀌었는지 알 수 없다.

| 값 | 무엇을 나타내는가 | 어디에 쓰는가 |
|---|---|---|
| `input_data_version` | 앵커 장부 행의 `row_version` | 빠른 1차 검사. 이 값만으로 전체 입력이 같다고 보지 않는다 |
| 입력 지문 | `PositionCardGenerationRequest` 전체 | cache key, 저장 직전 전체 입력 재검증 |

지문에는 AI에 보낸 요청 그 자체가 들어간다. 앵커 context 전 필드, 날짜 신호, 마스킹된 상담
로그 전량, source identity, `target_label`, 계약 버전이다.

정규화 규칙:

- `model_dump(mode="json")`이 Decimal은 문자열, datetime·date는 ISO 8601, enum은 값, None은
  null로 고정한다.
- `json.dumps(sort_keys=True, separators=(",", ":"))` 후 SHA-256 digest를 만든다.
- Python `hash()`는 쓰지 않는다. 프로세스마다 값이 달라 캐시와 fencing에 쓸 수 없다.
- 순서가 의미 없는 집합(`party_roles`)은 명시적으로 정렬한다. 조회 순서가 달라도 같은 지문이
  나와야 한다. 선호 순서가 의미를 갖는 `desired_complex_names`는 정렬하지 않는다.
- **digest만 사용한다.** 원문과 개인정보는 DB, 로그, 오류 어디에도 넣지 않는다. 지문은
  준비 단계 메모리에서 저장 직전 비교에 쓰고 cache key에는 digest만 반영한다.

### 날짜 bucket

날짜 신호는 모델 입력을 바꾸지만 정확한 시각을 지문에 넣으면 모든 실행이 서로 다른 값이 되어
캐시가 통째로 무의미해진다. snapshot 조립 입구에서 `as_of`를 UTC로 정규화하고, 그 UTC 날짜
하나를 파생 신호 계산과 지문의 bucket으로 함께 쓴다. `DateSignals.as_of`도 정규화된 UTC 값이다.
따라서 같은 순간을 KST나 UTC로 표현해도 실제 AI 요청과 지문이 같다.

- 같은 날 안의 다른 시각은 같은 지문 → 재사용한다.
- 날짜가 넘어가면 `days_since`·`days_until`이 달라져 지문이 바뀐다 → 어제 카드를 재사용하지
  않는다.
- 시간대 표기가 달라도 UTC 기준 같은 날이면 같은 bucket이다.

### 로그 범위 지문

`InteractionScope.identity()`는 `brokerage_id`, 대상 id(unit/listing/requirement), 정렬된
`allowed_party_ids`, 범위 계약 버전을 canonical JSON으로 묶어 SHA-256한 값이다. 당사자 ID
집합을 그대로 들고 다니면 오류 메시지나 로그로 새어 나갈 자리가 생기므로 digest로만 비교한다.

범위가 바뀌면 상담 로그 수가 우연히 같아도 다른 입력으로 판단한다.

### cache lookup

일반 cache lookup은 `find_active_position_card()`이며 cache key만 믿지 않는다. 다음을 **함께**
대조한다.

| 확인 | 이유 |
|---|---|
| `brokerage_id` | tenant 격리 |
| `cache_key` | 생성 구성과 입력 지문·범위 지문이 같은가 |
| `negotiation_side` | 측면이 같은가 |
| `listing_id` / `requirement_id` | 대상이 같은가 |
| `data_version` | 장부 버전이 같은가 |
| `source_interaction_count`, `last_interaction_at` | 저장된 상담 집합이 같은가 |
| `invalidated_at IS NULL` | 무효화되지 않았는가 |

`find_card_that_won_the_cache_key()`는 **저장 경합 전용**이다. `ON CONFLICT DO NOTHING`으로
밀린 쪽이 이미 같은 키를 넣은 상대 카드를 찾을 때만 쓰고, 일반 lookup에는 쓰지 않는다.

### cache hit과 저장 경합

- cache hit이면 generator를 **0회** 호출하고 기존 카드를 재사용한다. 새 카드·가격·근거를 만들지
  않고 실행만 `ANCHOR_READY`로 옮긴다.
- cache hit에서도 저장 직전 재검증은 그대로 돈다. 새 로그 추가, 과거 시각 로그 추가, 로그
  무효화, 범위 party 변경, 세대·단지·역할 변경, 날짜 bucket 변경을 모두 잡는다.
- **재사용할 카드를 저장 직전에 다시 조회한다.** 준비와 저장 사이에 `invalidated_at`이
  찍히거나 조건이 어긋날 수 있다. 준비 시점 ID를 그대로 믿으면 무효화된 카드를 가리킨 채
  `ANCHOR_READY`로 넘어간다. 사무소, 카드 ID, `cache_key`, 측면, 대상, `data_version`, 현재
  source identity, `invalidated_at IS NULL`을 모두 확인하고 준비 시점 ID와 같은지 본다. 이
  저장 단계 조회는 `SELECT ... FOR UPDATE`로 카드 행을 잠그고 `ANCHOR_READY` 전이 transaction이
  끝날 때까지 동시 무효화를 직렬화한다. 같은 cache key 저장 경합에서 이긴 카드를 재사용하는
  경로도 그 행을 잠근다. 준비 단계의 일반 cache lookup은 행을 잠그지 않는다.
- 재조회 결과가 없거나 ID가 다르면 기존 ID를 쓰지 않고, `ANCHOR_READY`로 넘어가지 않으며,
  저장 단계에서 모델을 즉석 호출하지도 않는다. `CachedCardUnavailableError`로 rollback한다.
- 두 실행이 같은 cache key를 동시에 저장할 수 있다. 카드 insert는
  `uq_position_analysis_active_cache_key`와 같은 조건으로 `ON CONFLICT DO NOTHING` 한다.
- 경합에서 이긴 쪽만 가격과 근거를 넣는다. 진 쪽은 실패하지 않고 이긴 카드를 재사용한다.
- 중복 카드와 중복 근거가 남지 않는다.

## 저장 구조

카드 본문의 정본은 `negotiation_position_analysis`와 그 자식 테이블이다.

| 테이블 | 담는 것 |
|---|---|
| `negotiation_position_analysis` | 카드 헤더, 판정값, 시점·양보 조건 JSON, `analysis_snapshot` |
| `negotiation_position_price` | 거래 유형별 표기·추정 금액 (migration 012) |
| `negotiation_position_evidence` | 항목별 근거와 인용 offset |

`analysis_snapshot`에는 검증을 통과한 공개 계약 결과 전체를 JSON으로 넣는다.

### 다중 가격

한 매물이 매매·전세·월세를 동시에 열어 둘 수 있어 `negotiation_position_analysis`의 scalar
가격 컬럼 하나로는 부족하다.

- 모든 `PriceAssessment`를 `negotiation_position_price`에 저장하고 원래 순서를
  `display_order`로 보존한다.
- 가격이 **정확히 하나일 때만** 기존 `stated_price_amount`·`estimated_price_amount`를 호환
  projection으로 채운다.
- 둘 이상이면 scalar 컬럼을 null로 두고 child table만 정본으로 쓴다. 첫 번째 항목을 임의
  대표값으로 저장하지 않는다.
- 장부가 열어 두지 않은 거래 유형은 카드에 싣지 않는다.

### 근거와 offset

`field_name`은 결정적으로 만든다: `intent`, `urgency`, `contactability`,
`price.<PRICE_KIND>`, `timing.constraints.<n>`, `flexible.<n>`, `inflexible.<n>`.

| kind | 저장 |
|---|---|
| `QUOTE` | `interaction_id`, 마스킹된 `quote_text`, `quote_start_offset`, `quote_end_offset`, `note`는 null |
| `INFERENCE` | `note`, 나머지는 모두 null |

offset은 해당 `masked_content`에서 결정적으로 계산한다. 길이 보존 마스킹 덕분에 그 위치가 원본
상담 로그의 같은 문자 위치다.

### 상태 전이

`ANCHOR_READY`는 Backend가 실제로 기록하는 상태다. 다음을 모두 만족할 때만 옮긴다.

- 유효한 포지션 카드 ID가 있다 (cache hit 또는 새 카드 저장 완료)
- lease 소유자·만료·시도 횟수가 그대로다
- 앵커 버전과 source identity가 그대로다

카드 없이 상태만 먼저 바꾸지 않는다. 중간 상태이므로 `completed_at`을 채우지 않고
`failure_code`·`failure_message`를 새로 만들지 않으며 lease 세 값을 유지해 다음 단계가 같은
fencing을 이어받게 한다. 상태 변경은 조건부 `UPDATE`로 보호하고 바뀐 행이 1이 아니면 전체를
rollback한다.

AI 호출이 실패하면 빈 카드를 저장하지 않고 상태도 바꾸지 않으며 Provider 원문 오류를 DB에
넣지 않는다. 현재 슬라이스에는 Worker 실패 전이 정책이 없으므로 예외를 호출자에게 전달하고,
실행은 lease 만료 후 기존 claim 정책으로 재시도된다.

## 개인정보 경계

수집 목적: 장부와 상담 로그를 바탕으로 당사자의 협상 포지션을 구조화한다.

| 구분 | 항목 |
|---|---|
| Backend → AI 전달 가능 | 내부 anchor ID, 구조화된 매물·구입 조건, 날짜 신호, 개인정보를 제거한 상담 내용, 내부 `interaction_id`, source identity |
| 전달 금지 | 성명, 로그인 ID, 전화번호, 이메일, 생년월일, 인증·세션·CSRF 정보, `requested_by`, 치환 대응표, Secret, 프롬프트 원문 전체, 반대편 당사자 데이터 |
| 저장 | Backend가 검증한 구조화 포지션 카드, 거래 유형별 금액, 마스킹된 근거 인용과 offset, 안전한 모델 진단, 버전 정보 |
| 로그 금지 | 전체 프롬프트, 전체 모델 원문 응답, 상담 로그 전체 원문, 성명·연락처, 토큰·인증 헤더 |

실행 제어 값(`run_id`, `lease_owner`, `lease_expires_at`, `attempt_count`)과 DB 객체
(Session, Repository, `AgentRun`, SQLModel)는 Backend 내부 정보이며 AI 공개 계약에 넣지 않는다.

`agent_run`에 남기는 것은 비식별 요약뿐이다: 앵커 종류·ID, `input_data_version`,
`position_analysis_id`, cache hit 여부, 계약·prompt·workflow 버전, 안전한 provider·model 이름,
그리고 token 수와 latency. 전체 카드 본문과 전체 상담 로그를 `redacted_output_snapshot`에
중복 저장하지 않는다. 카드 본문은 position analysis와 자식 테이블이 소유한다.

`ProviderDiagnostics`가 total token만 주고 output이 없으면 `output_tokens`를 0으로 둔다.
total 값을 output 컬럼에 넣어 컬럼 의미를 왜곡하지 않는다.

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

## 중개 판정 계약

앵커 포지션 카드 1장과 반대편 후보 카드 N장을 **한 번의 구조화 출력 호출**로 판정한다
(F3-BR-01, F3-BR-02, F3-NF-04). 후보를 1장씩 개별 호출하지 않고 앵커를 후보 수만큼 반복
전송하지 않는다. 후보가 0건이면 요청 자체를 만들지 않으며 모델도 부르지 않는다.

### 등급 어휘와 화면 표기

| 계약값 | 화면 한국어 | 의미 |
|---|---|---|
| `STRONG` | 강함 | 지금 연결할 만하다 |
| `WEAK` | 약함 | 조건이 움직이면 가능하다 |
| `REJECTED` | 기각 | 성사 불가다 |

같은 의미에 동의어를 두지 않는다. `HIGH`, `LOW`, `EXCLUDED`, `강함`, `약함`은 저장값이나
계약값으로 쓰지 않는다. 화면 한국어는 표시 매핑이며 저장 어휘로 되돌리지 않는다.

행동 제안의 접촉 경로도 하나의 enum으로 고정한다.

| `ContactChannel` | 화면 한국어 |
|---|---|
| `CALL` | 통화 |
| `MESSAGE` | 문자 |
| `IN_PERSON` | 대면 |

이는 F3 판정 어휘이며 F1의 `client_interaction.interaction_channel`과 다른 축이다. F1은 아직
채널 값 목록을 확정하지 않았다.

### 왜 brokerage_id와 run_id가 없는가

승인된 개인정보 경계가 실행 제어 값(`run_id`, `brokerage_id`, `requested_by`, lease)을 AI
공개 계약에 넣지 않는다. 그래서 요청·결과 대조는 tenant 식별자가 아니라 **카드 ID**로 한다.
결과의 앵커 카드 ID와 후보 카드 ID 집합이 요청과 정확히 같아야 하며, 그것이 "이 결과가 이
요청에 대한 것인가"를 판정하는 기준이다. tenant 격리와 lease 확인은 Backend가 저장 직전에 DB
현재 상태로 따로 한다.

### 요청 계약

`BrokerageJudgmentRequest`

| 필드 | 의미 |
|---|---|
| `contract_version` | `brokerage-judgment:v1` 고정 |
| `anchor` | `JudgmentCard` 1장 |
| `candidates` | `JudgmentCard` N장. 1장 이상이어야 한다 |

`JudgmentCard`는 `card_id`(`negotiation_position_analysis.id`), `negotiation_side`,
`target_label`, 그리고 **포지션 카드 계약의 `PositionCardAnalysis` 그대로**를 담는다. 판정
입력은 곧 두 대리의 출력이므로 별도 표현을 만들면 두 규격이 갈라진다.

DTO가 강제하는 것: 후보 카드 ID는 중복될 수 없고, 앵커가 후보로 들어올 수 없으며, 모든 후보는
앵커의 **반대편** `negotiation_side`여야 한다.

### 결과 계약

`BrokerageJudgmentResult`는 `contract_version`, `target`, `candidates`, `prompt_version`,
`workflow_version`, `diagnostics`를 담는다. `target`은 모델이 만드는 값이 아니라
`BrokerageJudgmentTarget.from_request()`가 요청에서 결정적으로 복사한다.

`CandidateJudgment` 1건이 후보 1건에 대응한다.

| 필드 | 의미 | 요구사항 |
|---|---|---|
| `card_id` | 후보 카드 ID | — |
| `grade` | `STRONG`/`WEAK`/`REJECTED` | F3-BR-03 |
| `rank` | 1 이상 | F3-BR-04 |
| `comparison_basis` | 후보 간 비교 근거. 필수 | F3-BR-04 |
| `primary_obstacle` | 결정적 걸림돌 하나 | F3-BR-05 |
| `possible_concession` | 누가·무엇을·얼마나 움직이면 되는가 | F3-BR-06 |
| `recommended_action` | `contact_side`·`channel`·`message` | F3-BR-07 |
| `rejection_reason` | 기각 사유 | F3-BR-10 |
| `evidence` | `JudgmentEvidence` 1건 이상 | F3-TR-01 |

자유 문자열은 500자 상한이다. 상한을 두면 모델이 근거 대신 장문을 만들어 저장 비용과 개인정보
노출면을 키우는 것을 막는다.

`JudgmentEvidence`는 `evidence_side`, `field_name`과 포지션 카드의 `Evidence`를 **합성으로
재사용**한다. 근거 규칙을 두 곳에 복제하지 않기 위해서다.

발송 문안은 여기서 만들지 않는다. `message`는 무슨 말을 꺼낼지에 대한 한 문장 제안이고, 실제
문안은 사용자가 [문자 보내기]를 누를 때 생성한다 (F3-CR-07).

### 검증 규칙

| 계층 | 위치 | 확인 |
|---|---|---|
| 구조 | Pydantic DTO | 어휘, 필수값, 빈 문자열, 순위 하한, 기각 사유 유무, 근거 1건 이상, extra field |
| 요청·결과 | `validate_judgment_result()` | 계약 버전, 앵커 카드·측면 일치, 후보 집합 정확 일치, 순위 1..N 연속, 근거 출처 |
| DB 현재 상태 | Backend | lease, tenant, 앵커 입력 버전, 후보 snapshot과 카드 집합, offset |

거절 조건:

- 후보 ID가 누락되거나 요청에 없던 후보가 추가되면 실패
- 같은 후보가 두 번 나오면 실패
- 순위가 중복되거나 1부터 연속이 아니면 실패 (구멍이 있으면 "몇 번째로 보여줄 것인가"에 답할 수 없다)
- 기각 등급인데 기각 사유가 없으면 실패. 기각이 아닌데 사유가 있어도 실패
- 근거가 하나도 없으면 실패
- 결과의 앵커 카드 ID·측면·후보 집합이 요청과 다르면 실패

인용 근거에는 한 가지 규칙이 더 있다. **판정 단계에는 상담 원문이 없다.** 그래서 `QUOTE`는
그 카드가 **이미 갖고 있던** `(interaction_id, quote_text)` 쌍만 허용한다. 카드에 없는 인용은
모델이 만들어 낸 것이므로 거절한다. 카드 값을 비교해 판단한 것은 `INFERENCE`로 명시한다.

`assemble_candidates()`는 순서만 요청 순서로 되돌리고 등급·순위·근거를 고치거나 채워 넣지
않는다. 빠진 후보를 조용히 메우면 위 검증이 무의미해진다.

### LangGraph

[AI ADR-0002](../../../ai/references/decisions/ADR-0002-langgraph-adoption.md)는 F3 workflow의
상태 전이·재개 기반으로 LangGraph를 채택했다. **중개 판정에는 아직 쓰지 않는다.** 판정 자체가
구조화 출력 1회이고, 노드가 하나뿐인 graph는 상태 전이도 재개 지점도 만들지 않는 이름뿐인
wrapper가 되기 때문이다.

현재 F3의 단계 경계와 재개는 **Backend DB 상태**가 담당한다. Worker가 저장된 상태를 보고
이어서 처리하므로 프로세스가 죽어도 진행이 남는다. LangGraph checkpointer는 쓰지 않으며
checkpoint 저장소 제품도 확정되지 않았다. graph가 실제로 필요해지는 시점은 한 번의 AI 호출
안에서 도구 호출·재질의·분기가 생길 때이며, 그때 도입하고 `ai/` 안에 가둔다.

## 오류와 재시도 경계

- Provider 오류는 AI의 `ProviderError` 계층으로 표현하고 `retryable` 여부를 함께 준다.
- 결과가 요청과 맞지 않으면 `PositionCardContractError`이며 재시도로 해결되지 않는다.
- 재시도 횟수와 backoff는 Worker가 소유한다. AI SDK 자동 재시도는 꺼져 있다.
- 검증에 실패한 결과로 카드를 저장하지 않는다. 조용히 근거를 지우고 성공으로 위장하지 않는다.

## 구현 범위

### 구현됨

- `negotiation_side`, intent, urgency, contactability, evidence, price_kind 어휘
- 계약 버전 `position-card:v1`, prompt·workflow 버전 v1
- 요청·결과 DTO와 LISTING/REQUIREMENT 입력 격리
- `PositionCardGenerator` Protocol과 `LlmPositionCardGenerator` 구현
- 프롬프트와 모델 구조화 출력 schema
- 요청·결과 교차 검증 순수 함수
- Backend의 F1 snapshot 조립, 대리 측면별 상담 로그 범위, 날짜 신호 계산
- 요청자·담당자·로그 당사자 식별값과 자유 문자열 전체의 길이 보존 마스킹
- 모델 출력 자유 문자열의 개인정보 검증
- 실행 모델·prompt·workflow 바인딩의 최초 기록과 재시도 고정
- Backend가 만드는 target label
- 모델 입력 전체의 결정적 지문과 날짜 bucket
- cache key 계산, 대상·버전·상담 집합·지문까지 대조하는 cache lookup, cache hit 재사용
- AI 호출 전후 transaction 분리와 cache hit·miss 모두의 lease·바인딩·범위·source·지문 재검증
- cache hit 카드의 저장 직전 활성 상태 잠금 재조회와 동시 무효화 직렬화
- 카드·다중 가격·근거 저장과 quote offset 계산
- `ANCHOR_READY` 상태 전이
- 같은 cache key 저장 경합 처리
- Backend `AnchorType`과의 값 일치 계약 테스트
- Worker polling loop와 `claim_next_run` 연결, 저장된 상태 기준 단계 오케스트레이션
- Worker composition. DB `ai_model_config`에서 Provider·모델을 읽어 두 generator를 조립
- 같은 앵커·입력 버전의 활성·완료 실행 재사용과 `SUPERSEDED` 전이
- 결정적 SQL 후보 추출과 `CANDIDATES_READY`
- 후보 포지션 카드와 `CANDIDATE_CARDS_READY`
- 중개 판정 계약·생성기, `JUDGING`, 판정 결과 저장과 `COMPLETED`
- 결과 조회 API와 사용자 피드백 API
- F1 저장 후 자동 접수

### 아직 구현하지 않음 (`계획됨`)

- LangGraph production graph와 checkpointer. 카드 생성과 중개 판정 모두 구조화 출력 1회다
- SSE 진행 구독과 Frontend 후보 패널
- 15건 이후 후보의 추가 카드화. 남은 건수와 후보 metadata 조회까지만 있다
- AI 구성 변경 시 완료 결과 무효화. 재사용 키에 AI 구성이 들어가지 않는다
- 정정 상담 로그 생성 (F3-TR-02). 피드백만 저장한다
- `FAILED_RETRYABLE` 상태. 재시도는 상태 변경이 아니라 lease 반납으로 표현한다
- AI 판정 품질 평가

### 미확정

- 실제 모델 ID와 운영 Provider (AI-OQ-001, AI-OQ-002, AI-OQ-003)
- LangGraph checkpoint 저장 계약 (AI-OQ-004)

Provider와 모델은 Backend가 고르지 않는다. 호출 조립 지점이 `GenerationBinding`으로 주입한
generator, `model_config_id`와 비밀이 제거된 model snapshot을 Backend가 기록해 cache key에
사용할 뿐이다.

Worker composition은 구현됐다. Worker가 그 사무소의 활성 `ai_model_config`에서 Provider와
모델 이름을 읽어 두 generator를 조립한다. 코드에 기본 Provider나 기본 모델을 두지 않으며,
지원하지 않는 provider 문자열이나 이 프로세스에 구성되지 않은 Provider는 그 실행 하나만
`FAILED_TERMINAL`로 끝내고 Worker loop는 계속 돈다. **운영 Provider와 모델 ID 자체는 여전히
미확정**이라 `WORKER_ENABLED=true` 운영 배포는 하지 않는다.
