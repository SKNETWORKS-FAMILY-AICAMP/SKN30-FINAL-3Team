---
name: backend
description: "`backend/`의 Python HTTP API, 배치·이벤트·큐, 인증·영속화, 서버 오케스트레이션과 Backend–AI 연동을 개발하거나 변경할 때 사용한다."
---

# 백엔드 개발

설계·테스트 권장안은 복잡도와 위험에 비례해 적용한다. 저장소 지침과 승인된 프로젝트·모듈 결정이 우선하며, 권장안에서 벗어나면 이유와 검증 방법을 PR에 남긴다.

## 필요한 문서 선택

공통 탐색·결정 확인·지식 갱신은 루트 `AGENTS.md`와 project-wiki를 따른다. [참조 인덱스](references/index.md)에서 해당 작업의 문서만 읽는다.

| 변경 | 읽을 정본 |
|---|---|
| 구조·의존 방향·트랜잭션·이벤트·배포 분리 | [아키텍처 권장안](references/architecture.md), [결정 인덱스](references/decisions/index.md)와 관련 ADR |
| 동작 추가·버그·계약·마이그레이션 검증 | [테스트와 품질](references/testing-and-quality.md) |
| HTTP·이벤트·AI 연동 | project-wiki의 해당 API·이벤트·AI 실행 계약과 모듈 경계 |
| DB·인증·런타임·환경 변경 | [런타임·DB·인증 ADR](references/decisions/ADR-0002-backend-runtime-database-authentication.md)과 명시된 후속 ADR. SQL 변경은 `docs/db/README.md` |
| 미확정 도구·구조에 의존 | [미해결 질문](references/open-questions.md) |

## 책임과 경계

- `backend/`는 HTTP API, 인증·인가, 애플리케이션 서비스, 배치·이벤트·큐와 DB 트랜잭션·Repository·AI 결과 저장을 소유한다. 그래프·프롬프트는 `ai/`, 데이터 수집·정제는 `data/`, IaC는 `infra/`에 둔다.
- Backend에서 LangGraph를 import하거나 그래프·노드·상태·체크포인트·프롬프트를 직접 다루지 않는다. 다른 루트 모듈 내부를 직접 import하지 않고 승인된 공개 인터페이스·계약을 사용한다.
- AI 경계에는 표준 Python 타입과 프레임워크 중립 DTO·인터페이스만 노출한다. Backend capability adapter가 권한·입력·현재 상태를 재검증하고 트랜잭션으로 부수 효과를 수행한다. AI 실행 중 DB 트랜잭션을 열어두지 않는다.
- 실행환경·의존성은 `backend/`에서 독립 관리한다. 루트 공통 Python 환경이나 `packages/`를 미리 만들지 않는다. API·배치·이벤트를 별도 배포 단위로 미리 나누지 않는다.
- 모듈러 모놀리스와 선택적 DDD·port/adapter를 기본 권장안으로 삼되 단순 기능에 계층·중복 모델·인터페이스를 강제하지 않는다.
- PostgreSQL·SQLModel·Yoyo는 승인된 기준이다. 도구 상태는 ADR과 설치 코드로 확인하고 Alembic·SQS 등 미채택 후보를 표준으로 가정하지 않는다. AWS SDK를 IaC에 사용하지 않는다.

## 완료 조건

- 변경 위험에 맞는 자동 검증을 실행한다. 버그는 가능하면 재현 테스트로 고정하고, 계약·개인정보·동시성·재처리·마이그레이션 경계는 자동 검증한다.
- API·이벤트 변경은 계약 테스트와 정본을 함께 갱신한다. AI 연동은 facade·capability 호환성과 Backend 검증·트랜잭션을 확인한다.
- DB 변경은 기존 데이터 호환성과 전진 마이그레이션을 검증한다. 파괴적 변경은 복구 또는 단계적 전환 방안을 제시한다.
- 개인정보가 DB·로그·이벤트·큐·오류·외부 서비스에 노출되는 경로를 점검한다.
- Python 변경 시 루트 `AGENTS.md`의 Ruff 명령을 실행한다. 타입 검사·테스트는 승인·구현된 명령을 사용하고 검증 공백을 보고한다.
