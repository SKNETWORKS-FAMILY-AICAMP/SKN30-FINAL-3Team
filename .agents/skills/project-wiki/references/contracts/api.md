---
status: 결정
updated: 2026-08-31
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
| POST | /api/v1/auth/development-session | local·dev 합성 전용 | 설정된 개발 계정의 서버 세션·CSRF 발급 |
| GET | /api/v1/auth/me | 서버 세션 | 현재 사용자와 역할, 그리고 브라우저에 보관된 기존 CSRF 토큰 반환 |
| DELETE | /api/v1/auth/session | 서버 세션·CSRF | 현재 세션 폐기 |

서버 세션 원문과 CSRF 원문은 각각 별도의 HttpOnly·SameSite=Lax Cookie로 전달하며, 서버 DB에는 두 값의 SHA-256 해시만 보관한다. `/auth/me`는 브라우저가 보낸 CSRF Cookie를 해당 세션의 해시와 상수 시간 비교한 뒤 같은 원문을 응답해 화면 메모리를 다시 채운다. 이 GET은 CSRF 토큰을 새로 만들거나 DB의 `csrf_token_hash`를 변경하지 않으므로 새로고침과 여러 탭이 서로의 토큰을 무효화하지 않는다. CSRF 원문을 반환하는 세션 발급·확인 응답은 `Cache-Control: no-store`로 캐시를 금지한다. CSRF Cookie가 없거나 세션의 해시와 다르면 403으로 거절한다. 상태 변경 요청은 응답으로 받은 값을 `X-CSRF-Token`에 실어야 한다. 로그아웃은 서버 세션을 폐기하고 두 Cookie를 함께 삭제한다. 배포된 dev에서는 두 Cookie에 `Secure`도 적용하고 세션을 유휴 30분·절대 12시간으로 제한한다. 개발 세션 route는 설정된 local·dev에만 등록하고 prod에는 등록하지 않는다. 공개 dev URL을 아는 사용자는 모두 같은 합성 계정 세션을 발급받을 수 있으므로 실제 개인정보와 인증정보를 사용하지 않는다. 실제 비밀번호 로그인 계약은 현재 MVP 범위에 포함하지 않는다.

오류 응답은 `code`, `message`, `request_id`를 포함하고 인증 실패는 401, 권한 부족은 403으로
구분한다. 이 envelope는 애플리케이션이 직접 만든 오류뿐 아니라 `/api/v1`의 route 404,
method 405와 요청 검증 422에도 적용한다. 생존·준비 상태를 확인하는 `/health/*`는 공개 업무 API
계약이 아니므로 framework 응답 형식을 유지할 수 있다. 예상하지 못한 예외는 500
`INTERNAL_SERVER_ERROR`의 고정 안전 문구로 변환하고 예외 원문이나 traceback을 응답하지 않는다.

`request_id`는 canonical UUID 문자열이다. 요청의 `X-Request-ID`도 이 형식일 때만 전파하고 그 밖의
값은 서버가 새 UUID로 교체한다.

Frontend는 HTTP `status`, `code`, `request_id`를 보존해 기능별 안전 문구와 복구 동작을 정한다.
서버 `message`를 그대로 사용자 문구로 쓰지 않는다. 현재 F2 multipart 경로도 공통 오류 응답
변환기를 사용하며, 계약에 없는 4xx는 일시적 5xx가 아니라 `contract` 오류로 분류한다. 세부 관측
조건과 로그 안전 필드는 [오류 관측 계약](observability.md)을 따른다.

## F1 장부 계약 (제안)

이 절은 `제안`이며 팀 검토 후 승인될 때 표시를 제거한다. 필드 목록의 정본은 [F1 데이터 항목](../../../../../docs/requirements/f1/data-fields.md)이고 여기서는 경로와 의미만 고정한다.

### 공통 규칙

- 모든 경로가 서버 세션을 요구한다. `brokerage_id`는 세션에서만 도출하고 요청 본문이나 쿼리로 받지 않는다.
- 상태를 바꾸는 POST, PATCH, DELETE는 `X-CSRF-Token`을 요구한다.
- DELETE는 소프트 삭제다. 행을 지우지 않고 `is_deleted`를 세워 목록에서 제외한다. 상담 로그와 매물 이력이 참조하고 있어 물리 삭제는 이력을 함께 잃는다. 낙관적 잠금을 위해 `row_version`을 질의 변수로 요구하며, 어긋나면 409를 돌려준다. 본문이 아니라 질의 변수인 이유는 DELETE가 본문을 싣지 않는 클라이언트에서도 같게 동작해야 하기 때문이다. 성공하면 본문 없이 204를 돌려준다.
- 금액은 원 단위 정수로 주고받는다. 억·만 단위 표시 변환은 클라이언트가 담당한다.
- 소프트 삭제된 행은 응답에서 제외한다.
- 목록 응답은 `items`, `total`, `limit`, `offset`을 포함하며 `total`은 현재 필터 조건의 전체 건수다.
- 같은 필터 파라미터를 반복하면 OR로 결합한다.
- 예약값 `__EMPTY__`는 해당 컬럼이 비어 있는 행을 뜻하며 다른 값과 함께 선택할 수 있다. `column-values` 응답도 같은 예약값과 건수를 목록에 포함한다. 값이 비어 있는 파라미터는 필터로 취급하지 않는다.
- 부분 수정은 PATCH를 사용하고 본문에 `row_version`을 요구한다. 값이 다르면 409로 거절하며 마지막 저장이 앞 변경을 덮어쓰지 않게 한다.
- 매물과 구입장 PATCH에서 요청값이 저장값과 모두 같으면 쓰기와 `row_version` 증가를 생략한다. 같은 값이어도 요청 `row_version`이 이미 낡았으면 409로 거절한다. 구입장의 `desired_complex_ids`는 순서가 아닌 단지 집합으로 비교하며 집합이 바뀌면 구입장 `row_version`도 올린다.
- 다른 중개사무소가 소유한 식별자는 403이 아니라 404로 응답해 존재 여부를 드러내지 않는다.

### 매물장

목록의 기준 행은 세대이며 매물이 아닌 세대도 반환한다. 매매·전세·월세 값이 비어 있는 행이 다수인 상태가 정상이다.

목록 응답의 각 행은 가장 최근 상담 로그 본문을 `latest_interaction_content`로 함께 싣는다. 행마다 별도 질의를 보내지 않도록 lateral join으로 붙이며, 로그가 없으면 null이다.

목록 응답의 각 행은 현재 유효한 인물 관계를 `parties`로 함께 싣는다. 매물장 33개 컬럼에 임대인·임대인 전화·임차인·임차인 전화가 있고(F1-GR-02), 공동명의도 세대당 한 행에 접어 표시해야 하므로(F1-GR-06) 목록이 인물을 빼면 행마다 상세를 다시 불러야 한다. 각 항목은 `role`, `role_index`, `is_primary`, `is_co_owner`, `valid_from`과 인물 요약(`id`, `party_type`, `name`, `alternate_name`, `privacy_consent_at`, `contacts`)을 갖는다. `valid_to`가 채워진 종료된 관계는 제외하고 `role`, `role_index` 순으로 정렬해 공동명의 표시 순서를 서버가 고정한다. 인물이 없는 세대가 정상이므로 `parties`는 빈 목록일 수 있으며, 목록과 상세는 같은 조립 규칙과 같은 필드를 쓴다.

세대 생성·수정 요청이 `parties`를 함께 실으면 세대 필드와 인물 관계는 한 트랜잭션에 저장한다. 인물 검증이 실패하면 세대 필드도 저장하지 않고 `row_version`도 올리지 않는다. 인물 없는 세대 자체는 정상이지만, 화면은 한 번의 요청을 전부 아니면 전무로 보고 성공했을 때만 서버 id와 새 `row_version`을 기록하므로, 세대만 저장되면 화면이 그 사실을 모른 채 PATCH는 낡은 버전으로 409를 받고 POST는 같은 세대를 다시 만든다.

세대 PATCH는 바꿀 필드가 하나도 없어도 시작에서 `row_version`을 검증한다. `parties`만 보내는 요청도 마찬가지이며 낡은 버전은 409로 거절한다. 인물 관계가 실제로 바뀌면 같은 트랜잭션에서 세대 `row_version`을 올린다. 인물은 별도 테이블이지만 화면에서는 세대 행의 칸이므로, 올리지 않으면 두 사람이 같은 세대의 임대인을 동시에 고쳐도 충돌이 잡히지 않고 나중 저장이 앞 변경을 조용히 덮어쓴다. 같은 인물을 다시 보낸 요청은 변경이 아니므로 버전을 올리지 않는다.

인물 요약은 화면이 실제로 그리는 범위로 한정한다. 성명, 별칭, 연락처와 동의 시각까지만 싣고 `party.memo`는 목록·상세 어느 쪽에도 싣지 않는다.

| Method | Path | 인증 | 동작 |
|---|---|---|---|
| GET | /api/v1/property-complexes | 세션 | 단지 목록. 이름 오름차순 |
| POST | /api/v1/property-complexes | 세션·CSRF | 단지 추가. 같은 중개사무소 안에서 이름 중복은 거절 |
| DELETE | /api/v1/property-complexes/{complex_id} | 세션·CSRF | 단지 삭제. `row_version` 질의 변수 필수. 세대가 남아 있으면 거절 |
| GET | /api/v1/property-units | 세션 | 세대 목록과 현재 매물 조건. 기본 정렬은 동·호 오름차순 |
| GET | /api/v1/property-units/column-values | 세션 | 현재 필터 범위에 실재하는 컬럼 값 목록과 건수 |
| GET | /api/v1/property-units/{unit_id} | 세션 | 세대 상세. 단지, 인물 관계, 매물 이력 포함 |
| POST | /api/v1/property-units | 세션·CSRF | 세대 추가 |
| PATCH | /api/v1/property-units/{unit_id} | 세션·CSRF | 세대 부분 수정 |
| DELETE | /api/v1/property-units/{unit_id} | 세션·CSRF | 세대 삭제. `row_version` 질의 변수 필수 |
| POST | /api/v1/property-units/{unit_id}/listings | 세션·CSRF | 해당 세대의 매물 건 등록 |
| PATCH | /api/v1/property-listings/{listing_id} | 세션·CSRF | 매물 건 조건 수정 |

세대와 매물 건은 `row_version`을 각각 보유하므로 한 요청으로 두 테이블을 함께 수정하지 않는다. 세대 삭제도 마찬가지로 매물 건을 수정하지 않는다. 매물 조회는 세대를 join하므로 세대가 감춰지면 그 세대의 매물 건도 응답에 나타나지 않는다.

같은 범위를 단건 경로에도 적용한다. 부모 세대가 삭제된 매물 건은 `PATCH /api/v1/property-listings/{listing_id}`에서 404이고, 상담 로그의 `listing_id`로도 쓸 수 없어 422 `VALIDATION_FAILED`가 된다. 매물 행 자체는 이력으로 남는다.

단지 삭제와 세대 추가는 같은 단지 행을 두고 직렬화된다. 두 요청이 동시에 들어오면 나중에 처리되는 쪽이 반드시 거절된다. 삭제가 먼저 반영되면 세대 추가가 `VALIDATION_FAILED`로, 세대 추가가 먼저 반영되면 삭제가 `COMPLEX_HAS_UNITS`로 거절된다. 따라서 삭제된 단지에 살아 있는 세대가 남는 상태는 생기지 않는다.

현재 구현된 필터는 세대와 최신 매물 건의 컬럼으로 한정한다. `complex_id`, `building_number`, `unit_number`, `floor_number`, `orientation`, `tenancy_status`, `lifecycle_status`, `unit_type`, `assigned_user_id`, `is_expanded`와 매물 건의 `listing_status`, `handover_condition`, `is_sale_available`, `is_jeonse_available`, `is_monthly_rent_available`를 지원한다. 임대인·임차인 등 인물 컬럼과 상담 로그 컬럼의 필터는 아직 제공하지 않는다.

빈 행 추가는 클라이언트 화면 상태로 처리한다. 저장하지 않고 닫은 빈 행은 서버에 전달하지 않으며, 저장 시점에 필수값을 갖춘 POST 한 번으로 확정한다.

### 구입장

| Method | Path | 인증 | 동작 |
|---|---|---|---|
| GET | /api/v1/property-requirements | 세션 | 구입장 목록. 각 행에 인물과 연락처를 포함한다. 기본 정렬은 최종접촉일 내림차순 |
| GET | /api/v1/property-requirements/column-values | 세션 | 현재 필터 범위에 실재하는 컬럼 값 목록과 건수 |
| GET | /api/v1/property-requirements/{requirement_id} | 세션 | 구입장 상세. 인물, 연락처, 희망 단지 포함 |
| POST | /api/v1/property-requirements | 세션·CSRF | 구입장 추가 |
| PATCH | /api/v1/property-requirements/{requirement_id} | 세션·CSRF | 구입장 부분 수정 |
| DELETE | /api/v1/property-requirements/{requirement_id} | 세션·CSRF | 구입장 행 삭제. `row_version` 질의 변수 필수 |

구입장은 인물이 행의 주체이고 화면 표에 손님과 연락처가 고정 컬럼으로 있으므로, 목록 응답이 `party`와 그 안의 `contacts`를 함께 싣는다. 행마다 상세를 다시 부르면 목록 한 번에 N번의 추가 요청이 생기고 다중 문자 발송처럼 여러 행을 한꺼번에 다루는 기능이 성립하지 않는다. 인물이 없는 구입장 행은 존재할 수 없으므로 `party`는 목록과 상세 모두에서 필수이며, 클라이언트는 이를 선택 필드로 다루지 않는다. 매물장 목록도 같은 이유로 인물을 싣는다. 두 장부의 차이는 인물의 필수 여부에서만 온다. 인물이 없는 세대는 정상이므로 매물장의 `parties`는 빈 목록을 허용한다.

개인정보 최소 노출은 장부 사이의 경계나 목록·상세 사이의 경계가 아니라 세션, 중개사무소 경계, 동의 여부와 응답 필드 범위로 지킨다. 두 장부의 목록과 상세는 모두 서버 세션을 요구하므로 로그인하지 않은 요청에는 인물이 나오지 않는다. 세션의 `brokerage_id`가 소유하지 않은 인물은 어떤 경로로도 나오지 않고, 동의가 없는 인물은 애초에 구입장으로 저장되지 않는다. 목록을 상세보다 좁게 두는 방식은 화면이 요구하는 인물 열을 채우지 못하면서 행마다 상세 조회를 부르게 해, 같은 개인정보를 더 많은 요청으로 흘리는 결과가 된다.

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

## F2 음성 분석 계약 (구현됨 · 1차 연동)

| Method | Path | 인증 | 동작 |
|---|---|---|---|
| POST | /api/v1/f2/analyses | 세션·CSRF | 음성을 RunPod `stt`로 전사하고 `sllm`으로 분석해 검토용 제안을 동기 반환 |

요청은 `multipart/form-data`이며 `audio`, `ledger_type`, `current_fields`,
`privacy_confirmed`를 받는다. `audio`는 비어 있지 않은 WAV·MP3·M4A이고 현재 상한은 25 MiB다.
`ledger_type`은 `매물장` 또는 `구입장`, `current_fields`는 필드명에서 문자열 또는 null로 가는 JSON
객체다. `privacy_confirmed`가 true가 아니면 422로 거절한다. Backend는 세션에서 사용자 문맥을
검증하지만 사용자·사무소 식별자는 모델에 보내지 않는다.

응답의 상담 유형은 `매도의뢰`, `매수문의`, `기타상담` 중 하나다. `기타상담`은 공동중개·단순문의와
불명확하거나 혼합된 상담을 합친 값이며 장부 필드 제안을 반환하지 않는다. 그 밖에 장부 불일치 여부,
필드별 현재값·제안값·상태·근거·기본 선택 여부, 불확실성,
상담 로그 초안과 서버가 확인한 주의 문구 확인 시각을 반환한다. 전사 전문, 모델 진단, 요청자와
Provider 오류 원문은 반환하지 않는다. 제안 응답만으로 장부를 저장하지 않으며 Frontend가 선택한 값을
부모 상세의 미저장 draft에 반영한다.

이 경로는 RunPod base model 연결을 검증하는 1차 동기 수직 슬라이스다. 영속 작업, Worker 재개,
SSE 단계 알림, 전사 재사용 재시도와 승인 감사 저장은 아직 구현하지 않았으며
`docs/architecture/f2/online-runtime.md`의 제안 구조를 대체하지 않는다. Backend와 RunPod 양쪽의 임시
음성은 각 요청 종료 시 삭제하고 애플리케이션 로그에는 음성·전사·제안 원문을 기록하지 않는다.

F2 route는 별도 사용자 기능 플래그 없이 항상 공개한다. Infra endpoint set이 `active`일 때만
Backend가 `AI_VLLM_SLLM_BASE_URL`과 `AI_VLLM_STT_BASE_URL`로 pipeline을 초기화한다. `offline`이면
Backend는 정상 기동하고 분석 요청만 503 `F2_UNAVAILABLE`로 종료한다. `active`인데 URL이 없으면
부분 활성화를 허용하지 않고 애플리케이션 시작을 설정 오류로 실패시킨다.

### 오류 코드

| code | HTTP | 발생 조건 |
|---|---|---|
| UNAUTHENTICATED | 401 | 세션이 없거나 만료됨 |
| COMPLEX_HAS_UNITS | 422 | 세대가 남아 있는 단지를 삭제하려 함 |
| FORBIDDEN | 403 | 역할 권한이 부족하거나 CSRF 토큰이 일치하지 않음 |
| NOT_FOUND | 404 | 대상이 없거나 다른 중개사무소 소유임 |
| METHOD_NOT_ALLOWED | 405 | `/api/v1` 경로에 허용되지 않은 HTTP method를 사용함 |
| ROW_VERSION_CONFLICT | 409 | 요청의 `row_version`이 저장된 값과 다름 |
| VALIDATION_FAILED | 422 | 입력 형식 또는 필수값 위반 |
| PRIVACY_CONSENT_REQUIRED | 422 | 개인정보 활용 동의 없이 구입장을 저장하려 함 |
| F2_UNAVAILABLE | 503 | RunPod endpoint가 offline이거나 STT·SLLM Provider 요청·응답을 사용할 수 없음 |
| F2_PROCESSING_FAILED | 502 | 공개할 수 없는 F2 내부 처리 오류 |
| INTERNAL_SERVER_ERROR | 500 | 공개할 수 없는 예상 밖 Backend 오류 |

세대 상태, 현 임대차 상태와 매물 상태의 값 목록은 아직 확정하지 않았다. 확정 전까지 서버는 이 값들을 고정된 열거형으로 검증하지 않고 문자열로 통과시킨다.

## F3 실행 계약

이 절은 현재 구현된 브라우저–Backend 공개 계약의 정본이다. 실행 요청을 `agent_run`에 `QUEUED`로
적재하고 현재 상태와 마지막 안전 결과를 조회하며, 저장된 카드·판정에 구조화 피드백을 남긴다.

이 절은 브라우저와 Backend 사이의 HTTP 계약만 다룬다. Backend와 AI 사이의 포지션 카드 입력·결과,
어휘와 근거 규칙은 [F3 AI 계약](f3-ai.md)이 소유하며 그 계약은 이 HTTP 경로로 노출되지 않는다.

| Method | Path | 인증 | 동작 |
|---|---|---|---|
| POST | /api/v1/f3/runs | 세션·CSRF | 교차 판정 실행을 적재하거나 같은 입력의 활성 실행 식별자를 반환 |
| GET | /api/v1/f3/runs/{run_id} | 세션 | 숫자 실행 ID로 현재 상태와 안전한 오류 정보를 조회 |
| GET | /api/v1/f3/runs/{run_id}/result | 세션 | 실행의 앵커 카드·후보 조회 조건·후보별 판정 결과를 현재 저장 단계까지 조회 |
| POST | /api/v1/f3/feedback | 세션·CSRF | 포지션 카드 또는 후보 판정에 구조화된 관심없음 사유를 기록 |

위 네 경로는 모두 현재 Backend에 **구현됨**이다. 결과 조회와 관심없음 피드백은 더 이상 미구현
후속 경로가 아니며 아래 각 절이 공개 계약의 정본이다. 상담 로그를 만드는 정정 피드백만 후속 범위다.

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

`POST /api/v1/f3/runs`는 Worker나 AI를 직접 호출하지 않고 `agent_run` 적재까지만 하므로 F3
실패가 F1 저장과 조회를 막지 않는다 (F3-CM-06).

### 활성 실행 중복 방지

같은 `(brokerage_id, anchor_type, anchor_id, input_data_version)`의 활성 루트
`CROSS_JUDGMENT` 실행이 있으면 새 행을 만들지 않고 기존 실행을 반환한다. 재사용 대상 상태는
`QUEUED`, `RUNNING`, `ANCHOR_READY`, `CANDIDATES_READY`, `CANDIDATE_CARDS_READY`, `JUDGING`이다.
재사용과 신규 접수 모두 `202 Accepted`와 같은 응답 형태를 사용하며 별도 `reused` 필드는 공개하지
않는다.

동시 요청은 PostgreSQL transaction advisory lock으로 사무소·앵커 단위 직렬화한다. 프로세스
메모리 lock은 여러 API 인스턴스 사이의 중복 생성을 막지 못하므로 사용하지 않는다. 잠금을 잡은 뒤
앵커와 최신 `row_version`을 다시 읽고 재사용 조회와 신규 적재를 같은 transaction에서 수행한다.

재사용할 때 기존 실행의 `requested_by`와 `trigger_type`은 바꾸지 않는다. 두 값은 실행 행을 최초로
만든 요청자와 접수 계기를 나타내며 이후 같은 실행을 조회한 사용자 목록이 아니다. 후속 재사용 호출
이력은 현재 별도로 저장하지 않는다.

`COMPLETED`, `FAILED_TERMINAL`, `SUPERSEDED` 실행은 재사용하지 않는다. 특히 완료 결과는 앵커
`row_version`만 같다고 재사용하지 않는다. 상담 로그 집합, 세대·단지·당사자 관계와 AI 구성이
그대로인지 접수 시점에 증명할 identity가 아직 없기 때문이다. 따라서 F3-CR-12 중 **활성 실행
중복 방지**만 구현됐고, 변경 없는 완료 판정 결과 재사용은 후속 범위다.

`LISTING` 앵커는 사무소가 같고 `property_listing.is_deleted = false`이며 **부모 세대도
`property_unit.is_deleted = false`** 여야 한다. F1의 세대 소프트 삭제는 이력 보존을 위해 딸린 매물
행을 건드리지 않으므로 매물 자신의 삭제 표시만으로는 부족하다. 세 조건 중 하나라도 어긋나면 다른
사무소의 식별자와 똑같이 404로 답해 삭제 여부와 존재 여부를 구분해서 드러내지 않는다.
`REQUIREMENT` 앵커는 사무소와 `property_requirement.is_deleted = false`를 본다.

### F1 저장 후 자동 접수

다음 네 저장이 성공하면 Backend가 F3 실행을 자동 접수한다 (F3-CR-01, F3-CR-02).

이 실행이 자동으로 수행하는 범위는 **앵커 포지션 카드 생성까지**다 ([ADR-0018](../decisions/ADR-0018-f3-save-trigger-anchor-card-scope.md)). 앵커 카드를 저장해
`ANCHOR_READY`가 되면 실행은 거기서 멈추고, 후보 조회·후보 카드·중개 판정은 사용자가
`POST /api/v1/f3/runs`로 판정을 요청할 때 이어서 수행한다 (F3-CR-01~04, 2026-08-31 개정).
저장 하나가 모델 판정까지 완주하던 종전 계약을 대체한다. 결과를 볼 의사가 없는 저장에서도
판정 비용이 들었고, 그 비용을 사용자가 선택한 적이 없기 때문이다.

| 저장 경로 | 앵커 | 접수 조건 |
|---|---|---|
| `POST /api/v1/property-units/{unit_id}/listings` | 매물 | 신규 등록 |
| `PATCH /api/v1/property-listings/{listing_id}` | 매물 | 거래 유형·가격·명도 조건·상태·의뢰인 등 판정 입력의 실제 변경 |
| `POST /api/v1/property-requirements` | 구입장 | 신규 등록 |
| `PATCH /api/v1/property-requirements/{requirement_id}` | 구입장 | 거래 유형·예산·면적·평형·이사일·만료일·상태·공동중개·희망 단지 등 판정 입력의 실제 변경 |

자동 접수는 F1 저장 transaction이 commit된 뒤 별도 transaction으로 실행한다. 접수 중 오류가
발생해도 이미 성공한 F1 저장과 응답을 되돌리거나 실패로 바꾸지 않는다 (F3-CM-06, F3-NF-07).
요청 처리 중 Worker나 AI를 호출하지 않고 기존 `queue_cross_judgment_run`으로 `agent_run` 적재까지만
수행한다.

F1 응답 형태에는 실행 ID나 F3 상태를 추가하지 않는다. 화면은 `POST /api/v1/f3/runs`로 실행을
확인하며, 같은 앵커·입력 버전의 활성 실행이면 저장 시 자동 생성된 실행 ID를 그대로 돌려받는다.
자동 실행의 `trigger_type`은 `LEDGER_SAVE`이고 직접 실행 요청의 `USER_REQUEST`와 구분한다. 기존
활성 실행을 재사용할 때는 최초 실행의 `trigger_type`과 `requested_by`를 바꾸지 않는다. **예외는
`LEDGER_SAVE` 실행에 사용자의 판정 요청이 들어온 경우다.** 실행이 `QUEUED`면 다음 최초 선점이
전체 판정을 수행하고, `RUNNING`이면 현재 lease의 Worker가 앵커 카드 뒤로 계속 진행하도록
`trigger_type`을 요청자의 값으로 옮긴다. `ANCHOR_READY`에서 멈춰 있으면 기존 lease를 비우고
같은 실행을 즉시 선점 가능하게 해 후보 조회부터 이어서 진행한다. 이 계획된 이어받기 선점은 실패
재시도가 아니므로 `attempt_count`를 늘리지 않는다. `requested_by`는 최초 값을 유지한다. 이어받기는
앵커 카드를 다시 만들지 않으므로 요청 시 추가 카드 비용이 없고, 화면은 종전과 같은 실행 ID를
돌려받는다. `trigger_type`이 바뀌면 자동 접수에서 시작했다는 사실과 이전 상태는
`f3_ledger_save_run_resumed` 로그로 남는다.

PATCH의 접수 여부는 요청에 필드가 포함됐는지가 아니라 F1 서비스가 저장 직전에 비교한 **실제 변경
필드**로 판단한다. 메모·담당자 같은 운영 필드만 바꾸거나 가격·예산 등 기존과 같은 값을 다시
보내면 새 실행을 만들지 않는다. 희망 단지는 순서가 아니라 집합 변경을 판정 입력 변경으로 본다.
자동 접수 실패 로그에는 앵커 종류·ID와 예외 타입만 남기고 상담 원문·연락처·성명은 남기지 않는다.

자동 접수와 AI 처리는 별도 경계다. 접수된 실행은 검토된 합성 전용 환경에서
`WORKER_ENABLED=true`와 `F3_ALLOW_SYNTHETIC_PROTOTYPE=true`를 모두 명시한 경우에만 현재 Worker가
처리한다. 합성 opt-in이 없으면 Worker는 DB·Provider 접근과 작업 선점 전에 기동을 거절한다. 현재
Infra 기본값은 두 설정 모두 `false`다. `MASKED` 입력 조립은 아직 구현되지 않았으므로 실제 F1
사용자 데이터를 처리하는 근거로 합성 opt-in을 사용할 수 없다. 실사용 연결 전에는 ADR-0014에 따라
Backend 마스킹을 구현하고 `input_privacy_mode=MASKED`로 전환해야 한다.

### 요청자 기록

요청자는 세션에서 도출한 내부 `app_user.id` 하나이며 `agent_run.requested_by`에 저장한다. 실행
요청과 상태 조회 응답 모두 요청자를 싣지 않고 Backend 조회는 세션의 `brokerage_id`로 격리한다.

처리 위치, 접근 주체, 보존 기간과 삭제 방식의 정본은
[개인정보 정책](../privacy/policy.md)의 `agent_run.requested_by` 절이다.

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
`run_group_id`와 `parent_run_id`를 싣지 않는다.

`agent_run.failure_message`는 외부 AI 오류 원문, 내부 예외와 개인정보가 들어올 수 있는 내부 운영
정보이므로 DB 원문을 그대로 공개하지 않는다. 공개 응답의 `failure_code`와 `failure_message`는
allowlist 기반으로만 만든다.

| 저장된 failure_code | 공개 failure_code | 공개 failure_message |
|---|---|---|
| 없음 | `null` | `null` |
| `LEASE_EXPIRED_MAX_ATTEMPTS` | `LEASE_EXPIRED_MAX_ATTEMPTS` | 실행이 최대 시도 횟수를 초과해 종료되었습니다 |
| `INPUT_SUPERSEDED` | `INPUT_SUPERSEDED` | 실행 중 입력 데이터가 변경되어 결과를 반영하지 않았습니다 |
| 그 밖의 모든 값 | `EXECUTION_FAILED` | 실행에 실패했습니다. 잠시 후 다시 시도해 주세요 |

allowlist에 없는 내부 실패는 `EXECUTION_FAILED`로 일반화한다. 개인정보, 외부 서비스 오류 원문과
내부 예외 문구는 어떤 경우에도 응답에 싣지 않는다. 공개 코드를 늘리려면 이 표를 먼저 갱신한다.

`status`는 DB에 저장된 문자열을 그대로 공개하며 표기는 `agent_run.status`의 기본값 `QUEUED`에 맞춰
**대문자 스네이크로 통일한다.** 클라이언트가 대소문자를 함께 분기하지 않게 하기 위한 규칙이다.

`QUEUED`와 `RUNNING`은 Worker가 작업을 잡았는지를 나타내는 실행 제어 상태이고, `ANCHOR_READY`
이후는 실제 업무 처리 진행 상태다. 클라이언트는 이 둘을 같은 진행률 축에 두지 않는다.

| status | 구분 | 의미 | 현재 |
|---|---|---|---|
| `QUEUED` | 실행 제어 | 실행 적재 완료, Worker 대기 | 구현됨 |
| `RUNNING` | 실행 제어 | Worker가 lease를 걸고 선점함 | 구현됨 |
| `ANCHOR_READY` | 업무 처리 | 앵커 카드 검증·저장 완료 | 구현됨 |
| `CANDIDATES_READY` | 업무 처리 | 결정적 SQL 후보 스냅샷 완료 | 구현됨 |
| `CANDIDATE_CARDS_READY` | 업무 처리 | 후보 카드 생성·재사용 완료 | 구현됨 |
| `JUDGING` | 업무 처리 | 전체 후보 중개 판정 실행 중 | 구현됨 |
| `COMPLETED` | 업무 처리 | 검증을 통과한 최종 결과 저장 | 구현됨 |
| `FAILED_RETRYABLE` | 종료 | 재시도 가능한 일시 오류 | 제안 · 미구현 |
| `FAILED_TERMINAL` | 종료 | 재시도해도 성공하지 않는 영구 오류 | 구현됨 |
| `CANCELLED` | 종료 | 현재 화면에서 더 실행할 필요 없음 | 제안 · 미구현 |
| `SUPERSEDED` | 종료 | 실행 중 입력 데이터가 변경됨 | 구현됨 |

Backend가 실제로 기록하는 상태는 아홉 가지다. 실행 접수 시 `QUEUED`, Worker 선점 시 `RUNNING`,
검증된 앵커 카드 확보 시 `ANCHOR_READY`, 결정적 SQL 후보 스냅샷 저장 시 `CANDIDATES_READY`,
상위 후보 카드 ID 저장 시 `CANDIDATE_CARDS_READY`, 중개 판정 호출 중 `JUDGING`, 검증된 결과를
원자 저장하면 `COMPLETED`, 입력 버전·상담 범위가 실행 중 바뀌면 `SUPERSEDED`, lease 최대 시도
초과나 영구 오류이면 `FAILED_TERMINAL`이다. `ANCHOR_READY`,
`CANDIDATES_READY`, `CANDIDATE_CARDS_READY`, `JUDGING`은 중간 상태라 `completed_at`을 채우지
않고 `COMPLETED`에서 채운다. `ANCHOR_READY`는 자동 접수된 실행이 사용자 요청을 기다리며 머무는
지점이기도 하다. 이 상태의 `LEDGER_SAVE` 실행은 Worker 선점과 최대 시도 초과 정리에서 모두
제외되므로 시도 횟수가 늘지 않고 `LEASE_EXPIRED_MAX_ATTEMPTS`로 종료되지도 않는다. 사용자가 끝내 판정을 요청하지 않으면
실행은 `ANCHOR_READY`로 남으며, 보존 기간이 지난 실행 정리는 `retention_until`·`purged_at`을
쓰는 별도 작업의 범위다. 후보가 0건이면 모델 호출과 `JUDGING` 없이 빈 결과를 확정하고
`CANDIDATE_CARDS_READY`에서 바로 `COMPLETED`로 간다. Worker polling·handler가 이 유스케이스를
상태 순서대로 호출한다. 그 밖의 상태는 아직 만들지 않는다.

후보 조회 조건, 전체 후보 집합과 상위 후보의 `position_analysis_id`는
`match_evaluation.candidate_selection_snapshot`에 저장한다. 상태 조회 경로는 이 내부 snapshot을
노출하지 않으며 아래 결과 조회 경로만 허용된 필드로 변환한다.

상태 집합의 의미 정본은
[온라인 실행 아키텍처](../../../../../docs/architecture/f3/online-runtime.md)이고, 서버는 이 값을 고정
열거형으로 검증하지 않는다. 이 경로는 polling용 상태 조회이며 SSE 진행 구독은 아직 없다.

### 실행 결과 조회

`GET /api/v1/f3/runs/{run_id}/result`는 상태를 변경하지 않으므로 CSRF 토큰을 요구하지 않는다.
상태 조회와 동일하게 세션의 `brokerage_id`, 루트 `CROSS_JUDGMENT`, 숫자 `run_id >= 1` 조건으로
격리하며 없는 실행·다른 사무소 실행·하위 실행·다른 실행 유형은 모두 404로 답한다.
상한 조정 전 `candidate-selection:v2`로 완료된 과거 결과와 현재 `v3` 결과를 모두 조회한다.

후보 목록은 `limit`과 `offset`으로 페이지 처리한다. `limit` 기본값은 20이고 범위는 1..100,
`offset` 기본값은 0이며 0 이상이다. 범위를 벗어나면 422로 답한다. 페이지 대상은 카드화된 상위
5건만이 아니라 결정적 SQL에 포함된 **전체 후보**다. 카드화·판정되지 않은 후보도 목록에 남고
`selected_for_cards=false`, 판정·근거 필드는 `null` 또는 빈 목록으로 반환한다.

진행 중인 실행은 완료를 가장하지 않고 마지막으로 영속화된 안전 단계까지만 반환한다.

- `QUEUED`·`RUNNING`: 실행 정보, 빈 카드·후보 결과
- `ANCHOR_READY`: 앵커 카드의 공개 `analysis`와 카드 근거
- `CANDIDATES_READY` 이후: 실제 SQL 조회 조건, 전체·카드화·잔여 건수와 페이지 후보
- `COMPLETED`: 후보별 등급·순위·비교 근거·걸림돌·양보·추천 행동·기각 사유·판정 근거

앵커 카드 snapshot 전체를 반환하지 않고 `analysis`만 반환한다. 계약 버전, 프롬프트·워크플로 버전,
Provider·모델 진단은 공개하지 않는다. 실행의 사무소·요청자·모델 설정·입출력 snapshot·토큰 수,
`run_group_id`, `parent_run_id`, lease 값과 내부 실패 원문도 싣지 않는다. 실패 정보는 상태 조회와
같은 allowlist 변환을 적용한다. 카드·판정 근거의 `quote_text`는 현재 승인된
`SYNTHETIC_PROTOTYPE` 입력에서 저장된 공개 근거만 반환하며 실제 F1 데이터 연결은 마스킹 구현 전까지
허용하지 않는다. 카드 저장 단계가 실행 snapshot에 기록한 `input_privacy_mode`가
`SYNTHETIC_PROTOTYPE`인 실행만 카드·후보·근거 내용을 공개한다. 표식이 없거나 다른 값이면 실행
상태와 안전한 실패 정보만 반환하고 나머지 결과는 빈 값으로 둔다.

응답 최상위는 실행·앵커 정보와 `anchor_card`, `candidate_selection`, `candidates`,
`candidates_total`, `limit`, `offset`이다. `candidate_selection`은 `criteria`, `total_count`,
`carded_count`, `remaining_count`를 싣는다. 후보는 장부 `candidate_id`, SQL 순위·점수·금액·접수일,
카드화 여부와 저장된 경우에만 중개 판정 및 근거를 싣는다. 빈 후보 결과도 같은 형태로 200을 반환한다.

후보의 `candidate_id`는 반대편 장부 레코드 식별자다. `LISTING` 앵커의 후보는 `property_requirement.id`,
`REQUIREMENT` 앵커의 후보는 `property_listing.id`다. 이 경로는 후보의 성명, 연락처와 표시 이름을 싣지
않으므로 화면은 자기 사무소의 F1 조회 결과로 표시 이름을 만든다.

후보의 `judgment_id`는 저장된 중개 판정의 식별자이며 관심없음 피드백의 `target_id`로 쓴다. 판정 전
후보와 카드화되지 않은 후보는 `null`이다. 실행 내부 식별자가 아니라 사무소 범위 피드백 대상 식별자이며,
피드백 경로가 같은 사무소 소유를 다시 확인한다.

### 관심없음 피드백

`POST /api/v1/f3/feedback`은 F3-TR-03의 [관심없음]만 기록하는 상태 변경 경로이므로 세션과 CSRF를
요구한다. 응답은 `201 Created`다. 요청은 다음 네 필드만 허용하며 선언하지 않은 필드는 422로
거절한다.

```json
{
  "target": "MATCH_CANDIDATE",
  "target_id": 81,
  "reason": "WRONG_JUDGMENT",
  "field_name": "match_grade"
}
```

- `target`: `POSITION_ANALYSIS` 또는 `MATCH_CANDIDATE`
- `target_id`: 1 이상의 숫자 식별자. `POSITION_ANALYSIS`이면 결과 조회의
  `anchor_card.position_analysis_id`, `MATCH_CANDIDATE`이면 후보의 `judgment_id`다
- `reason`: `CONDITION_MISMATCH`, `ALREADY_CONTACTED`, `WRONG_JUDGMENT`, `OTHER`
- `field_name`: 선택값. `negotiation_intent`, `urgency`, `preferred_timing`,
  `flexible_conditions`, `inflexible_conditions`, `contactability_status`, `price`,
  `match_grade`, `evaluation_basis`, `primary_obstacle`, `possible_concession`,
  `recommended_action`, `exclusion_reason` 중 하나

| 화면 사유 | reason |
|---|---|
| 조건 안 맞음 | `CONDITION_MISMATCH` |
| 이미 연락함 | `ALREADY_CONTACTED` |
| 판정이 틀림 | `WRONG_JUDGMENT` |
| 기타 | `OTHER` |

`feedback_type`은 클라이언트 입력이 아니라 서버가 `NOT_INTERESTED`로 고정한다. `detail`,
`original_value`, `corrected_value`, `correction_interaction_id`, `brokerage_id`, `created_by`도 받지
않는다. 따라서 이 경로에는 상담 원문, 이름, 연락처와 자유문자를 저장할 입력란이 없다.

대상은 세션의 `brokerage_id`로 조회한다. 없거나 다른 사무소 소유이면 모두 404로 답하고,
`brokerage_id`와 `created_by`는 세션에서만 도출한다. 응답은 아래 필드만 포함하며 사무소와 작성자
식별자를 싣지 않는다.

```json
{
  "feedback_id": 12,
  "target": "MATCH_CANDIDATE",
  "target_id": 81,
  "feedback_type": "NOT_INTERESTED",
  "reason": "WRONG_JUDGMENT",
  "field_name": "match_grade",
  "created_at": "2026-08-24T12:00:00+09:00"
}
```

F3-TR-02의 정정은 이번 계약에 포함하지 않는다. 정정은 값을 저장하는 것만으로 끝나지 않고 추가 전용
상담 로그를 생성해 다음 판정 입력에 포함해야 한다. 그 유스케이스와 권한·개인정보 경계를 함께
구현하기 전까지 `CORRECTION`이나 임의 정정값을 공개 입력으로 받지 않는다. 작성자 식별자의 처리
정본은 [개인정보 정책](../privacy/policy.md)의 `ai_decision_feedback.created_by` 절이다.

### Worker 선점과 lease

Worker는 API가 아니라 `claim_next_run(worker_id)` 유스케이스로 실행을 가져간다. 선점 대상은 루트
`CROSS_JUDGMENT` 실행 중 `QUEUED`이거나, lease가 만료됐고 시도 횟수가 상한 미만인 구현된 진행
상태(`RUNNING`, `ANCHOR_READY`, `CANDIDATES_READY`, `CANDIDATE_CARDS_READY`, `JUDGING`)다.
다만 `trigger_type`이 `LEDGER_SAVE`이고 상태가 `ANCHOR_READY`인 실행은 선점 대상에서 제외한다.
저장이 자동으로 하는 일은 앵커 카드까지이므로 lease가 만료돼도 다시 집어가지 않는다. 사용자가
판정을 요청해 `trigger_type`이 옮겨지면 lease가 없는 계획된 handoff로 즉시 선점 대상이 되며,
그 첫 선점은 `attempt_count`를 늘리지 않는다. 최초
`QUEUED`만 `RUNNING`으로 바꾸고
재선점한 진행 상태는 보존한다. `JUDGING`을 재선점하면 최초 판정 바인딩과 후보 집합을 다시
검증한 뒤 중개 판정 호출부터 안전하게 재실행한다. 5분짜리 lease와 시도 횟수를 기록하며,
만료됐는데 시도 횟수가 3회 이상이면
`FAILED_TERMINAL`과 `LEASE_EXPIRED_MAX_ATTEMPTS`로 종료한다. heartbeat는 쓰지 않는다.

`lease_owner`, `lease_expires_at`, `attempt_count`는 내부 실행 제어 값이므로 상태 조회 응답에 싣지
않는다.

배포용 Worker 프로세스(`backend/src/worker.py`)는 `claim_next_run`을 RDS polling으로 호출하고,
저장된 상태를 기준으로 앵커 카드 → 후보 SQL → 후보 카드 → 중개 판정 유스케이스를 같은 lease
아래에서 진행한다. 자동 접수된 실행은 앵커 카드를 저장한 뒤 같은 lease 안에서 더 진행하지 않고
`ANCHOR_READY`에 남기며 그 자리에서 lease를 비운다. 이 주차는 `trigger_type`을 조건에 넣은
갱신이라 사용자 판정 요청과 같은 행에서 직렬화된다. Worker가 실행을 읽은 뒤 주차하기 전에
요청이 들어왔으면 주차하지 않고 후보 조회로 이어 간다. 빈 큐에서는 2초 timeout으로 stop event를 기다려 busy loop를 만들지 않는다.
일시 Provider 오류는 상태를 보존하고 lease를 즉시 만료시켜 다음 선점이 재시도하며, 영구 계약·
설정 오류는 `FAILED_TERMINAL`, 입력 변경은 `SUPERSEDED`로 기록한다. raw 예외와 Provider 원문은
failure 컬럼에 저장하지 않는다.

`WORKER_ENABLED=false`는 기존처럼 readiness만 제공하고 실행을 claim하지 않는다. `true`는 DB와
LLM Provider 설정을 기동 전에 검증한 뒤 polling을 시작한다. 코드가 Provider·모델 기본값을 정하지
않고 사무소별 `ai_model_config`의 capability별 최신 활성 설정을 사용한다. 실제 배포 설정 기본값은
계속 `false`이며 운영 Provider 선택과 활성화는 별도 운영 결정이다. 구현됨·미구현의 정본은
[온라인 실행 아키텍처](../../../../../docs/architecture/f3/online-runtime.md)의 현재 구현 절이고,
배포 계약은 [백엔드 ADR-0003](../../../backend/references/decisions/ADR-0003-dev-deployment-contract.md)이다.

`anchor_type`과 `anchor_id`는 `target_listing_id`와 `target_requirement_id` 중 **정확히 하나**가 있을
때만 도출한다. 둘 다 없거나 둘 다 있는 실행은 존재하지 않는 앵커를 정상 응답으로 내보내지 않고
`INTERNAL_SERVER_ERROR`로 답한다. DB에 해당 CHECK 제약이 없어 응용 계층에서 막는다.

## Time Keeper 일정 계약 (제안)

이 절은 `제안`이며 팀 검토 후 승인될 때 표시를 제거한다. Time Keeper는 F1 장부에 이미 있는 날짜
컬럼에서 "언제까지 무엇을 해야 하는가"를 뽑아 한 목록으로 돌려주는 **읽기 전용** 조회다. 새 테이블을
만들지 않고, 장부를 바꾸지 않으며, 모델을 호출하지 않는다. 날짜 계산은 SQL과 순수 함수가 한다
(F3 17장 "만기 보드 → F1", "날짜 계산 → 코드").

| Method | Path | 인증 | 동작 |
|---|---|---|---|
| GET | /api/v1/time-keeper/agenda | 세션 | 기한이 다가온 일정과 할 일을 종류별로 조회 |

상태를 바꾸지 않으므로 CSRF 토큰을 요구하지 않는다. `brokerage_id`는 세션에서만 도출한다.

### 조회 조건

| 질의 변수 | 기본값 | 범위 | 의미 |
|---|---|---|---|
| `within_days` | 90 | 1~730 | 앞으로 며칠까지 볼지. F1-AL-01의 "기본 3개월"을 일수로 옮긴 값 |
| `overdue_days` | 7 | 0~365 | 이미 지난 기한을 며칠까지 함께 볼지 |
| `recontact_days` | 30 | 1~365 | 마지막 접촉 후 며칠이면 재연락 대상으로 볼지 (F1-AL-03) |
| `revalidation_days` | 30 | 1~365 | 매물 접수 후 며칠이면 조건 재확인 대상으로 볼지 |
| `per_category_limit` | 3 | 1~100 | 한 종류에서 실을 최대 건수 |
| `limit` | 50 | 1~500 | 페이지 크기 |
| `offset` | 0 | 0 이상 | 페이지 시작 위치 |

`recontact_days`·`revalidation_days`·`per_category_limit`의 기본값은 MVP 조정값이며 승인된
요구사항 수치가 아니다. 사무소별 설정 위치는 [미해결 질문](../open-questions.md)에 남긴다.

### 종류 어휘

`category`는 **고정 열거형이 아니다.** 계약과 일정 테이블이 생기면 값이 늘어나므로 클라이언트는
모르는 값을 오류로 다루지 않고 코드를 그대로 표시한다. 현재 서버가 내보내는 값은 다음 일곱 가지다.

| category | 원천 | 성격 |
|---|---|---|
| `TENANCY_EXPIRY` | `property_unit.tenancy_expiry_date` | 저장된 날짜 |
| `CLIENT_TENANCY_EXPIRY` | `property_requirement.current_tenancy_expiry_date` | 저장된 날짜 |
| `REQUEST_EXPIRY` | `property_requirement.request_expiry_date` | 저장된 날짜 |
| `MOVE_IN` | `property_requirement.desired_move_in_date` | 저장된 날짜 |
| `LISTING_RECONTACT` | `property_unit.last_contact_at` + `recontact_days` | 주기 규칙 |
| `CLIENT_RECONTACT` | `property_requirement.last_contact_at` + `recontact_days` | 주기 규칙 |
| `LISTING_REVALIDATION` | `property_listing.received_at` + `revalidation_days` | 주기 규칙 |

계약 체결일, 계약금·중도금·잔금 지급일, 임장·매물 방문일, 신고·서류 제출 기한과 명도일은
**대응 데이터가 없어 이 계약에 없다.** 앞의 넷은 계약·일정 테이블(F1-CT-01~03, F1-SC-01~05)이
미구현이기 때문이고, 명도일은 `handover_condition`이 "만기후" 같은 자유 문구이지 날짜가 아니기
때문이다. 해당 테이블이 생기면 이 표에 종류를 더한다.

종료된 구입 의뢰(`status <> 'ACTIVE'`)와 내려간 매물(`status <> 'RECEIVED'`)은 제외한다. F1이 상태
값 목록을 확정하지 않았으므로 서버가 신규 저장에 쓰는 기본값만 진행 중으로 본다. F3 후보 추출과
같은 판단이며 값이 확정되면 두 곳을 함께 고친다.

### 응답

```json
{
  "items": [
    {
      "category": "TENANCY_EXPIRY",
      "due_date": "2026-08-31",
      "days_until_due": -3,
      "unit_id": 1,
      "listing_id": null,
      "complex_name": "연희 캐슬",
      "building_number": "101",
      "unit_number": "1",
      "tenancy_status": null,
      "requirement_id": null,
      "demand_type": null,
      "requirement_status": null,
      "assigned_user_id": null,
      "last_contact_at": "2026-08-31T02:27:17.135229Z",
      "contacts": [
        {
          "role": "LANDLORD",
          "is_primary": true,
          "party": {
            "id": 7,
            "party_type": "PERSON",
            "name": "김임대",
            "alternate_name": null,
            "privacy_consent_at": "2026-01-01T00:00:00Z",
            "contacts": [
              {
                "id": 11,
                "contact_method": "PHONE",
                "contact_value": "010-1234-5678",
                "contact_label": null,
                "is_primary": true,
                "contactability_status": "UNKNOWN"
              }
            ]
          }
        }
      ]
    }
  ],
  "categories": [{ "category": "TENANCY_EXPIRY", "total": 2 }],
  "total": 2,
  "limit": 50,
  "offset": 0,
  "as_of": "2026-09-03",
  "within_days": 90,
  "overdue_days": 7,
  "per_category_limit": 3
}
```

`categories`에는 **창 안에 실제로 있는 종류만** 실린다. 0건인 종류는 행 자체가 없으므로 화면이
해당되는 것만 그린다. `total`과 `categories[].total`은 `per_category_limit`을 적용하기 **전** 건수라
`items`에 실린 수보다 클 수 있고, 그 차이가 곧 화면의 "외 N건"이다.

세대에서 온 행은 구입장 필드가, 구입장에서 온 행은 세대 필드가 null이다. 어느 쪽인지는 `category`가
정한다. 표시 문자열은 서버가 만들지 않고 장부 목록과 같이 원본 값을 싣는다.

인물 요약은 구입장 목록과 같은 범위다. 목록에서 곧바로 연락으로 넘어가는 화면이 인물마다 상세를
다시 부르지 않게 하려는 것이며, 개인정보 노출 범위는 세션과 중개사무소 경계로 지킨다. 세대 행은
현재 유효한 인물 관계를, 구입장 행은 의뢰 인물 본인을 싣는다.

### 기준일

`as_of`는 서버가 D-day를 계산한 업무일이며 중개사무소 시간대(UTC+09:00)로 정한다. UTC 날짜를 쓰면
한국 시각 오전 9시 이전에 하루가 밀려 `days_until_due`가 전부 어긋난다. 주기 규칙으로 만드는 종류의
`timestamptz` → 날짜 변환도 PostgreSQL에서 같은 시간대로 맞춘다. 브라우저는 자기 시계로 다시 계산하지
않고 서버가 준 `days_until_due`를 그대로 쓴다.

정렬은 `due_date` 오름차순이며 같은 날짜에서는 `category`와 식별자로 안정화한다. 정렬이 흔들리면
페이지를 넘길 때 같은 행이 다시 나오거나 건너뛴다.
