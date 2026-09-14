---
status: 결정
updated: 2026-09-08
---

# F1 장부 HTTP 계약

인증·오류의 공통 규칙은 [API 공통 계약](api-common.md)을 함께 읽는다. F1 저장에 따른 F3 자동 접수는 [F3 실행 계약](api-f3.md#f1-저장-후-자동-접수)을 확인한다.

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

구입장 생성 요청은 `party_id`와 `new_party` 중 하나를 필수로 받는다. 화면에는 기존 인물을 고르는
검색이 없으므로 새 손님은 대부분 `new_party`(`name` 필수, `phone` 선택)로 인물까지 함께 만든다.
매물장이 세대 생성 요청의 `parties`로 임대인·임차인을 함께 만드는 것과 같은 구조다. `new_party`를
쓸 때는 `privacy_consent`가 true여야 하며, 아니면 `PRIVACY_CONSENT_REQUIRED`로 거절하고 인물도
만들지 않는다. true이면 서버가 그 시각을 인물의 `privacy_consent_at`으로 기록한다. `party_id`를
보내는 경로는 이미 동의를 받은 기존 인물에 새 구입장을 잇는 용도로 열려 있지만, 인물 검색 화면이
없어 현재 클라이언트는 쓰지 않는다. 새 인물의 이름이 비어 있거나 두 필드가 모두 없으면
`VALIDATION_FAILED`다. `PropertyRequirementUpdateRequest`(PATCH)에는 이 필드가 없다. 구입장의
인물 연결은 생성 시점에 정해지며 이후 바꾸는 경로는 없다.

### 상담 로그

| Method | Path | 인증 | 동작 |
|---|---|---|---|
| GET | /api/v1/client-interactions | 세션 | 지정한 세대, 구입장 또는 인물의 상담 로그 조회 |
| POST | /api/v1/client-interactions | 세션·CSRF | 상담 로그 추가 |

조회는 세대, 구입장 또는 인물 중 하나의 식별자를 반드시 요구한다. 범위를 지정하지 않은 전체 조회는 제공하지 않으며 식별자가 없는 요청은 422로 거절한다.

상담 로그는 추가 전용이므로 수정과 삭제 경로를 두지 않는다. 로그를 추가하면 서버가 대상 세대 또는 구입장의 최종접촉일을 갱신한다. 무효 처리와 AI 생성 로그의 승인 경로는 현재 범위에 포함하지 않는다.

### 장부 상태값

세대 상태, 현 임대차 상태와 매물 상태의 값 목록은 아직 확정하지 않았다. 확정 전까지 서버는 이 값들을 고정된 열거형으로 검증하지 않고 문자열로 통과시킨다.
