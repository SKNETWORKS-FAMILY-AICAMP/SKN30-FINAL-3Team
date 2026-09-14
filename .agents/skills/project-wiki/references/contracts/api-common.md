---
status: 결정
updated: 2026-09-08
---

# API 공통 계약

HTTP API를 변경할 때 이 문서와 해당 [기능 계약](api.md)을 함께 읽는다.

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
| F2_BUSY | 429 | 다른 F2 분석이 진행 중이며 재시도 필요; `Retry-After: 5` |
| F2_PROCESSING_FAILED | 502 | 공개할 수 없는 F2 내부 처리 오류 |
| INTERNAL_SERVER_ERROR | 500 | 공개할 수 없는 예상 밖 Backend 오류 |
