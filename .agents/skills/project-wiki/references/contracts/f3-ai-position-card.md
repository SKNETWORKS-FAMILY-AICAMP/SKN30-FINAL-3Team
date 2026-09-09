---
status: 결정
updated: 2026-09-04
---

# F3 포지션 카드 Backend–AI 계약

이 문서는 포지션 카드의 어휘·입력·결과·근거 규격이다. 버전·책임·진단·개인정보·오류는 [F3 공통 계약](f3-ai-common.md)을 함께 읽는다. 카드의 공개 어휘·분석·근거 의미를 변경하거나 해석할 때는 소비자인 [중개 판정 계약](f3-ai-brokerage.md)도 확인한다.

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

## 카드 생성 경계

### 후보 카드 재사용 경계

후보 포지션 카드는 별도 AI 계약이나 생성기를 만들지 않고 앵커 카드와 같은
`PositionCardGenerator`와 검증·저장 경로를 쓴다. 다른 것은 실행의 앵커가 아닌 결정적 SQL
후보 snapshot의 상위 5건을 대상으로 하고, 앵커와 반대인 `negotiation_side`를 쓴다는 점뿐이다.
이 상한은 [F3-BR-12·13](../../../../../docs/requirements/f3/delegates-and-brokerage.md)의
2026-08-31 승인 결정이며 기존 상위 15건 규칙을 대체한다.

- 각 후보의 현재 `row_version`, 상담 범위 identity와 입력 fingerprint를 준비·저장 시점에
  다시 확인한다.
- 같은 대상·입력·모델·프롬프트·워크플로의 유효한 캐시가 있으면 모델을 호출하지 않는다.
- 후보 카드는 child 실행을 만들지 않고 루트 `agent_run`에 귀속한다.
- 입력 준비와 저장은 순차 처리하고 DB transaction 밖의 모델 호출만 병렬 실행한다.
  전부 확보한 뒤에만 `CANDIDATE_CARDS_READY`로 전이한다. 일부 생성이 실패해도 다른 성공
  카드는 각각 재검증 후 저장하여 재사용하며, 상태는 `CANDIDATES_READY`를 유지한다.
- 후보가 0건이면 모델을 호출하지 않고 빈 카드 목록을 기록한 뒤 상태를 전이한다.

이 단계도 ADR-0014의 `SYNTHETIC_PROTOTYPE` 입력만 허용한다. 실사용 F1 마스킹은
아직 승인하지 않았으며, 합성 입력의 Provider 범위는
[ADR-0026](../decisions/ADR-0026-general-ai-provider-and-model-profiles.md)와
[ADR-0027](../decisions/ADR-0027-bedrock-gpt56-luna-dev-poc.md)를 따른다.

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
