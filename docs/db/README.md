# 데이터베이스 SQL 관리

이 디렉터리는 PostgreSQL 15 기준 보존 DDL과 순차 전진 migration SQL을 관리한다. 특정 migration 도구의 명령 사용법은 다루지 않는다.

백엔드 DB 계층은 PostgreSQL 15, SQLModel과 순수 SQL migration으로 결정되었다. 적용 도구와 애플리케이션 실행법은 백엔드 ADR 및 backend/README.md에서 관리하며, 이 문서는 SQL 파일 자체의 규칙만 정의한다.

공유 환경에 적용하는 최초 migration은 `CREATE EXTENSION vector`로 pgvector를 활성화한다. Terraform은 SQL을 실행하거나 extension schema를 소유하지 않는다. 현재 migration 기준선에는 아직 이 결정이 반영되지 않았으므로 첫 공유 DB 적용 전 별도 배포 작업에서 migration을 갱신하고 PostgreSQL 15에서 검증해야 한다.

## 디렉터리

| 경로 | 용도 | 실행 여부 |
|---|---|---|
| archive/ | 전달받은 대형 DDL과 과거 설계의 보존본 | 실행하지 않음 |
| migrate/ | 새 환경과 기존 환경에 순서대로 적용할 전진 migration | 번호순 적용 |

archive의 F1/F2/F3 표기는 원문 추적을 위해 유지한다. 실행 migration과 신규 DB 객체에는 원장, 상담 자동화, 에이전트 실행, 협상 포지션, 매칭 평가 등 업무 용어를 사용한다.

## 현재 기준선

현재 기준선은 27개 테이블과 13개 전진 migration이다.

| 파일 | 도메인 | 테이블 수 | 주요 테이블 |
|---|---|---:|---|
| 001_CREATE_BROKERAGE_PLATFORM.sql | 중개 플랫폼 | 3 | brokerage, app_user, ai_model_config |
| 002_CREATE_PROPERTY_LEDGER.sql | 매물·수요 원장 | 9 | 세대, 매물, 손님, 희망 단지, 상담 로그 |
| 003_CREATE_CONSULTATION_AUTOMATION.sql | 상담 자동화 | 4 | 장부 초안, 전사 작업, 필드·상담 제안 |
| 004_CREATE_AGENT_EXECUTION.sql | 에이전트 실행 | 2 | agent_run, agent_capability_call |
| 005_CREATE_NEGOTIATION_POSITION.sql | 협상 포지션 | 2 | 포지션 분석, 상담 원문 근거 |
| 006_CREATE_MATCH_EVALUATION.sql | 매칭 판정 | 3 | 판정 헤더, 후보별 판정·근거 |
| 007_CREATE_AI_EVALUATION.sql | AI 평가 | 2 | 판단 피드백, 실험 평가 결과 |
| 008_CREATE_AUTHENTICATION.sql | 인증 | 1 | user_session |
| 009_ALTER_PROPERTY_LEDGER_FIELDS.sql | 매물·수요 원장 확장 | 0 | 세대 스펙, 공동중개, 현 거주지 만기, 분류·진행단계 |
| 010_ALTER_PARTY_PRIVACY_CONSENT.sql | 매물·수요 원장 확장 | 0 | 인물 개인정보 활용 동의 |
| 011_ALTER_AGENT_EXECUTION_LEASE.sql | 에이전트 실행 확장 | 0 | Worker 선점 lease와 시도 횟수 |
| 012_CREATE_NEGOTIATION_POSITION_PRICE.sql | 협상 포지션 확장 | 1 | 카드의 거래 유형별 표기·추정 금액 |
| 013_ALTER_AGENT_EXECUTION_CLAIM_INDEX.sql | 에이전트 실행 확장 | 0 | 중간 진행 상태 lease 회수용 선점 인덱스 |

판단 품질 평가를 위해 다음 추적 사슬을 유지한다.

> 상담 원문 → 모델·프롬프트·워크플로 버전 → Agent 실행 → capability 호출 → 포지션 판단 → 원문 근거 → 후보 판정 → 판정 근거 → 사용자 정정·실험 평가

## 파일 이름

~~~text
NNN_ACTION_SCOPE.sql
~~~

- NNN: 3자리 증가 번호. 한 번 사용한 번호는 재사용하지 않는다.
- ACTION: CREATE, ALTER, DATA, DROP 중 하나다.
- SCOPE: 대문자 영문·숫자·밑줄로 표현한 업무 범위다.
- 확장자는 소문자 .sql이다.

정규식:

~~~text
^[0-9]{3}_(CREATE|ALTER|DATA|DROP)_[A-Z0-9_]+\.sql$
~~~

예:

- 008_CREATE_AUTHENTICATION.sql
- 009_ALTER_CONSULTATION_AUDIO_RETENTION.sql
- 010_DATA_MATCH_EVALUATION_BACKFILL.sql
- 011_DROP_LEDGER_LEGACY_STATUS.sql

번호 충돌은 병합 전에 아직 적용되지 않은 파일만 다음 번호로 변경해 해소한다.

## 불변성과 순서

1. 공유 환경에 적용된 파일은 수정, 삭제, 이름 변경 또는 순서 변경하지 않는다.
2. 오류 수정은 기존 파일 역편집이 아니라 다음 번호의 새 파일로 추가한다.
3. 한 파일에는 하나의 검토 가능한 목적만 둔다.
4. 각 파일의 -- depends:는 직전 필수 migration 식별자를 명시한다.
5. 새 파일은 앞 번호 객체만 참조한다.
6. 파일 적용 여부와 SHA-256은 배포 기록에서 추적한다.
7. IF NOT EXISTS로 예상하지 않은 스키마 차이를 숨기지 않는다.
8. 파일 단위 transaction은 migration 실행기가 관리하므로 SQL 안에 BEGIN과 COMMIT을 넣지 않는다.
9. transaction에서 실행할 수 없는 PostgreSQL 명령은 별도 파일로 분리하고 이유를 주석으로 남긴다.

## SQL 작성 규칙

- 테이블과 컬럼은 snake_case, PK는 id, FK는 대상_id를 사용한다.
- tenant 소유 테이블은 brokerage_id를 포함한다.
- UNIQUE (brokerage_id, id)와 복합 FK로 tenant 간 연결을 방지한다.
- 상태 전이, 승인 권한과 AI 역할 검증은 Backend가 담당한다.
- DB는 존재, 관계, 고유성과 최소 형식 무결성에 집중한다.
- AI 모듈은 DDL이나 DB 세션을 직접 사용하지 않는다.
- 상담 로그는 추가 전용이며 정정은 새 로그와 피드백 연결로 남긴다.
- 운영 SQL에 실제 이름, 연락처, 상담 원문, 토큰, 비밀번호나 실사용 음성 경로를 넣지 않는다.
- 세션과 CSRF 원문은 저장하지 않고 해시만 저장한다.
- Agent JSON과 오류에는 비식별 또는 마스킹된 값만 저장한다.
- 모든 테이블과 컬럼에는 `COMMENT ON TABLE`과 `COMMENT ON COLUMN`으로 업무 의미를 기록한다.
- 기존 객체의 설명을 보완할 때는 적용된 migration을 역편집하지 않고 다음 ALTER migration에서 comment를 추가하거나 교체한다.

## 변경 유형

- CREATE: 새 객체를 추가하며 참조 대상은 앞 번호에서 먼저 생성한다.
- ALTER: nullable 또는 안전한 기본값으로 확장하고 데이터 전환 후 별도 파일에서 제약을 강화한다.
- DATA: 스키마 전환에 필요한 결정적 보정만 수행한다.
- DROP: 읽기·쓰기 중단, 데이터 보존과 참조 제거를 확인한 마지막 단계에서만 수행한다.

## 검토와 검증

1. 이름과 번호가 규칙에 맞고 중복되지 않는가.
2. -- depends:가 실제 앞 migration을 참조하는가.
3. 빈 PostgreSQL 15 DB에 전체 파일을 순서대로 적용할 수 있는가.
4. 기존 스키마에 새 파일만 전진 적용할 수 있는가.
5. 실패 시 파일 단위 transaction이 rollback되는가.
6. FK 대상에 PK 또는 UNIQUE가 있고 타입과 tenant 키 순서가 일치하는가.
7. 인덱스가 실제 컬럼만 참조하는가.
8. 기존 데이터가 새 NULL, 중복, 길이와 상태 제약을 만족하는가.
9. API·AI 계약과 저장 구조가 함께 변경되었는가.
10. 개인정보 수집, 접근, 외부 전송, 보존과 삭제 영향을 검토했는가.
11. SHA-256과 적용 결과가 배포 또는 PR 기록에 남는가.

실제 PostgreSQL 15 적용 전에는 파서 및 정적 검토만으로 적용 가능하다고 판단하지 않는다.

## 파괴적 변경과 복구

파괴적 변경은 확장 → 데이터 보정 또는 이중 처리 → 애플리케이션 전환 → 제거 순서로 나눈다. 적용 파일을 역편집해 rollback하지 않고 호환 가능한 전진 migration을 우선한다. 데이터 손실 가능성이 있으면 적용 전에 복구 가능한 백업과 절차를 확인한다.

## 아직 확정하지 않은 사항

- 개인정보별 법정·업무 보존 기간과 자동 파기 절차
- 실제 고객 데이터 사용 여부와 동의·접근 감사 범위
- 업무 상태값의 최종 목록과 상태 전이 규칙
