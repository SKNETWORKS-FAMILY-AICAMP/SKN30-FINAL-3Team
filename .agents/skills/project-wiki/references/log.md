---
status: 구현됨
updated: 2026-08-17
---

# 위키 변경 로그

- 2026-08-17: AI의 Python 3.13·uv 독립 패키지와 Provider/config/runtime 경계를 AI ADR-0001로, F3 LangGraph 채택 범위를 AI ADR-0002로 확정하고 OQ-003을 종료함.
- 2026-08-17: 공개 `.env.local`·`.env.prod`에는 비밀값을 두지 않고 Infra가 로컬·CI·운영 프로세스 환경변수로 비밀값을 주입하는 책임 경계를 확정함.
- 2026-08-17: Backend의 Python 3.13·uv·FastAPI·SQLModel·Yoyo와 서버 세션 인증 기반을 백엔드 ADR-0002로 확정하고 26테이블 SQL 기준선에 인증 세션을 추가함.
- 2026-08-17: 기존 58테이블 DDL을 검토용 archive로 보존하고 F1 최소 원장과 F2/F3 근거·평가 추적을 유지한 25테이블 PostgreSQL 15 SQL 기준선을 `docs/db/`에 추가함.
- 2026-08-17: AI가 DB·FastAPI·SQLAlchemy를 모르고 Backend가 LangGraph·프롬프트를 모르게 하는 모듈 경계와 Backend Tool Adapter 원칙을 ADR-0006으로 확정함.
- 2026-08-17: F1 최소화와 F2/F3 AI 시연·평가 우선 원칙을 현재 MVP 범위 정본과 프로젝트 목표에 반영함.
- 2026-08-12: 프로젝트 위키 거버넌스, 루트 모듈 경계, Git 정책, 개발환경, 계약 및 개인정보 기준의 최초 버전을 작성함.
- 2026-08-12: Terraform, SQLModel, LangGraph, ECS Fargate 및 예산 범위를 미해결 질문으로 등록함.
- 2026-08-12: 브랜치·PR 정책 정본을 `.agents-rule/git.md`로 이동하고 `AGENTS.md`와 Claude import를 갱신함.
- 2026-08-12: 백엔드의 선택적 DDD, 모듈러 모놀리스와 경계 기반 이벤트 설계를 제안으로 등록하고 기술 스택 승인 질문을 구체화함.
- 2026-08-12: 프로젝트 ADR을 공통·모듈 간 결정으로 한정하고 백엔드 내부 결정 정본을 backend 스킬 references로 이동함.
- 2026-08-14: 통합 F1·F2·F3 요구사항을 출처 스냅샷과 검색 의도별 분할 정본으로 가져오고, 요구사항 라우터·추적 골격·ADR-0005를 추가함.
