---
status: 결정
updated: 2026-08-19
---

# API 계약 규칙

구체적인 API는 기능 기획이 승인될 때 추가한다.

## 기본 규칙

- 공개 요청·응답 모델과 DB 테이블 모델을 분리한다.
- 입력, 출력, 오류, 인증, 권한과 부수 효과를 명시한다.
- 날짜와 시간은 타임존을 포함한 ISO 8601 형식을 사용한다.
- 호환되지 않는 변경은 버전 전략과 마이그레이션 계획을 함께 제시한다.
- 장시간 작업은 동기 요청에 가두지 않고 작업 식별자를 반환하는 방식을 검토한다.
- 추적을 위해 요청 또는 실행 식별자를 전파한다.
- 개인정보를 응답, 오류 또는 로그에 불필요하게 노출하지 않는다.

## 모델 경계 후보

- SQLModel `table=True`: 저장소 내부 테이블 모델
- Pydantic 또는 별도 SQLModel 데이터 모델: API 입력·출력
- OpenAPI: HTTP 계약의 기계 판독 가능한 표현

## 초기 Backend 계약

| Method | Path | 인증 | 동작 |
|---|---|---|---|
| GET | /health/live | 불필요 | 프로세스 생존 확인 |
| GET | /health/ready | 불필요 | PostgreSQL 준비 상태 확인 |
| POST | /api/v1/auth/development-session | local 전용 | 설정된 개발 계정의 서버 세션·CSRF 발급 |
| GET | /api/v1/auth/me | 서버 세션 | 현재 사용자와 역할 반환 |
| DELETE | /api/v1/auth/session | 서버 세션·CSRF | 현재 세션 폐기 |

서버 세션은 HttpOnly Cookie로 전달하며 상태 변경 요청은 X-CSRF-Token을 요구한다. 개발 세션 발급 경로는 운영 애플리케이션에 등록하지 않는다. 실제 비밀번호 로그인 계약은 현재 MVP 범위에 포함하지 않는다.

오류 응답은 code, message, request_id를 포함하고 인증 실패는 401, 권한 부족은 403으로 구분한다.

## F1 장부 계약 (제안)

이 절은 `제안`이며 팀 검토 후 승인될 때 표시를 제거한다. 필드 목록의 정본은 [F1 데이터 항목](../../../../../docs/requirements/f1/data-fields.md)이고 여기서는 경로와 의미만 고정한다.

### 공통 규칙

- 모든 경로가 서버 세션을 요구한다. `brokerage_id`는 세션에서만 도출하고 요청 본문이나 쿼리로 받지 않는다.
- 상태를 바꾸는 POST와 PATCH는 `X-CSRF-Token`을 요구한다.
- 금액은 원 단위 정수로 주고받는다. 억·만 단위 표시 변환은 클라이언트가 담당한다.
- 소프트 삭제된 행은 응답에서 제외한다.
- 목록 응답은 `items`, `total`, `limit`, `offset`을 포함하며 `total`은 현재 필터 조건의 전체 건수다.
- 같은 필터 파라미터를 반복하면 OR로 결합한다.
- 예약값 `__EMPTY__`는 해당 컬럼이 비어 있는 행을 뜻하며 다른 값과 함께 선택할 수 있다. `column-values` 응답도 같은 예약값과 건수를 목록에 포함한다. 값이 비어 있는 파라미터는 필터로 취급하지 않는다.
- 부분 수정은 PATCH를 사용하고 본문에 `row_version`을 요구한다. 값이 다르면 409로 거절하며 마지막 저장이 앞 변경을 덮어쓰지 않게 한다.
- 다른 중개사무소가 소유한 식별자는 403이 아니라 404로 응답해 존재 여부를 드러내지 않는다.

### 매물장

목록의 기준 행은 세대이며 매물이 아닌 세대도 반환한다. 매매·전세·월세 값이 비어 있는 행이 다수인 상태가 정상이다.

| Method | Path | 인증 | 동작 |
|---|---|---|---|
| GET | /api/v1/property-units | 세션 | 세대 목록과 현재 매물 조건. 기본 정렬은 동·호 오름차순 |
| GET | /api/v1/property-units/column-values | 세션 | 현재 필터 범위에 실재하는 컬럼 값 목록과 건수 |
| GET | /api/v1/property-units/{unit_id} | 세션 | 세대 상세. 단지, 인물 관계, 매물 이력 포함 |
| POST | /api/v1/property-units | 세션·CSRF | 세대 추가 |
| PATCH | /api/v1/property-units/{unit_id} | 세션·CSRF | 세대 부분 수정 |
| POST | /api/v1/property-units/{unit_id}/listings | 세션·CSRF | 해당 세대의 매물 건 등록 |
| PATCH | /api/v1/property-listings/{listing_id} | 세션·CSRF | 매물 건 조건 수정 |

세대와 매물 건은 `row_version`을 각각 보유하므로 한 요청으로 두 테이블을 함께 수정하지 않는다.

현재 구현된 필터는 세대와 최신 매물 건의 컬럼으로 한정한다. `complex_id`, `building_number`, `unit_number`, `floor_number`, `orientation`, `tenancy_status`, `lifecycle_status`, `unit_type`, `assigned_user_id`, `is_expanded`와 매물 건의 `listing_status`, `handover_condition`, `is_sale_available`, `is_jeonse_available`, `is_monthly_rent_available`를 지원한다. 임대인·임차인 등 인물 컬럼과 상담 로그 컬럼의 필터는 아직 제공하지 않는다.

빈 행 추가는 클라이언트 화면 상태로 처리한다. 저장하지 않고 닫은 빈 행은 서버에 전달하지 않으며, 저장 시점에 필수값을 갖춘 POST 한 번으로 확정한다.

### 구입장

| Method | Path | 인증 | 동작 |
|---|---|---|---|
| GET | /api/v1/property-requirements | 세션 | 구입장 목록. 기본 정렬은 최종접촉일 내림차순 |
| GET | /api/v1/property-requirements/column-values | 세션 | 현재 필터 범위에 실재하는 컬럼 값 목록과 건수 |
| GET | /api/v1/property-requirements/{requirement_id} | 세션 | 구입장 상세. 인물, 연락처, 희망 단지 포함 |
| POST | /api/v1/property-requirements | 세션·CSRF | 구입장 추가 |
| PATCH | /api/v1/property-requirements/{requirement_id} | 세션·CSRF | 구입장 부분 수정 |

현재 구현된 필터는 `demand_type`, `status`, `classification`, `workflow_stage`, `assigned_user_id`다.

접수일과 최종접촉일은 별개 필드이며 정렬에는 최종접촉일을 사용한다. 희망 평형은 복수 값을 허용한다. 금액, 면적, 이사일은 사용자 입력 원문과 파싱값을 함께 저장하고 응답에서도 함께 반환한다.

인물의 개인정보 활용 동의가 없으면 구입장 저장을 거절한다. 동의 사실은 인물 단위로 기록하며 동의 문구, 보존 기간과 철회 절차는 아직 확정하지 않았다.

### 상담 로그

| Method | Path | 인증 | 동작 |
|---|---|---|---|
| GET | /api/v1/client-interactions | 세션 | 지정한 세대, 구입장 또는 인물의 상담 로그 조회 |
| POST | /api/v1/client-interactions | 세션·CSRF | 상담 로그 추가 |

조회는 세대, 구입장 또는 인물 중 하나의 식별자를 반드시 요구한다. 범위를 지정하지 않은 전체 조회는 제공하지 않으며 식별자가 없는 요청은 422로 거절한다.

상담 로그는 추가 전용이므로 수정과 삭제 경로를 두지 않는다. 로그를 추가하면 서버가 대상 세대 또는 구입장의 최종접촉일을 갱신한다. 무효 처리와 AI 생성 로그의 승인 경로는 현재 범위에 포함하지 않는다.

### 오류 코드

| code | HTTP | 발생 조건 |
|---|---|---|
| UNAUTHENTICATED | 401 | 세션이 없거나 만료됨 |
| FORBIDDEN | 403 | 역할 권한이 부족하거나 CSRF 토큰이 일치하지 않음 |
| NOT_FOUND | 404 | 대상이 없거나 다른 중개사무소 소유임 |
| ROW_VERSION_CONFLICT | 409 | 요청의 `row_version`이 저장된 값과 다름 |
| VALIDATION_FAILED | 422 | 입력 형식 또는 필수값 위반 |
| PRIVACY_CONSENT_REQUIRED | 422 | 개인정보 활용 동의 없이 구입장을 저장하려 함 |

세대 상태, 현 임대차 상태와 매물 상태의 값 목록은 아직 확정하지 않았다. 확정 전까지 서버는 이 값들을 고정된 열거형으로 검증하지 않고 문자열로 통과시킨다.

## F3 실행 계약 (제안)

이 절은 `제안`이며 팀 검토 후 승인될 때 표시를 제거한다. 현재 구현 범위는 실행 요청을 검증해
`agent_run`에 `QUEUED`로 적재하고 그 실행의 현재 상태를 조회하는 것까지다. 결과와 후보 조회, 피드백
경로는 아직 없다.

| Method | Path | 인증 | 동작 |
|---|---|---|---|
| POST | /api/v1/f3/runs | 세션·CSRF | 교차 판정 실행을 대기 상태로 적재하고 실행 식별자를 반환 |
| GET | /api/v1/f3/runs/{run_id} | 세션 | 숫자 실행 ID로 현재 상태와 안전한 오류 정보를 조회 |

요청 본문은 앵커만 받는다. `anchor_type`은 `LISTING` 또는 `REQUIREMENT`이고 `anchor_id`는 1 이상의
정수다. 선언하지 않은 필드가 있으면 422로 거절한다.

```json
{ "anchor_type": "LISTING", "anchor_id": 123 }
```

`brokerage_id`와 요청자는 세션에서만 도출한다. 실행 상태, 실행 종류와 에이전트 종류는 서버가 정하며
클라이언트가 지정할 수 없다. 응답은 `202 Accepted`이고 사무소 식별자, 요청자와 입력 스냅샷을 싣지 않는다.

```json
{
  "run_id": 1,
  "run_group_id": "018f7c9e-0f2f-7c1e-9a3b-2f7c9e0f2f7c",
  "status": "QUEUED",
  "anchor_type": "LISTING",
  "anchor_id": 123,
  "input_data_version": 1,
  "created_at": "2026-08-19T02:13:44.512834+00:00"
}
```

`input_data_version`은 앵커가 된 매물 또는 구입장의 `row_version`이다. 같은 화면을 다시 열었을 때
같은 판정인지 구분하는 기준이 된다 (F3-CM-05). 앵커가 없거나 다른 중개사무소 소유이면 404로 답한다.

같은 앵커·입력 버전의 활성 실행을 재사용하는 중복 실행 정책(F3-CR-12)과 Worker 획득은 아직 구현하지
않았다. 이 경로는 AI 실행을 호출하지 않으므로 F3 실패가 F1 저장과 조회를 막지 않는다 (F3-CM-06).

### 실행 상태 조회

`run_id`는 `agent_run.id` 숫자 PK다. `run_group_id`는 내부 실행 묶음 식별자이므로 외부 조회 키로
사용하지 않는다. 상태 변경이 없는 GET이므로 CSRF 토큰을 요구하지 않는다.

조회는 `brokerage_id`와 루트 `CROSS_JUDGMENT` 조건(`parent_run_id IS NULL`)으로 격리한다. 다른
중개사무소의 실행, 내부 하위 실행과 다른 실행 유형은 모두 404로 답해 숫자 ID로 존재 여부를 넘겨짚을
수 없게 한다. `run_id`가 1 미만이면 422다.

```json
{
  "run_id": 51,
  "status": "QUEUED",
  "anchor_type": "LISTING",
  "anchor_id": 123,
  "input_data_version": 3,
  "created_at": "2026-08-19T02:13:44.512834+00:00",
  "started_at": null,
  "completed_at": null,
  "failure_code": null,
  "failure_message": null
}
```

응답에는 사무소 식별자, 요청자, 모델 설정·스냅샷, 프롬프트·워크플로 버전, 입출력 스냅샷, 토큰 수,
`run_group_id`와 `parent_run_id`를 싣지 않는다. `failure_message`는 DB 계약상 개인정보를 담지 않는
안전한 설명이라는 전제로 그대로 노출한다.

`status`는 DB에 저장된 문자열을 그대로 공개하며 표기는 `agent_run.status`의 기본값 `QUEUED`에 맞춰
**대문자 스네이크로 통일한다.** 클라이언트가 대소문자를 함께 분기하지 않게 하기 위한 규칙이다.

`QUEUED`와 `RUNNING`은 Worker가 작업을 잡았는지를 나타내는 실행 제어 상태이고, `ANCHOR_READY`
이후는 실제 업무 처리 진행 상태다. 클라이언트는 이 둘을 같은 진행률 축에 두지 않는다.

| status | 구분 | 의미 | 현재 |
|---|---|---|---|
| `QUEUED` | 실행 제어 | 실행 적재 완료, Worker 대기 | 구현됨 |
| `RUNNING` | 실행 제어 | Worker가 lease를 걸고 선점함 | 구현됨 |
| `ANCHOR_READY` | 업무 처리 | 앵커 카드 저장 완료 | 제안 · 미구현 |
| `CANDIDATES_READY` | 업무 처리 | 결정적 SQL 후보 스냅샷 완료 | 제안 · 미구현 |
| `CANDIDATE_CARDS_READY` | 업무 처리 | 후보 카드 생성·재사용 완료 | 제안 · 미구현 |
| `JUDGING` | 업무 처리 | 전체 후보 중개 판정 실행 중 | 제안 · 미구현 |
| `COMPLETED` | 업무 처리 | 검증을 통과한 최종 결과 저장 | 제안 · 미구현 |
| `FAILED_RETRYABLE` | 종료 | 재시도 가능한 일시 오류 | 제안 · 미구현 |
| `FAILED_TERMINAL` | 종료 | 재시도해도 성공하지 않는 영구 오류 | 구현됨 |
| `CANCELLED` | 종료 | 현재 화면에서 더 실행할 필요 없음 | 제안 · 미구현 |
| `SUPERSEDED` | 종료 | 실행 중 입력 데이터가 변경됨 | 제안 · 미구현 |

Backend가 실제로 기록하는 상태는 세 가지뿐이다. 실행 접수 시 `QUEUED`, Worker 선점 시 `RUNNING`,
lease 최대 시도 초과 시 `FAILED_TERMINAL`이다. 나머지는 아직 만들지 않는다.

상태 집합의 의미 정본은
[온라인 실행 아키텍처](../../../../../docs/architecture/f3/online-runtime.md)이고, 서버는 이 값을 고정
열거형으로 검증하지 않는다. 이 경로는 polling용 상태 조회이며 SSE 진행 구독은 아직 없다.

### Worker 선점과 lease

Worker는 API가 아니라 `claim_next_run(worker_id)` 유스케이스로 실행을 가져간다. 선점 대상은 루트
`CROSS_JUDGMENT` 실행 중 `QUEUED`이거나, lease가 만료됐고 시도 횟수가 상한 미만인 `RUNNING`이다.
선점하면 `RUNNING`으로 바꾸고 5분짜리 lease와 시도 횟수를 기록하며, 만료됐는데 시도 횟수가 3회
이상이면 `FAILED_TERMINAL`과 `LEASE_EXPIRED_MAX_ATTEMPTS`로 종료한다. heartbeat는 쓰지 않는다.

`lease_owner`, `lease_expires_at`, `attempt_count`는 내부 실행 제어 값이므로 상태 조회 응답에 싣지
않는다. Worker 프로세스와 polling loop 자체는 아직 구현하지 않았다.

`anchor_type`과 `anchor_id`는 `target_listing_id`와 `target_requirement_id` 중 **정확히 하나**가 있을
때만 도출한다. 둘 다 없거나 둘 다 있는 실행은 존재하지 않는 앵커를 정상 응답으로 내보내지 않고
`INTERNAL_SERVER_ERROR`로 답한다. DB에 해당 CHECK 제약이 없어 응용 계층에서 막는다.
