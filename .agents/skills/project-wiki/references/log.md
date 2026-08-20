---
status: 구현됨
updated: 2026-08-20
---

# 위키 변경 로그

- 2026-08-20: Identity Center 전환을 폐기하고 2026-09-23까지 기존 개인 IAM 사용자·MFA·`aws login`·`TerraformOperatorRole`을 유지하며, 승인된 `student` 사용자에게 세 dev Pipeline 최소 운영 policy를 직접 연결하기로 ADR-0012에서 확정함. INFRA-OQ-001과 delivery 적용 차단 조건을 제거함.

- 2026-08-20: 통합 main 자동 배포와 Backend·Frontend 수동 독립 배포를 세 CodePipeline V2 QUEUED로 승인하고, 충돌 상태 검사·CodeDeploy 전진 migration/rollback·Frontend index 복원·Discord 알림·Worker 비활성 계약을 ADR-0011과 delivery 구현에 반영함. dev workload와 DB migration의 실제 적용 상태를 문서에 동기화하고 delivery apply는 Identity Center 운영자 결정 뒤로 유지함.

- 2026-08-20: F3 실행 상태 조회가 DB `failure_message` 원문을 공개하지 않고 allowlist 기반 `failure_code`·고정 문구만 반환하도록 공개 경계를 좁히고, 알 수 없는 내부 실패를 `EXECUTION_FAILED`로 일반화했으며, `agent_run.requested_by`의 수집 목적·저장 위치·비노출과 OQ-007 보존 미확정을 F3 실행 계약에 명시하고 Worker 구현 범위 서술의 상충을 정정함.
- 2026-08-20: 4인 공유 개발 환경의 비용 절감을 위해 EC2 instance class를 `t3.medium`에서 `t3.small`로 축소하고 Infra ADR-0010과 Terraform·자원 인벤토리·아키텍처 현재값을 동기화함. RDS와 gp3 40 GiB는 변경하지 않음.

- 2026-08-20: ADR-0010의 PR 리뷰 한도를 전체 10,000줄로 높이고, 최대 10개 chunk를 동시성 3으로 독립 검토한 뒤 결과를 통합하는 결정적 fan-out/fan-in 방식과 incomplete 보존 규칙을 구현함.
- 2026-08-20: GitHub Actions 기반 권고형 PR AI 리뷰와 Discord 결과 전달을 ADR-0010으로 승인하고 Git 정책, 개인정보 외부 전송, CI secret·변수와 운영 런북을 반영함.
- 2026-08-19: 앵커 포지션 카드 캐시 조회와 AI 생성 요청 준비를 구현하고, `ANCHOR_READY`가 원장 조회 완료가 아니라 유효한 포지션 카드 확보를 뜻한다는 점을 명시함. cache key(`position-card:v2`)는 대상·입력 버전·상담 로그 건수·마지막 상담 시각·최대 로그 ID·모델 구성 버전의 canonical JSON SHA-256이며, 과거 시각 로그 추가와 로그 무효화도 cache miss가 된다. `negotiation_side` 값 어휘 미확정을 OQ-012로 등록함.
- 2026-08-19: agent_run에 Worker lease 컬럼을 추가하고 FOR UPDATE SKIP LOCKED 기반 원자적 작업 선점과 5분 lease·3회 상한 종료 정책을 구현했으며, 실행 상태값 11종을 대문자 스네이크로 통일하고 실행 제어·업무 처리 구분을 명시함.
- 2026-08-19: 숫자 run_id 기반 F3 실행 상태 조회 계약과 사무소·루트 실행으로 격리한 tenant-scoped GET endpoint를 구현하고, 공개 status 표기를 대문자 스네이크로 고정했으며 앵커가 정확히 하나가 아닌 실행은 응답으로 변환하지 않게 함.
- 2026-08-19: F3 실행 요청 API 계약을 제안으로 등록하고 `agent_run`에 `QUEUED` 실행을 적재하는 Backend 수직 슬라이스를 구현함.
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
- 2026-08-14: 통합 F1·F2·F3 요구사항을 출처 스냅샷과 검색 의도별 분할 정본으로 가져오고, 요구사항 라우터·추적 골격·ADR-0005를 추가함.
- 2026-08-12: 프로젝트 위키 거버넌스, 루트 모듈 경계, Git 정책, 개발환경, 계약 및 개인정보 기준의 최초 버전을 작성함.
- 2026-08-12: Terraform, SQLModel, LangGraph, ECS Fargate 및 예산 범위를 미해결 질문으로 등록함.
- 2026-08-12: 브랜치·PR 정책 정본을 `.agents-rule/git.md`로 이동하고 `AGENTS.md`와 Claude import를 갱신함.
- 2026-08-12: 백엔드의 선택적 DDD, 모듈러 모놀리스와 경계 기반 이벤트 설계를 제안으로 등록하고 기술 스택 승인 질문을 구체화함.
- 2026-08-12: 프로젝트 ADR을 공통·모듈 간 결정으로 한정하고 백엔드 내부 결정 정본을 backend 스킬 references로 이동함.
