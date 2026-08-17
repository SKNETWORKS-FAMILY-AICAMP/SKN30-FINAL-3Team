---
status: 결정
updated: 2026-08-17
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
