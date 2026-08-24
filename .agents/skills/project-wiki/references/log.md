---
status: 구현됨
updated: 2026-08-24
---

# 위키 변경 로그

- 2026-08-24: F3 Backend가 저장된 앵커 카드 1장과 후보 카드 1~15장으로 `brokerage-judgment:v1` 요청을 조립하고, `SYNTHETIC_PROTOTYPE` privacy mode와 별도 `BROKERAGE_JUDGMENT` 모델 바인딩을 확인한 뒤 중개 판정을 한 번 호출하도록 구현했다. 호출 전 `JUDGING`으로 전이하고 모델을 기다리는 동안 DB transaction을 열어 두지 않으며, 저장 직전에 lease·attempt·사무소·바인딩·앵커와 후보 장부 버전·후보 snapshot·카드 활성 여부·결과 근거를 재검증한다. 후보별 등급·순위·걸림돌·양보·행동·기각 사유·근거와 `COMPLETED` 전이를 한 transaction에 저장해 부분 완료를 막는다. 후보 0건은 모델 설정 조회·호출·`JUDGING` 없이 빈 결과로 완료한다. Provider 호출 중 중단된 `JUDGING` 실행은 migration 016의 선점 인덱스와 최초 바인딩 대조를 거쳐 lease 만료 후 재실행할 수 있다. 전체 프롬프트·모델 원문은 저장하지 않고 결과 HTTP 조회와 Worker handler 연결은 후속 범위로 유지했다.
- 2026-08-24: F3 중개 판정 Backend–AI 계약 `brokerage-judgment:v1`과 Provider 중립 구조화 출력 생성기를 구현했다. 앵커 카드 1장과 반대편 후보 카드 1~15장을 한 번에 보내고 `STRONG`·`WEAK`·`REJECTED` 등급, 1..N 연속 순위, 비교 근거·걸림돌·양보·행동·기각 사유를 반환한다. 기각도 제거하지 않으며 인용은 각 카드가 이미 보유한 `(interaction_id, quote_text)`만 허용한다. 생성기는 합성 입력의 명시적 opt-in을 Provider 호출 전에 확인하고 후보 집합·순위·근거 교차 검증을 통과한 결과만 반환한다. 이 항목을 기록한 시점에는 Backend 입력 조립·저장과 `JUDGING`·`COMPLETED` 전이가 후속 범위였고, 바로 위 후속 항목에서 구현했다. 운영 Provider와 외부 전송은 승인하지 않았다.
- 2026-08-24: F3 결정적 후보 snapshot의 상위 15건에 대해 앵커 반대편 포지션 카드를 순차 생성·캐시 재사용하고, 후보 자신의 `row_version`과 공용 snapshot·privacy mode·cache key·저장 fencing을 적용했다. 후보 카드 ID는 루트 실행의 `match_evaluation.candidate_selection_snapshot`에 기록하며 전건 확보 뒤에만 `CANDIDATE_CARDS_READY`로 전이한다. 후보 0건은 모델 호출 없이 전이하고 일부 실패 시 상태는 `CANDIDATES_READY`에 남는다. 해당 진행 상태의 만료 lease 회수를 위해 migration 015로 선점 인덱스를 확장했다. ADR-0014의 합성 입력 전용 경계와 Worker polling·handler 미연결, 후보 카드·결과 조회 미구현은 유지했다.
- 2026-08-24: F3 결정적 SQL 후보 추출을 구현하고 `CANDIDATES_READY`를 실제 상태로 기록했다. 후보 조회는 LLM을 쓰지 않고 앵커 카드의 추정값을 축으로 반대편 장부를 조회하며, 사무소·소프트 삭제·부모 세대 삭제·호환 거래 유형·현재 서버 기본 활성 상태·가격 밴드·희망 단지를 SQL 조건으로 적용한다. 월세는 보증금만 비교하고 월 차임은 버리지 않고 snapshot에 보존한다. 가격 근접도·평형 일치·접수 최신성은 중개 등급이 아닌 카드화 우선순위 점수로만 사용한다. 전체 후보와 조회 조건은 `match_evaluation.candidate_selection_snapshot`의 `candidate-selection:v2`에 보존하며, 상위 15건은 첫 페이지일 뿐 컷이 아니다. 가격 밴드·평형 오차·가중치는 승인된 수치가 아닌 MVP 조정값으로 snapshot에 함께 기록한다. 만료된 `CANDIDATES_READY` lease 회수용 인덱스를 확장했으며 Worker polling·handler와 후보 카드 생성 이후 단계는 후속 범위로 유지했다.
- 2026-08-24: F3 앵커 포지션 카드의 합성 F1 snapshot 조립, 측면별 상담 범위, 입력 fingerprint 기반 `position-card:v3` 캐시, 주입 생성기 호출 전후 transaction 분리, 저장 직전 lease·입력 fencing, 카드·거래 유형별 가격·근거 저장과 `ANCHOR_READY` 전이를 구현했다. 만료된 `ANCHOR_READY` lease는 진행 상태를 보존해 재선점하도록 선점 인덱스까지 확장했다. ADR-0014에 따라 `SYNTHETIC_PROTOTYPE`만 명시적으로 허용하며 실사용 F1 마스킹, Worker polling·handler, 운영 Provider 선택과 후보 이후 단계는 후속 범위로 유지했다.
- 2026-08-24: F3 프로토타입은 실제 인물과 연결되지 않는 합성 케이스에 한해 마스킹 변환을 생략하고 `SYNTHETIC_PROTOTYPE` 요청과 생성기 opt-in을 모두 요구하기로 ADR-0014에서 승인했다. 실제 F1 사용자 데이터 연결 전에는 마스킹과 `MASKED` 모드로 전환하며 외부 Provider 선택은 별도 결정으로 유지한다.
- 2026-08-24: F3 포지션 카드 생성기가 모델 결과를 반환하기 전에 요청·결과 교차 검증을 강제하도록 계약을 명확히 하고, F3 AI 정본 등록과 `negotiation_side` OQ-012 종료를 아키텍처 테스트로 고정했다.
- 2026-08-24: F3 포지션 카드의 Provider 중립 구조화 출력 생성기를 구현했다. 서버 소유 대상·source identity·장부 표기 금액은 모델 schema에서 제외하고 요청으로부터 결정적으로 조립하며, prompt·workflow 버전을 모델 호출 전에 공개한다. Backend 입력 조립·저장과 운영 Provider 선택은 후속 범위로 유지했다.
- 2026-08-24: PR Policy Agent가 `synchronize`에서 base·설정·chunk fingerprint가 같은 정제 결과만 재사용하고 project-wide 변경은 전체 무효화하도록 ADR-0010을 확장했다. 부분 리뷰는 Luna/low, 통합은 Terra/medium으로 분리하고 고정 정책 explicit prompt cache, cache read/write 계측, PR 종료 시 숨은 상태 제거를 구현했다.
- 2026-08-24: 사람의 PR 일반 댓글·리뷰 제출·인라인 코드 댓글을 봇 제외, secret-like line redaction, 240자 미리보기와 멘션 비활성화 조건으로 Discord에 전달하는 읽기 전용 알림 workflow를 추가하고 ADR-0010·개인정보 정책·운영 가이드에 반영함.
- 2026-08-24: PR Policy Agent의 실제 코드·설정·운영 가이드와 일치하도록 ADR-0010의 finding 상한을 부분 리뷰당 3건, 최종 통합 5건으로 정정함.
- 2026-08-24: 일반 개발 PR을 `dev`에 통합하고 `dev → main` 릴리스 PR로 배포 기준을 갱신하며, `Hong1008`을 기본 사람 승인 책임자로 두는 Git 흐름을 ADR-0013과 정책 정본에 승인함. 작업 PR은 squash, 릴리스 PR은 조상 관계 보존을 위해 merge commit을 사용함.
- 2026-08-20: Backend·Frontend CI를 artifact 없는 Verify와 테스트 DB 없는 Build로 분리하고, Backend 검증 DB image를 ECR Public 기반으로 만들어 전용 private ECR에 캐시해 Docker Hub pull limit에 의존하지 않도록 delivery 계약을 보완함.
- 2026-08-20: CodeBuild false-green 방지를 위해 Backend `TEST_DB_URL` 필수 통합 검사와 Frontend typecheck·현재 Vite release 검사를 공통 로컬/CodeBuild 진입점으로 고정함.
- 2026-08-20: F3 포지션 카드의 Backend–AI 계약을 `contracts/f3-ai.md`로 확정했다. `negotiation_side`를 `LISTING`·`REQUIREMENT`로 고정해 OQ-012를 종료하고, 계약 버전 `position-card:v1`을 당시 cache key 버전 `position-card:v2`와 별개 축으로 분리했으며, intent·urgency·contactability·evidence·price_kind 어휘와 화면 한국어 매핑, LISTING/REQUIREMENT 입력 격리와 근거 규칙을 정의했다. 이 항목을 기록한 당시에는 프롬프트·모델 호출·카드 저장·`ANCHOR_READY` 전환이 미구현이었고 2026-08-24 후속 항목들에서 구현했다. 운영 Provider·모델은 계속 미확정이다.
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
