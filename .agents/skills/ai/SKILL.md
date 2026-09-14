---
name: ai
description: "`ai/`의 모델·프롬프트·구조화 출력, 그래프·실행 상태·체크포인트, 도구·평가와 AI–Backend 실행 경계를 개발하거나 변경할 때 사용한다."
---

# AI 모듈 개발

`ai/`는 모델 호출·선택, 프롬프트·구조화 출력·검증, 워크플로·그래프·상태·도구 정의, 평가·실험을 소유한다. 아래 경계는 승인된 결정이며 일반적인 구조 권장안과 구분한다.

## 필요한 문서 선택

공통 탐색·결정 확인·지식 갱신은 루트 `AGENTS.md`와 project-wiki를 따른다. [참조 인덱스](references/index.md)에서 해당 작업의 문서만 읽는다.

| 변경 | 읽을 정본 |
|---|---|
| 공개 facade·capability·부수 효과·모듈 경계 | [AI–Backend 경계 ADR](../project-wiki/references/decisions/ADR-0006-ai-backend-boundary.md)와 project-wiki의 해당 기능 실행 계약 |
| 라이브러리·workflow·구조화 출력·Provider 동작 | [결정 인덱스](references/decisions/index.md)와 관련 ADR |
| 모델·route·Provider·checkpoint의 미확정 선택 | [미해결 질문](references/open-questions.md) |
| F4 챗봇·오프라인 학습 | 참조 인덱스의 해당 `chatbot.md`·`training.md` |

## 반드시 지킬 경계

- `ai/`는 `fastapi`·`sqlalchemy`를 import하지 않는다. DB 엔진·연결·테이블·ORM 모델·세션·트랜잭션·Repository를 알지 않는다.
- `backend/`는 `langgraph`를 import하거나 그래프·노드·상태·체크포인트 구현, 프롬프트 원문·조합, 모델별 구조화 출력을 직접 다루지 않는다.
- Agent·그래프 노드·AI 도구는 DB를 직접 조회·수정하지 않는다. 범용 SQL·ORM 세션·Repository를 Agent 도구로 노출하지 않는다.
- 모듈 경계에는 표준 Python 타입과 프레임워크 중립 DTO·`Protocol`만 둔다. FastAPI 요청·응답, SQLAlchemy 모델과 LangGraph 상태·checkpointer 타입을 노출하지 않는다.

## 연동과 실행

- Backend가 요청 DTO를 조립하고 공개 AI facade를 호출한다. 조립 지점에서 Backend 소유 adapter를 AI capability port에 런타임 주입한다.
- AI는 Agent 도구의 이름·설명·입출력 스키마·호출 정책을 소유한다. DB 동작은 최소 업무 capability만 호출하며, Backend adapter가 권한·입력·현재 상태를 재검증하고 애플리케이션 서비스·트랜잭션으로 수행한다. Backend가 최종 결과를 검증·저장한다.
- 영속 checkpoint는 저장 기술을 숨긴 port로 주입한다. LangGraph 전용 adapter는 AI 내부, DB 드라이버·트랜잭션은 Backend 구현에 둔다.
- 모든 I/O와 부수 효과를 식별하고 모델·파일·외부 API·capability 호출을 adapter 뒤에 둔다. 재시도·재개 가능한 외부 호출에는 멱등 키·중복 처리 또는 안전한 재실행 전략을 둔다.
- 프롬프트·모델별 파라미터를 Backend 설정·API 핸들러에 누출하지 않는다. 공개 요청·결과·오류 계약을 경계 변경에 맞춰 갱신한다.
- F3 LangGraph는 승인됐으며 F2에는 강제하지 않는다. 운영 모델·Provider·queue·checkpoint 제품까지 확정됐다고 해석하지 않는다. 필요하지 않은 내부 계층·공통 패키지를 미리 만들지 않는다.

## 검증

- 변경된 의존성을 정적 검색 또는 경계 테스트로 확인한다. AI의 FastAPI·SQLAlchemy·DB·SQL·Repository 의존, Backend의 LangGraph·프롬프트·그래프 상태 누출을 차단한다.
- AI 단위 테스트에는 fake model·capability와 인메모리 checkpoint를 주입한다. 공개 계약 테스트로 facade와 Backend adapter의 호환성을 검증한다.
- DB 부수 효과는 Agent 결과만으로 실행되지 않고 Backend 권한 검증·트랜잭션·결과 저장을 통과하는지 테스트한다. Backend 테스트가 LangGraph·모델 SDK 없이 fake AI로 실행되는지 확인한다.
- Python 변경 시 루트 `AGENTS.md`의 Ruff 명령을 실행한다. 경계 예외는 구현 전에 project-wiki 결정과 이유·대안 ADR에 반영한다.
