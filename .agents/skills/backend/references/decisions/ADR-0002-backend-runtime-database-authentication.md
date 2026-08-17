---
status: 결정
updated: 2026-08-17
---

# ADR-0002: 백엔드 런타임·DB·인증 기반

- 상태: 승인됨
- 결정일: 2026-08-17

## 맥락

백엔드 기능 개발을 시작하려면 Python 실행환경, HTTP 프레임워크, DB 접근, 순수 SQL migration, 환경 설정, 인증 경계와 품질 도구를 하나의 재현 가능한 기준으로 확정해야 한다.

현재 MVP는 완성형 원장 제품보다 상담 자동화와 중개 판단의 시연·평가에 집중한다. 실제 로그인 UI와 비밀번호 인증은 범위 밖이지만, 모든 업무 API가 사용자와 중개사무소 문맥을 받을 수 있는 인증 구조는 필요하다.

## 결정

- Python 3.13과 uv를 사용하고 backend/가 독립된 pyproject.toml과 uv.lock을 소유한다.
- backend/src/를 애플리케이션 소스 루트로 사용하며 별도 최상위 Python 패키지를 만들지 않는다.
- FastAPI, 동기 SQLModel, psycopg3와 PostgreSQL 15를 사용한다.
- DB 스키마는 docs/db/migrate/의 순수 SQL을 Yoyo로 전진 적용한다. 애플리케이션 시작 시 migration을 실행하지 않는다.
- 사용자의 명시적 폴더 규칙에 따라 DB engine과 요청 세션을 src/domain/에 둔다. 이는 순수 domain 권장안의 예외이며 공개 DTO와 SQLModel 테이블 모델은 계속 분리한다.
- 환경변수는 APP_*, DB_*, AUTH_*, HTTP_*, LOG_*로 명시하고 src/core/config.py가 AppConfig, DbConfig, AuthConfig, HttpConfig, LogConfig에 직접 바인딩한다.
- python-dotenv가 APP_PROFILE 또는 APP_ENV에 따라 .env.local 또는 .env.prod를 읽는다. 프로세스 환경변수가 파일보다 우선한다.
- .env.local과 .env.prod는 비밀값이 없는 공개 환경 설정으로 Git에서 관리한다. DB URL·비밀번호·토큰과 같은 비밀 변수는 두 파일에서 키 자체를 제외하고 .env.example에 빈 값으로만 선언한다.
- Backend는 비밀 저장소에 직접 접근하지 않는다. Infra가 로컬·CI·운영 비밀값을 프로세스 환경변수로 주입하며 구체 저장소와 전달 방식은 별도 Infra 결정으로 확정한다.
- 브라우저 인증은 JWT가 아니라 PostgreSQL 서버 세션을 사용한다. 무작위 session·CSRF 원문은 브라우저에만 전달하고 DB에는 SHA-256 해시를 저장한다.
- 실제 비밀번호 로그인은 구현하지 않는다. local 환경에서 개발자가 생성한 임의 계정에만 개발 세션을 발급한다.
- 계정 활성 상태와 역할은 매 요청 다시 확인한다. 역할은 OWNER, STAFF, READ_ONLY다.
- Cookie는 HttpOnly와 SameSite=Lax를 사용하고 운영에서 Secure를 강제한다. 상태 변경 요청은 X-CSRF-Token을 검증한다.
- Ruff, Pyright, pytest와 pre-commit을 backend 품질 도구로 사용한다.
- 백엔드 전용 GitHub Actions workflow는 만들지 않고 추후 저장소 통합 CI에서 같은 명령을 실행한다.
- Dockerfile, Compose와 프로젝트 Docker 이미지는 이 결정 범위에 포함하지 않는다.
- Backend는 LangGraph와 프롬프트를 import하지 않으며 AI 실행 중 열린 DB transaction을 유지하지 않는다.

## 결과

개발자는 Python 3.13과 uv.lock으로 같은 환경을 재현하고, 설정·DB·인증 문맥이 준비된 FastAPI 기능을 추가할 수 있다. 공용 AWS 개발 DB의 DDL 적용은 애플리케이션 계정과 분리된 migration 계정으로 직렬 실행한다.

서버 세션은 즉시 폐기와 계정 비활성화를 단순하게 처리하지만 DB 조회와 만료 세션 정리가 필요하다. 실제 로그인과 비밀번호 정책을 도입할 때 세션 검증 구조는 유지하고 credential 검증·세션 발급 단계만 확장한다.

src/domain/에 영속성 구현을 둔 구조는 일반적인 순수 domain 분리와 다르다. 구조 변경이 필요할 정도로 업무 규칙과 adapter가 커지면 별도 ADR로 재검토한다.
