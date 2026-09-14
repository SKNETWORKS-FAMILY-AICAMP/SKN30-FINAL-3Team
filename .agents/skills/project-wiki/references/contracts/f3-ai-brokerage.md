---
status: 결정
updated: 2026-09-04
---

# F3 중개 판정 Backend–AI 계약

버전·책임·진단·개인정보·오류는 [F3 공통 계약](f3-ai-common.md)을 함께 읽는다. 입력 카드의 어휘·분석·근거 의미를 변경하거나 해석할 때는 [포지션 카드 계약](f3-ai-position-card.md)도 읽는다.

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
| `candidates` | 반대편 `JudgmentCard` 1~5장 |

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
