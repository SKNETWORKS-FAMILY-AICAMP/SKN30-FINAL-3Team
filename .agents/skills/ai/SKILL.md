---
name: ai
description: "`ai/`의 Python AI 워크플로, 멀티에이전트 그래프, 프롬프트·구조화 출력, 모델·도구 어댑터, 실행 상태와 체크포인트를 개발하거나 AI–Backend 실행 경계를 변경할 때 사용한다. AI 코드의 DB·FastAPI·SQLAlchemy 의존 차단, Backend의 LangGraph·프롬프트 의존 차단, 런타임 포트 주입과 Agent 부수 효과 통제가 필요한 작업에도 사용한다. 프로젝트 공통 지식은 project-wiki와 함께 확인한다."
---

# AI 모듈 개발

이 스킬의 구조 권장안은 작업 규모와 위험에 맞게 조정하되, 아래 모듈 경계는 승인된 프로젝트 결정으로 취급한다. 저장소 지침과 project-wiki의 승인된 결정이 나머지 권장안보다 우선한다.

## 작업 전 확인

1. `.agents/skills/project-wiki/references/index.md`를 읽고 현재 작업과 직접 관련된 문서만 확인한다.
2. 모듈 경계나 공개 계약을 바꾸기 전에 project-wiki의 아키텍처 문서, 결정 인덱스와 관련 ADR을 확인한다.
3. 존재하면 `.agents/skills/ai/references/index.md`에서 관련 AI 내부 결정과 미해결 질문만 확인한다.
4. LangGraph, 모델 제공자, 체크포인트 저장소와 큐 제품은 승인된 결정인지 확인하고, 후보를 확정 기술처럼 표현하지 않는다.
5. 여러 루트 모듈을 수정하면 해당 모듈 스킬도 함께 사용한다.

## 반드시 지킬 경계

- `ai/`에서 `fastapi`와 `sqlalchemy`를 import하지 않는다.
- `ai/`는 DB 엔진, 연결 정보, 테이블, ORM 모델, 세션, 트랜잭션과 Repository를 알지 않는다.
- `backend/`에서 `langgraph`를 import하지 않고 그래프, 노드, 상태와 체크포인트 구현을 직접 다루지 않는다.
- 프롬프트 원문, 프롬프트 조합과 모델별 구조화 출력 처리는 `ai/`가 소유한다. Backend는 이를 직접 정의하거나 수정하지 않는다.
- Agent, 그래프 노드와 AI 도구 구현이 DB를 직접 조회·수정하지 않는다. 범용 SQL, ORM 세션 또는 Repository를 Agent 도구로 노출하지 않는다.
- FastAPI 요청·응답, SQLAlchemy 모델과 LangGraph 상태 같은 프레임워크 타입을 모듈 경계 밖으로 전달하지 않는다.

목표는 AI가 DB를 모르고 Backend가 LangGraph를 모르게 유지하는 것이다. 모델·프롬프트·그래프 변경은 AI 내부에, DB·트랜잭션·API 변경은 Backend 내부에 가둔다.

## 책임 분리

`ai/`가 소유한다.

- 모델 호출 어댑터와 모델 선택
- 프롬프트, 구조화 출력과 출력 검증
- 워크플로와 멀티에이전트 오케스트레이션
- 그래프 상태, 노드, 중단·재개와 체크포인트 의미
- Agent가 사용할 도구 정의, 입력·출력 스키마와 호출 정책
- 평가, 추적 가능한 실행 결과와 실험 구성

`backend/`가 소유한다.

- HTTP API, 인증·인가와 애플리케이션 서비스
- 트랜잭션, Repository, DB 스키마와 영속화
- AI 실행 요청의 조립, 실행 결과 검증과 저장
- AI가 요청한 외부 부수 효과를 수행하는 Backend Tool Adapter

일반 서버 API 전체, 범용 큐 인프라 정의, 데이터 수집 파이프라인과 비즈니스 도메인 규칙은 이 스킬의 범위에서 제외한다.

## 연동 패턴

모듈 경계에는 표준 Python 타입과 프레임워크 중립 DTO·`Protocol`만 노출한다.

1. Backend가 공개 AI 실행 인터페이스에 요청 DTO를 전달한다.
2. 애플리케이션 조립 지점에서 Backend 소유 어댑터를 AI의 capability port에 런타임 주입한다.
3. AI 내부 구현이 모델, 프롬프트와 그래프를 실행하고 결과 또는 부수 효과 요청을 반환한다.
4. Backend 어댑터가 권한, 입력과 현재 상태를 다시 검증한 뒤 애플리케이션 서비스와 트랜잭션을 통해 DB 변경을 수행한다.
5. Backend가 최종 AI 결과와 실행 메타데이터를 필요한 범위에서 저장한다.

AI 도구 정의는 Agent에게 보이는 이름, 설명과 입출력 스키마를 소유하되, DB 변경이 필요한 실제 동작은 주입된 Backend capability만 호출한다. 읽기 도구도 원시 SQL이나 범용 조회가 아니라 작업에 필요한 최소 capability로 제한한다.

영속 체크포인트가 필요하면 AI에는 저장 기술을 숨긴 checkpoint port를 두고 구현을 주입한다. LangGraph 전용 어댑터는 `ai/` 내부에, DB 드라이버와 트랜잭션은 Backend 쪽 구현에 둔다. Backend에는 LangGraph checkpointer 타입을 노출하지 않는다.

## 구현 절차

1. 변경을 AI 내부 구현, 공개 실행 계약, 주입 capability 또는 Backend 부수 효과로 분류한다.
2. 경계 변경이면 프레임워크 중립 요청·결과·오류 계약을 먼저 정의한다.
3. 모든 I/O와 부수 효과를 식별하고 모델 호출, 파일·외부 API와 capability 호출을 어댑터 뒤에 둔다.
4. 프롬프트와 모델별 파라미터를 Backend 설정이나 API 핸들러로 누출하지 않는다.
5. 재시도·재개될 수 있는 외부 호출에는 멱등 키, 중복 처리 또는 안전한 재실행 전략을 둔다.
6. AI 단위 테스트에는 fake model, fake capability와 인메모리 checkpoint port를 주입한다.
7. DB 변경이 포함되면 Backend 테스트에서 권한 검증, 트랜잭션과 결과 저장을 검증한다.

내부 폴더 구조와 그래프 패턴은 실제 코드 규모가 필요로 할 때 정한다. 공개 facade와 내부 오케스트레이션의 경계는 유지하되, 아직 필요하지 않은 공통 패키지나 추상 계층을 미리 만들지 않는다.

## 검증

- 정적 검색 또는 의존성 테스트로 `ai/`의 FastAPI·SQLAlchemy import와 `backend/`의 LangGraph import가 없음을 확인한다.
- 프롬프트와 그래프 상태가 `backend/`에 새지 않았는지 변경 파일을 검토한다.
- `ai/`에서 SQL 실행, ORM 세션, DB 연결과 Repository 사용이 없는지 확인한다.
- Agent 결과만으로 DB가 변경되지 않고 반드시 Backend 검증과 트랜잭션을 통과하는지 테스트한다.
- 공개 계약 테스트로 Backend 어댑터와 AI 실행 facade의 호환성을 검증한다.
- 모델 또는 프롬프트 구현을 fake로 교체해도 Backend 테스트가 LangGraph나 모델 SDK 없이 실행되는지 확인한다.

규모가 커지면 AST 기반 import 경계 테스트를 추가한다. 경계 예외가 필요하면 구현 전에 project-wiki의 결정을 변경하고 이유와 대안을 ADR로 남긴다.

## 지식 갱신

- AI 내부의 구조, 라이브러리, 그래프 패턴, 상태·프롬프트·평가 규칙은 `.agents/skills/ai/references/`와 해당 결정 인덱스에 기록한다.
- AI–Backend 공개 계약이나 모듈 책임을 바꾸면 project-wiki의 관련 문서와 ADR을 갱신한다.
- 임시 실험 결과와 추측은 정본에 기록하지 않는다.
