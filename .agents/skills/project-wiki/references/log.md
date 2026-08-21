---
status: 구현됨
updated: 2026-08-21
---

# 위키 변경 로그

- 2026-08-21: 앵커 포지션 카드의 실행 중 변경 감지를 전면 보강했다. 앵커 `row_version` 만으로는 세대 스펙·단지명·당사자 역할·날짜 신호 변화를 볼 수 없어, AI에 보낸 요청 전체를 정규화한 SHA-256 입력 지문(`position-card-input:v1`)을 도입하고 cache key 를 `position-card:v3` 로 올려 지문과 로그 범위 지문을 함께 넣었다. snapshot의 `as_of`와 파생 날짜 신호를 UTC 기준으로 통일해 동일 순간의 시간대 표기가 달라도 실제 AI 요청과 지문이 같게 했다. 저장 단계는 범위를 현재 장부에서 다시 만들어 준비 이후 생긴 당사자 관계를 감지하고, cache hit 카드 행을 `FOR UPDATE`로 잠가 활성 확인과 `ANCHOR_READY` 전이 사이의 동시 무효화를 직렬화하며, 모델 바인딩 네 값(`model_snapshot` 포함)을 모두 대조한다. 미바인딩 판정을 `model_snapshot = '{}'::jsonb` 조건까지 포함하도록 고쳐 손상된 행을 덮지 않는다. 매물 대리 로그 범위에서 세대에만 달리고 당사자도 없는 모호한 로그를 제외했다.
- 2026-08-21: 앵커 포지션 카드 구현의 격리·개인정보 구멍을 막았다. 대리 측면별 상담 로그 범위를 `InteractionScope` 하나로 정의해 같은 세대에 달린 반대편 당사자의 로그가 매물 대리 입력에 섞이지 않게 했고, 요청자·담당자·로그 작성자와 실제로 선택된 로그 당사자의 식별값까지 마스킹 대상에 넣었으며 `handover_condition`도 같은 마스킹을 거치게 했다. 모델 출력 자유 문자열을 저장 직전에 훑어 금지 패턴이나 가렸던 식별값이 다시 나타나면 전체 저장을 거절한다. source identity 재검증을 cache hit 경로에도 적용하고, cache lookup이 대상·버전·상담 집합까지 대조하게 했다. 실행의 모델·prompt·workflow 바인딩을 lease fencing 아래 최초 1회 기록하고 재시도에서 고정하며, allowlist 필드만 model snapshot으로 저장한다. `target_label`은 Backend가 F1 구조화 값에서 만들어 모델이 바꿀 수 없게 했다. 준비 단계는 모든 예외에서 transaction을 닫는다.
- 2026-08-20: F3 앵커 포지션 카드의 생성·검증·저장 수직 슬라이스를 구현했다. AI는 `position-card-prompt:v1`·`position-card-workflow:v1`로 구조화 출력 1회를 내고 모델 출력 schema에서 대상·source·장부 표기 금액을 아예 제외했다. Backend는 F1 장부와 상담 로그 전량을 읽어 길이 보존 마스킹을 적용한 뒤 날짜 신호와 함께 요청을 조립하고, AI 호출 전후로 transaction을 분리해 모델을 기다리는 동안 DB를 쥐지 않으며, 저장 직전에 lease·앵커 버전·source identity를 다시 확인한다. 거래 유형별 금액을 잃지 않도록 migration 012로 `negotiation_position_price`를 추가했고 가격이 하나일 때만 기존 scalar 컬럼을 호환 projection으로 채운다. 근거는 마스킹 본문 기준 offset과 함께 저장하고 `ANCHOR_READY`를 실제 상태로 기록한다. Worker polling, 후보 추출, 중개 판정과 운영 Provider·모델은 여전히 미구현·미확정이다.
- 2026-08-20: F3 포지션 카드의 Backend–AI 계약을 `contracts/f3-ai.md`로 확정했다. `negotiation_side`를 `LISTING`·`REQUIREMENT`로 고정해 OQ-012를 종료하고, 계약 버전 `position-card:v1`을 cache key 버전 `position-card:v2`와 별개 축으로 분리했으며, intent·urgency·contactability·evidence·price_kind 어휘와 화면 한국어 매핑, LISTING/REQUIREMENT 입력 격리, 근거 필수 규칙, 마스킹된 상담 로그만 전달하는 개인정보 경계를 정의했다. F3-SE-03의 원문 보관 요구보다 승인된 개인정보 정책의 전체 프롬프트·응답 로그 금지를 우선한다. 프롬프트, 모델 호출, LangGraph workflow, 카드 저장과 `ANCHOR_READY` 전환은 아직 구현하지 않았고 운영 Provider·모델은 미확정이다.
- 2026-08-20: F3 매물 앵커가 F1 세대 소프트 삭제를 따르도록 매물 단건 조회 범위에 부모 세대 삭제 여부를 포함하고, `agent_run.requested_by`의 보존·삭제를 개인정보 정책 정본에서 `agent_run` 감사 이력과 같은 생명주기로 확정해 OQ-007 범위를 미확정 항목만으로 좁힘. 배포용 Worker 프로세스는 있으나 polling loop·handler는 없다는 구현 상태와 활성 실행 재사용·`SUPERSEDED`·SSE 미구현을 F3 아키텍처와 API 계약에 같은 사실로 반영함.
- 2026-08-20: 세션 발급 시 CSRF 원문을 별도 HttpOnly Cookie에 보관하고 `/auth/me`는 Cookie와 DB 해시를 검증해 같은 값을 반환만 하도록 인증 계약을 변경하여, GET의 CSRF 해시 변경과 다중 탭 토큰 무효화를 제거함.
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
