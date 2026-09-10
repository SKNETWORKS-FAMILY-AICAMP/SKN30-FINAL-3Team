---
status: 부분 대체됨
updated: 2026-09-04
---

# ADR-0010: GitHub Actions 기반 권고형 PR AI 리뷰와 Discord 결과 전달

- 상태: 부분 대체됨
- 결정일: 2026-08-20
- 후속 대체: [ADR-0016](ADR-0016-pr-review-cross-chunk-evidence.md)이 PR head 전체 파일 보조 근거, 동일 PR 정책 변경의 교차 chunk 공유와 부분 리뷰 `high` 오탐 기각 규칙을 대체하고, [ADR-0024](ADR-0024-pr-review-policy-routing-and-arbitration.md)가 정책 선택과 최종 통합 실행 조건을 대체
- 관련 정책: [브랜치 및 PR 정책](../../../../../.agents-rule/git.md)
- 운영 가이드: [PR Policy Agent](../../../../../.github/PR_REVIEW_BOT.md)

## 맥락

PR에서 세부 문법보다 프로젝트 위키, 모듈별 스킬, 아키텍처 경계, ADR와 구현 문서의 일관성을 확인하고 결과를 팀 Discord에도 전달할 필요가 있다. 별도 상시 서버를 운영하지 않으면서 저장소의 현재 정본을 매 실행에 사용하고, 추후 관측성이나 AWS 운영 알림과 불필요하게 결합하지 않는 경계가 필요하다.

`pull_request_target`은 base branch의 trusted code에서 secret과 쓰기 권한을 사용할 수 있지만, PR head checkout 또는 실행과 결합하면 공급망 공격 경로가 된다. OpenAI와 Discord로 코드 관련 정보를 외부 전송하므로 fork, Draft, 비밀값, 로그와 보존 정책도 명시해야 한다.

초기 2,000줄 총량 제한은 한 번의 모델 호출에 diff와 정책 컨텍스트를 함께 넣을 때의 품질·지연·비용·잘린 patch 위험을 제어하기 위한 보수적 기준이었다. 큰 PR도 여러 개의 작은 PR과 비슷한 검토 단위로 나눠 처리할 수 있으므로, 전체 허용량과 단일 모델 입력 한도를 분리한다.

## 결정

### 실행 구조

- PR 정책 리뷰는 별도 서버 없이 `GitHub Actions + OpenAI Responses API + Discord Incoming Webhook`으로 실행한다.
- 사람의 PR 일반 댓글, 리뷰 제출과 인라인 코드 댓글은 OpenAI를 호출하지 않는 별도 GitHub Actions workflow에서 같은 Discord Incoming Webhook으로 알린다.
- workflow는 `pull_request_target`에서 base SHA의 검증된 스크립트만 checkout한다. PR head를 checkout하거나 PR 코드를 실행하지 않고 GitHub API의 metadata·patch와 ADR-0016의 제한된 전체 파일 보조 근거를 신뢰할 수 없는 데이터로만 읽는다.
- 댓글 알림 workflow는 기본 브랜치의 검증된 스크립트만 checkout하고 이벤트 payload만 읽으며, 저장소 또는 PR에 쓰지 않는다. 봇 댓글과 일반 Issue 댓글은 제외한다.
- 권한은 `contents: read`, `pull-requests: write`, `checks: write`로 제한하고 필요한 GitHub 공식 Action은 commit SHA로 고정한다.
- 댓글 알림 workflow 권한은 checkout을 위한 `contents: read`만 사용한다.
- PR 번호별 concurrency로 새 commit이 오면 이전 실행을 취소한다.
- 외부 fork와 Draft PR에서는 OpenAI·Discord secret을 사용하는 job과 호출을 실행하지 않는다.
- 과거 리뷰 상태가 남은 내부 Draft PR이 종료될 수 있으므로 `closed` Draft에는 OpenAI·Discord secret이 없는 cleanup job만 실행해 숨은 상태를 제거한다.
- Discord 병합 승인, 버튼, 대화형 Bot, Lambda·API Gateway와 AWS 자원 변경은 이 결정의 범위에 포함하지 않는다.

### 결정적 분할 리뷰와 정책 중재

- 전체 PR 기본 한도는 reviewable 파일 200개와 변경 10,000줄이다. 이를 넘으면 불완전한 부분 리뷰를 만들지 않고 PR 분할을 요청한다.
- 한 번의 부분 리뷰는 변경 2,000줄, patch 80,000자, 전체 정책 포함 컨텍스트 200,000자 이하로 제한한다. 파일 경로의 루트 모듈을 먼저 보존하고, 큰 파일과 긴 단일 행은 patch 조각으로 나눈다. raw patch를 분할한 뒤 JSON 직렬화·태그 escape와 선택 정책을 포함한 실제 컨텍스트를 다시 측정해 초과 chunk를 재분할하고 최종 chunk 상한을 다시 검증한다.
- 최대 chunk 수는 10개, 기본 동시 실행 수는 3개다. 동시 실행 수는 변수로 조정할 수 있지만 구현상 6개로 상한을 둔다.
- chunk별 독립 Responses 호출과 fan-out 구조는 유지한다. 최종 호출 여부와 정책 입력 범위는 ADR-0024의 조건부 정책 중재 규칙을 따른다.
- OpenAI의 네이티브 Multi-agent 베타에 workflow를 결합하지 않는다. CI에서 chunk 경계, 호출 수, 실패 상태와 재현성을 직접 통제하기 위해 애플리케이션 수준의 고정 orchestration을 사용한다.
- 부분 리뷰는 chunk당 일반 finding 최대 3개를 반환하고 정책 중재는 중복과 충돌을 정리해 일반 finding 최대 5개를 반환한다. 다만 `critical`과 ADR-0016에 따라 명시적으로 기각되지 않은 `high`는 게시 상한을 넘어도 보존한다.
- 최종 정책 중재 입력에는 ADR-0024가 선택한 교차 pack과 부분 finding이 인용한 정책, PR 설명, 변경 파일 inventory, 정제된 부분 리뷰 결과와 ADR-0016의 제한된 PR head 정책·설정 근거만 포함한다. 일반 구현 원문 diff를 다시 보내지 않는다.
- 일부 chunk 실패, 정책 중재 실패, 읽지 못한 정책 또는 없거나 잘린 GitHub patch가 있으면 최종 상태는 `incomplete`다. 완료된 chunk finding은 보존하되 `clean`으로 판정하지 않는다.

### 증분 재검토

- `opened`, `reopened`, `ready_for_review`와 수동 실행은 전체 reviewable 변경을 검토한다. `synchronize`만 직전 sticky comment의 증분 상태를 사용할 수 있다.
- 증분 상태에는 raw patch와 전체 프롬프트를 저장하지 않고 base·head SHA, 리뷰 설정 hash, chunk별 patch fingerprint, 정제된 finding과 정책 중재 결과만 압축해 GitHub sticky comment의 숨은 marker로 보관한다.
- base SHA, 모델·reasoning·한도·policy router·schema·지침을 포함한 설정 hash가 같고 현재 chunk fingerprint가 직전 상태와 같을 때만 해당 chunk 결과를 재사용한다.
- `.github/`, `.agents-rule/`, project-wiki, `AGENTS.md` 같은 project-wide 변경이 PR에 있거나 base·설정이 바뀌면 모든 chunk를 다시 검토한다. 삭제·이름 변경·patch 변경은 fingerprint를 바꿔 해당 chunk를 무효화한다.
- 일부 chunk가 바뀌면 현재 전체 inventory와 재사용·신규 부분 결과를 사용해 필요한 정책 중재를 다시 실행한다. 모든 chunk와 aggregate fingerprint가 같을 때만 직전 정책 중재 결과도 재사용한다.
- 실패한 chunk와 완료되지 않은 정책 중재는 재사용 상태로 저장하지 않는다. PR `closed`에서는 숨은 증분 상태만 제거하고 사람이 읽는 최종 리뷰 내용은 보존한다.

### 검토와 결과

- AI 검토는 권고형이다. 최소 1명 사람 승인, 필수 자동 검사와 squash merge 정책은 계속 적용한다.
- 실행 시 루트 지침, Git 정책, project-wiki 인덱스·결정과 ADR-0024의 결정적 pack router가 변경 경로에 배정한 모듈 스킬·references·ADR 절을 읽는다. 프롬프트에 정책 사본을 별도 정본으로 유지하지 않는다.
- 상세 문법과 스타일보다 정책 위반, 모듈·계약 경계, ADR 타당성, 문서 불일치, 개인정보·비밀, 호환성·재시도·복구, 비용·IAM, 의존성·공급망과 검증 근거를 검토한다.
- finding은 근거가 있는 변경 라인에 한하며 심각도, 분류, 위치, 근거, 적용 정본, 영향과 권고안을 가진다.
- 결과는 같은 head SHA의 GitHub sticky comment와 Check에 기록한다. Discord에는 정제된 요약과 finding, 단일·분할 방식, 모델·token·시간만 보내며 전체 diff, 전체 프롬프트와 모델 원문 응답은 보내지 않는다.
- Discord 전송 실패는 GitHub 결과를 유실시키거나 review workflow를 실패시키지 않는다.

### OpenAI, 캐시와 데이터

- 기본 부분 모델은 `gpt-5.6-luna`, reasoning effort `low`, verbosity `low`, 출력 상한 2,500 token이다. 기본 정책 중재 모델은 `gpt-5.6-terra`, reasoning effort `medium`, verbosity `low`, 출력 상한 4,000 token이며 각각 저장소 변수로 교체할 수 있다.
- Responses API strict Structured Outputs와 `store: false`를 모든 부분·통합 호출에 사용한다. PR 본문과 patch 안의 지시는 실행하지 않는다.
- 고정 리뷰 지침과 선택된 정책 문서를 developer message의 앞쪽에 두고 GPT-5.6 explicit cache breakpoint를 표시한다. PR SHA·제목·본문, chunk 범위와 patch는 breakpoint 뒤의 user message에 둔다.
- cache key는 모델·schema·고정 정책 접두사의 hash로 만들고 TTL은 30분으로 둔다. 응답의 `cached_tokens`와 `cache_write_tokens`를 일반 input·output token과 별도로 GitHub 결과와 Actions summary에 기록한다.
- ADR-0024에 따라 표준 service tier를 명시하고 실제 token category와 날짜가 있는 모델 요금표로 예상 비용·장기 컨텍스트 호출을 함께 기록한다.
- OpenAI key는 애플리케이션 runtime key와 분리한 project-scoped Actions secret으로 관리하고 사용량 한도를 둔다.
- 외부 전송 전에 secret-like line을 `[REDACTED]`로 대체한다. 로그와 artifact에는 diff, 전체 입력·응답, key, webhook URL을 남기지 않는다.
- OpenAI 기본 abuse monitoring 데이터가 제한 기간 보존될 수 있다는 점과 Discord 전송 범위는 개인정보 정책에 기록한다.
- 사람 댓글 알림은 GitHub 사용자명, PR 번호·제목, 이벤트 유형, 댓글 앞 240자, 인라인 파일·줄 위치와 원문 링크만 Discord로 전송한다. secret-like line은 미리 가리고 Discord 멘션은 비활성화한다.

### 관측성과 운영 알림 경계

- 이 PR workflow를 CloudWatch, LangSmith 또는 Langfuse와 통합하지 않는다.
- Actions summary에는 SHA, 모델, 합산 token 수, 지연, chunk 수, finding 수와 오류 코드 수준만 기록한다.
- CloudWatch 운영 알림이 필요하면 별도 결정과 `SNS → Lambda → Discord` 경계로 구현한다.

## 결과

- 상시 서버 비용 없이 단순 PR은 한 번, 큰 PR이나 교차 정책 검토가 필요한 PR은 독립 검토와 조건부 정책 중재로 GitHub와 Discord에서 확인할 수 있다.
- base code만 실행하고 fork·Draft를 차단해 권한 있는 workflow의 공격면을 줄인다.
- 최초 10,000줄 PR은 최대 10개의 부분 호출과 필요할 때 한 번의 정책 중재 호출을 사용한다. 후속 commit은 호환되는 변경 없는 chunk를 재사용하고 반복 정책 접두사는 prompt cache를 사용해 input 비용을 줄인다.
- 증분 fingerprint는 의미적 의존 그래프가 아니므로 project-wide 변경과 base·설정 변경은 보수적으로 전체 무효화한다. `ready_for_review`와 수동 실행의 전체 검토가 증분 누락 위험을 보완한다.
- GitHub가 대형·바이너리 diff의 patch를 제공하지 않거나 잘라 반환하면 전체 검토를 보장할 수 없으므로 `incomplete`로 표시한다.
- AI 결과는 오탐과 누락 가능성이 있으므로 merge gate가 아니며 사람 검토와 결정적 CI가 필요하다.
- 일반 Incoming Webhook은 양방향 대화나 병합 승인을 제공하지 않는다. 필요성이 확인되면 공개 Interaction endpoint와 별도 인증·권한 ADR이 필요하다.

## 제외 범위

- Discord에서 승인·병합하거나 리뷰 에이전트와 대화하는 기능
- AI Check를 Required Check로 승격하는 결정
- CloudWatch·LangSmith·Langfuse 연동
- 애플리케이션 모듈의 lint, type check, test, build와 Terraform 검증 CI 구현
