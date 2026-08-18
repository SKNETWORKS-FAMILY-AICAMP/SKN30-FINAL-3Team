---
status: 결정
updated: 2026-08-18
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

## F3 포지션 카드·매칭 판정 계약 (제안)

이 절은 `제안`이며 팀 검토 후 승인될 때 표시를 제거한다. 등급 어휘와 하드 게이트 규칙의 정본은 [F3 판정 규칙](../../../../../docs/requirements/f3/delegates-and-brokerage.md)이고 여기서는 경로와 의미만 고정한다.

### 공통 규칙

- 두 경로 모두 서버 세션과 `X-CSRF-Token`을 요구한다. 카드와 판정 결과가 저장되고 `agent_run`이 남으므로 조회가 아니라 상태 변경이다.
- `brokerage_id`는 세션에서만 도출한다. 다른 중개사무소의 식별자는 404로 응답한다.
- 금액은 요청·응답 모두 억 단위 실수로 주고받는다. 저장은 원 단위 정수다.
- 등급은 모델이 정하지 않는다. 중개 판정은 걸림돌·양보·행동만 서술하고 등급·점수는 서버가 계산한다. 같은 입력이면 같은 등급이 나온다.

| Method | Path | 인증 | 동작 |
|---|---|---|---|
| POST | /api/v1/position-cards | 세션·CSRF | 세대 또는 구입장 1건의 포지션 카드 생성. 모델 호출 1회 |
| POST | /api/v1/match-evaluations | 세션·CSRF | 구입장을 앵커로 후보 추출·카드 확보·중개 판정·등급 산출 |

### 포지션 카드

`unit_id`와 `requirement_id` 중 정확히 하나를 지정한다. 둘 다 주거나 둘 다 비우면 422다.

응답의 `cache_hit`은 저장된 카드를 그대로 돌려줬다는 뜻이다. 캐시 키는 대상 식별자, 프롬프트 버전, 상담 로그 건수와 최종 로그 시각으로 만든다. 로그가 하나라도 늘면 카드를 다시 생성한다.

`evidence`는 카드 항목별 근거다. `is_inferred`가 참이면 로그 원문에 근거가 없다는 뜻이며, 저장 시에도 `evidence_type`이 `INFERENCE`가 된다. 인용문이 있어도 원본 상담 로그 행을 찾지 못하면 추적 불가로 낮춰 기록한다.

### 매칭 판정

`requirement_id`가 앵커다. `as_of`는 인도 가능일 계산의 기준일이며 생략하면 오늘이다. 케이스 재현에만 쓴다.

후보 추출 상한은 장부 표기 예산이 아니라 **앵커 카드의 추정값**이다. 추정값이 없을 때만 표기 예산으로 물러난다. 상한 15%까지는 협상 여지로 보고 후보에 남긴다.

응답의 `selection`은 후보 추출 결과 전체다. 게이트 밖으로 빠졌거나 상위 N건 컷에 걸린 세대를 사유와 함께 싣는다. 모델을 태우기 전에 무엇이 왜 빠졌는지 보이는 것이 이 필드의 목적이다.

`candidates`에는 **기각 후보도 포함한다.** 판정 수 = 노출 수 + 기각 수이며 서버가 컷하지 않는다. 기각 사유는 `hard_gates`에, 확인이 필요해 한 단계 강등된 사유는 `hold`와 `flags`에 담는다.

`llm_calls`와 `cache_hits`는 계측값이다. 캐시가 전부 비었을 때 호출 수는 앵커 1 + 후보 수 + 판정 1이다.

### 오류 코드

| code | HTTP | 발생 조건 |
|---|---|---|
| AI_UNAVAILABLE | 503 | AI 런타임이 없거나, route에 맞는 Provider가 설정되지 않았거나, 일시적으로 호출할 수 없음 |
| AI_RESPONSE_INVALID | 502 | 모델이 응답했으나 구조화 출력으로 쓸 수 없음 |

AI 설정이 없어도 애플리케이션은 기동한다. F3 경로만 503이고 F1 장부 기능은 그대로 동작한다. 응답에 Provider 종류나 모델 이름을 싣지 않는다.
