---
status: 결정
updated: 2026-09-09
---

# 프로젝트 위키 인덱스

현재 작업의 조건에 해당하는 문서만 읽는다. 계약은 공통 규칙과 해당 기능만 선택하고, 기능별 설계·검증 기록은 아래 진입점에서 필요한 문서로 이동한다.

| 문서 | 읽는 조건 |
|---|---|
| [개발자 인프라 운영](../../../../infra/operations/README.md) | 설정·공유 dev 상태·배포 준비·기동 검증 명령을 찾을 때 |
| [F3 조건부 자동 판정 구현](../../../../docs/architecture/f3/implementation-and-validation.md) | F3 신규 조회·자동 처리·Worker 복구·로컬 통합 검증과 한계를 확인할 때 |
| [F3 실행·카드·자동 판정 검토](../../../../docs/architecture/f3/position-card-review.md) | F3 현재 구현·Worker 확장성·조건부 자동 판정·결과 목록의 검토안을 확인할 때 |
| [프로젝트 개요](project-overview.md) | 목표·범위·제약을 확인할 때 |
| [요구사항 인덱스](../../../../docs/requirements/index.md) | 기능 범위·사용자 동작·수용 기준·요구사항 ID를 확인할 때 |
| [모듈 경계](architecture/overview.md) | 모듈 책임이나 의존 관계를 변경할 때 |
| [런타임 구조](architecture/runtime.md) | 프레임워크·런타임·배포 선택을 검토할 때 |
| [환경변수 작성·정리](../../../../docs/development/environment-variables.md) | .env·.env.local·.env.example 역할, 기능별 설정과 변수 변경 절차를 확인할 때 |
| [개발환경](development/environments.md) | 로컬·CI·공유 dev·prod 환경이나 의존성을 변경할 때 |
| [테스트 개선 검증 범위](../../../../docs/validation/test-reliability-2026-09-09.md) | 2026-09-09 로컬 결함 회귀, 테스트 실행·분리 변경과 검증 한계를 확인할 때 |
| [HTTP 계약 라우터](contracts/api.md) | HTTP 계약을 구현·해석·변경할 때. 공통 규칙과 해당 기능 계약을 선택 |
| [F3 AI 계약 라우터](contracts/f3-ai.md) | 포지션 카드·중개 판정의 Backend–AI 계약을 확인할 때. 공통 경계와 해당 작업 계약을 선택 |
| [챗봇 AI–Backend 계약](contracts/chatbot-ai.md) | 챗봇 DTO·facade·조회 capability·오류 경계를 변경할 때 |
| [챗봇 HTTP·SSE 계약](../../../../docs/architecture/chatbot/api-and-stream.md) | 챗봇 요청·진행 이벤트·취소·복구를 변경할 때 |
| [이벤트 계약](contracts/events.md) | 큐 메시지·이벤트 계약을 만들거나 바꿀 때 |
| [오류 관측 계약](contracts/observability.md) | 오류 로그·metric·alarm·모듈별 복구 경계를 변경할 때 |
| [개인정보 정책](privacy/policy.md) | 개인정보를 수집·저장·전송·기록할 가능성이 있을 때 |
| [DB SQL 관리](../../../../docs/db/README.md) | DB 기준선·마이그레이션 SQL·검증을 다룰 때 |
| [화면 인덱스](../../../../docs/screen/index.md) | 화면 구조·상태·소유권·이동을 변경할 때 |
| [챗봇 설계 진입점](../../../../docs/architecture/chatbot/overview.md#문서-정리-위치) | 챗봇 저장·실행·화면·시세 설계 또는 구현·검증 근거가 필요할 때 |
| [인프라 참조 인덱스](../../infra/references/index.md) | AWS·RunPod 아키텍처·배포·운영·모델 비교와 검증 기록을 찾을 때 |
| [장애 대응](../../../../docs/operations/cloudwatch-alarm-response.md) | CloudWatch Alarm을 받고 Backend·AI·인프라 오류를 조사할 때 |
| [결정 인덱스](decisions/index.md) | 아키텍처·정책 변경 전에 관련 승인 결정과 대체 관계를 확인할 때 |
| [미해결 질문](open-questions.md) | 미확정 사항에 의존하거나 새 질문이 생겼을 때 |
| [위키 운영 규칙](governance.md) | 영구 지식을 정본에 추가·수정할 때 |
| [브랜치 및 PR 정책](../../../../.agents-rule/git.md) | 브랜치·커밋·PR·검토·병합 작업을 할 때 |
| [변경 로그](log.md) | 과거 변경 이력 자체가 필요할 때. 일상 개발의 필수 읽기 아님 |

외부·사람용 원문은 출처 대조가 필요할 때만 `../sources/manifest.yaml`에서 찾는다.
