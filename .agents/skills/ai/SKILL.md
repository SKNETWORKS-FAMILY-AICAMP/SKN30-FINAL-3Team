---
name: ai
description: "`ai/`의 Python 멀티에이전트 그래프, 실행 상태, 체크포인트, OpenAI API·RunPod·도구 연동을 개발하거나 에이전트 실행 경계를 변경할 때 사용한다. 프로젝트 공통 지식은 project-wiki와 함께 확인한다."
---

# 에이전트 스킬 초안

이 스킬의 구조와 개발 방식은 절대 규칙이 아니라 기본 권장안이다. 작업 규모와 위험에 맞는 가장 단순한 설계를 우선하고, 권장안에서 벗어난 이유와 검증 방법을 PR에 남긴다. 장기 유지할 모듈 내부 결정은 `.agents/skills/ai/references/decisions/`에, 프로젝트 공통 결정·계약·정책은 project-wiki에 기록한다. 저장소 지침과 승인된 프로젝트·모듈 결정은 이 권장안보다 우선한다.

- 작업 위치: `ai/`
- 주 언어 방향: Python
- 오케스트레이션 후보: LangGraph
- 외부 연동 방향: OpenAI API, RunPod
- 책임 후보: 에이전트 그래프, 실행 상태, 체크포인트, 모델·도구 호출, 중단·재개
- SQS는 외부 작업 전달·재시도, LangGraph는 에이전트 실행 내부 상태를 담당하는 경계 검토
- 운영 체크포인트 후보: PostgreSQL 기반 LangGraph checkpointer
- 외부 API 호출과 파일 저장 등 부수 효과는 재실행을 고려해 멱등하게 설계
- 제외: 일반 서버 API 전체, 범용 큐 인프라 정의, 데이터 수집 파이프라인
- 에이전트 실행환경과 의존성은 모듈 내부에서 독립 관리
- 내부 폴더 구조, 그래프 패턴, 상태 스키마, 프롬프트 관리, 평가·테스트 규칙은 보류
- 작업 전 project-wiki와 존재하는 경우 `.agents/skills/ai/references/index.md`에서 관련 결정만 확인
