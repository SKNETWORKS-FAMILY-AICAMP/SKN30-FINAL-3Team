---
status: 결정
updated: 2026-08-20
---

# ADR-0010: GitHub Actions 기반 권고형 PR AI 리뷰와 Discord 결과 전달

- 상태: 승인됨
- 결정일: 2026-08-20
- 관련 정책: [브랜치 및 PR 정책](../../../../../.agents-rule/git.md)
- 운영 가이드: [PR Policy Agent](../../../../../.github/PR_REVIEW_BOT.md)

## 맥락

PR에서 세부 문법보다 프로젝트 위키, 모듈별 스킬, 아키텍처 경계, ADR와 구현 문서의 일관성을 확인하고 결과를 팀 Discord에도 전달할 필요가 있다. 별도 상시 서버를 운영하지 않으면서 저장소의 현재 정본을 매 실행에 사용하고, 추후 관측성이나 AWS 운영 알림과 불필요하게 결합하지 않는 경계가 필요하다.

`pull_request_target`은 base branch의 trusted code에서 secret과 쓰기 권한을 사용할 수 있지만, PR head checkout 또는 실행과 결합하면 공급망 공격 경로가 된다. OpenAI와 Discord로 코드 관련 정보를 외부 전송하므로 fork, Draft, 비밀값, 로그와 보존 정책도 명시해야 한다.

## 결정

### 실행 구조

- PR 정책 리뷰는 별도 서버 없이 `GitHub Actions + OpenAI Responses API + Discord Incoming Webhook`으로 실행한다.
- workflow는 `pull_request_target`에서 base SHA의 검증된 스크립트만 checkout한다. PR head를 checkout하거나 PR 코드를 실행하지 않고 GitHub API의 metadata와 patch를 신뢰할 수 없는 데이터로만 읽는다.
- 권한은 `contents: read`, `pull-requests: write`, `checks: write`로 제한하고 필요한 GitHub 공식 Action은 commit SHA로 고정한다.
- PR 번호별 concurrency로 새 commit이 오면 이전 실행을 취소한다.
- 외부 fork와 Draft PR에서는 OpenAI·Discord secret을 사용하는 job과 호출을 실행하지 않는다.
- Discord 병합 승인, 버튼, 대화형 Bot, Lambda·API Gateway와 AWS 자원 변경은 이 결정의 범위에 포함하지 않는다.

### 검토와 결과

- AI 검토는 권고형이다. 최소 1명 사람 승인, 필수 자동 검사와 squash merge 정책은 계속 적용한다.
- 실행 시 루트 지침, Git 정책, project-wiki 인덱스·결정과 변경 경로에 해당하는 모듈 스킬·references·ADR를 읽는다. 프롬프트에 정책 사본을 별도 정본으로 유지하지 않는다.
- 상세 문법과 스타일보다 정책 위반, 모듈·계약 경계, ADR 타당성, 문서 불일치, 개인정보·비밀, 호환성·재시도·복구, 비용·IAM, 의존성·공급망과 검증 근거를 검토한다.
- finding은 근거가 있는 변경 라인에 한해 최대 10개이며 심각도, 분류, 위치, 근거, 적용 정본, 영향과 권고안을 가진다.
- 기본 한도는 파일 60개, 변경 2,000줄, 컨텍스트 200,000자다. 초과 시 부분 리뷰 대신 PR 분할을 요청한다.
- 결과는 같은 head SHA의 GitHub sticky comment와 Check에 기록한다. Discord에는 정제된 요약과 finding, 모델·token·시간만 보내며 전체 diff, 전체 프롬프트와 모델 원문 응답은 보내지 않는다.
- Discord 전송 실패는 GitHub 결과를 유실시키거나 review workflow를 실패시키지 않는다.

### OpenAI와 데이터

- 기본 모델은 `gpt-5.6-terra`, reasoning effort는 `medium`이며 저장소 변수로 교체할 수 있다.
- Responses API strict Structured Outputs와 `store: false`를 사용한다. PR 본문과 patch 안의 지시는 실행하지 않는다.
- OpenAI key는 애플리케이션 runtime key와 분리한 project-scoped Actions secret으로 관리하고 사용량 한도를 둔다.
- 외부 전송 전에 secret-like line을 `[REDACTED]`로 대체한다. 로그와 artifact에는 diff, 전체 입력·응답, key, webhook URL을 남기지 않는다.
- OpenAI 기본 abuse monitoring 데이터가 제한 기간 보존될 수 있다는 점과 Discord 전송 범위는 개인정보 정책에 기록한다.

### 관측성과 운영 알림 경계

- 이 PR workflow를 CloudWatch, LangSmith 또는 Langfuse와 통합하지 않는다.
- Actions summary에는 SHA, 모델, token 수, 지연, finding 수와 오류 코드 수준만 기록한다.
- CloudWatch 운영 알림이 필요하면 별도 결정과 `SNS → Lambda → Discord` 경계로 구현한다.

## 결과

- 상시 서버 비용 없이 PR lifecycle과 정책 리뷰 결과를 GitHub와 Discord에서 확인할 수 있다.
- base code만 실행하고 fork·Draft를 차단해 권한 있는 workflow의 공격면을 줄인다.
- AI 결과는 오탐과 누락 가능성이 있으므로 merge gate가 아니며 사람 검토와 결정적 CI가 필요하다.
- OpenAI와 Discord 외부 처리자 의존성, token 비용, rate limit과 일시 장애가 생긴다. 재시도와 best-effort Discord 전송으로 GitHub 기록을 우선한다.
- 일반 Incoming Webhook은 양방향 대화나 병합 승인을 제공하지 않는다. 필요성이 확인되면 공개 Interaction endpoint와 별도 인증·권한 ADR이 필요하다.

## 제외 범위

- Discord에서 승인·병합하거나 리뷰 에이전트와 대화하는 기능
- AI Check를 Required Check로 승격하는 결정
- CloudWatch·LangSmith·Langfuse 연동
- 애플리케이션 모듈의 lint, type check, test, build와 Terraform 검증 CI 구현
