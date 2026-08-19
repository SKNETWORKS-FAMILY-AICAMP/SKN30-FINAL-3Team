---
status: 구현됨
updated: 2026-08-20
---

# 위키 변경 로그

- 2026-08-20: GitHub Actions 기반 권고형 PR AI 리뷰와 Discord 결과 전달을 ADR-0010으로 승인하고 Git 정책, 개인정보 외부 전송, CI secret·변수와 운영 런북을 반영함.

- 2026-08-18: 개발 환경 RDS·S3·설정 기준을 Infra ADR-0003으로, AL2023 t3.medium·gp3 40 GiB·ASG 1대·14일 로그와 5개 alarm 기준을 Infra ADR-0004로, private S3·CloudFront·`/api/*` routing을 Infra ADR-0005로 확정하고 Terraform에 구현했으며 원격 plan 96 add·0 change·0 destroy를 확인함.

- 2026-08-18: AWS 비용 상한을 2026-09-23까지 누적 300,000원의 참고값으로 정정하고 Billing 자원 미사용, Identity Center 사용 가능, CloudFront `/api/*` 동일 origin, 개인정보 제한, release artifact 종료와 최초 DB migration의 pgvector 활성화를 ADR-0009로 확정함.
- 2026-08-18: 개발·시연 1차 런타임을 EC2 Backend·설치형 brokerage-ai·RunPod Pod로, 애플리케이션 전달을 자동 감지 없는 수동 CodePipeline V2·CodeBuild·CodeDeploy로 확정하고 AWS·RunPod 아키텍처, ADR, 자원 상태와 미해결 질문을 갱신함.
- 2026-08-18: F1 MVP 범위에서 후보 추출용 조건 필터를 포함으로, 통합검색을 제외로 구분했다. 2026-08-17 원문 스냅샷은 검색과 필터를 함께 제외했으나 F3 결정적 후보 추출이 조건 조회를 요구해 조정함.
- 2026-08-18: 인물 개인정보 활용 동의 기록을 migration 010으로 추가하고 F1 매물장·구입장·상담 로그의 HTTP 계약 초안을 API 계약 문서에 `제안`으로 등록했으며 세대·매물 컬럼 범위의 조회·상세·추가·수정 API를 구현함.
- 2026-08-17: 매물장 세대 스펙과 구입장 공동중개·현 거주지 만기·분류·진행단계를 migration에 추가하고 전체 26개 테이블과 모든 컬럼의 생성·변경 SQL에 DB comment를 부여함.
- 2026-08-17: Terraform을 AWS 인프라 변경의 IaC 정본으로 승인하고 OQ-001을 종료했으며, Identity Center 전환 시점을 OQ-011로 등록함.
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
