# PR Policy Agent 운영 가이드

이 기능은 별도 서버 없이 GitHub Actions에서 PR의 정책·아키텍처·문서 일관성을 권고형으로 검토하고 결과를 GitHub와 Discord에 전달한다. 사람 1명 이상의 승인과 squash merge 정책을 대체하지 않는다.

## 구성

- [workflow](workflows/pr-policy-review.yml): `pull_request_target` 이벤트, 권한, concurrency와 base SHA checkout을 정의한다.
- [comment workflow](workflows/pr-comment-discord.yml): 사람의 PR 댓글·리뷰 이벤트를 읽기 전용으로 받아 Discord에 알린다.
- [review engine](scripts/pr-policy-review.mjs): GitHub API로 PR metadata와 patch를 읽고 Responses API 부분 리뷰를 병렬 실행한 뒤 결과를 통합하며 sticky comment, Check와 Discord 알림을 갱신한다.
- [comment notifier](scripts/pr-comment-discord.mjs): 이벤트 payload를 신뢰할 수 없는 텍스트로 처리하고 비밀 의심 행 redaction·길이 제한 후 Discord로 전송한다.
- [policy router](pr-review-policy.json): 전체 PR·부분 리뷰·통합 컨텍스트 한도와 변경 경로별로 읽을 스킬·위키·ADR을 선택한다.
- [pure library and fixtures](scripts/pr-review-lib.mjs): 결정적 chunk 계획, redaction, strict schema, retry, 결과 병합, 메시지 포맷과 fixture 테스트를 제공한다.

PR head를 checkout하거나 실행하지 않는다. workflow는 base branch의 검증된 스크립트만 checkout하고 PR patch를 GitHub API 응답의 신뢰할 수 없는 데이터로 취급한다.

## 이벤트

| 이벤트 | 처리 |
|---|---|
| 일반 PR opened/reopened/ready_for_review | Discord 생성 또는 시작 알림 후 AI 리뷰 |
| synchronize | 호환되는 변경 없는 chunk 결과를 재사용하고 변경 chunk와 최종 통합만 최신화; PR별 이전 실행 취소 |
| closed/merged | 숨은 증분 상태 제거 후 최종 Discord 상태 알림 |
| PR Conversation 일반 댓글 생성 | 사람 댓글만 Discord 알림; 봇과 일반 Issue 댓글 제외 |
| PR review 제출 | 승인·변경 요청·일반 리뷰를 Discord 알림 |
| PR inline review 댓글 생성 | 파일·줄 위치와 함께 Discord 알림 |
| Draft | secret을 사용하는 job과 AI·Discord 호출 모두 생략; 종료 시 secret 없는 cleanup job으로 과거 숨은 상태만 제거 |
| 외부 fork | secret을 사용하는 job과 AI·Discord 호출 모두 생략 |
| workflow_dispatch | 기본 dry-run; 실제 PR을 읽되 쓰기와 Discord를 비활성화 |

Discord는 Incoming Webhook 단방향 알림만 사용한다. 병합 승인 버튼, Discord 대화형 Bot, Forum thread 자동 생성은 구현하지 않는다.

### 댓글 알림 범위

- `issue_comment.created`, `pull_request_review.submitted`, `pull_request_review_comment.created`를 서로 다른 GitHub 이벤트 payload 형태에 맞게 정규화한다.
- GitHub 사용자명, PR 번호·제목, 이벤트 유형, 댓글 앞 240자, 인라인 파일·줄 위치와 원문 링크만 전송한다.
- `github-actions[bot]`을 포함한 Bot 사용자는 제외해 PR Policy Agent 알림이 중복 전송되지 않게 한다.
- secret-like line은 미리 가리고 HTML comment와 제어 문자를 제거한다. 댓글 내용은 셸 명령, 환경 변수 또는 코드로 평가하지 않는다.
- Discord의 mention parsing은 비활성화한다. 알림 workflow는 `contents: read`만 사용하고 PR head를 checkout하지 않는다.
- 댓글 알림 전송은 429·5xx에 최대 3회 재시도한다. 실패한 알림 job은 Actions에서 확인하되 PR 병합이나 AI 리뷰 결과를 변경하지 않는다.

## 리뷰 방식

- reviewable 파일 200개·변경 10,000줄까지 전체 검토 대상으로 허용한다.
- 변경 경로를 프로젝트 공통과 `frontend`, `backend`, `ai`, `data`, `infra`로 묶은 뒤 chunk당 변경 2,000줄·patch 80,000자 이하로 결정적으로 분할한다. 큰 파일은 같은 파일의 patch 조각으로 나뉠 수 있다.
- chunk별 정책 포함 컨텍스트는 200,000자 이하, chunk 수는 최대 10개다.
- chunk가 하나면 Responses API를 한 번 호출한다. 둘 이상이면 기본 동시성 3으로 부분 리뷰를 실행하고, 정책·변경 파일 inventory·정제된 부분 결과를 최대 300,000자 통합 컨텍스트로 한 번 더 검토한다. 통합 호출에는 원문 diff를 다시 포함하지 않는다.
- 부분 리뷰는 최대 3개, 최종 결과는 최대 5개의 finding을 낸다. 부분 리뷰의 `critical`·`high` finding은 최종 통합 결과에 우선 보존한다.
- 같은 근본 원인은 파일·라인이 달라도 `root_cause`로 하나로 합친다. `low`는 게시하지 않고 `medium`은 개선 권고로 표시한다.
- `제안`·`미확정`·`계획됨` 문서는 현재 구현이나 승인된 의무로 간주하지 않는다.
- 읽지 못한 정책, 없거나 잘린 patch, 부분 호출 실패 또는 통합 실패처럼 실행기가 확인한 누락만 최종 상태를 `incomplete`로 표시한다. 다른 chunk에 파일이 없다는 모델 판단은 누락으로 취급하지 않는다.

### 증분 리뷰와 무효화

- sticky comment에는 raw patch 대신 base·head SHA, 리뷰 설정 hash, chunk patch fingerprint, 정제된 부분·통합 결과만 압축한 숨은 상태를 저장한다.
- `synchronize`에서 base SHA와 설정 hash가 같고 chunk fingerprint가 같은 결과만 재사용한다. 변경된 chunk가 하나라도 있으면 현재 전체 inventory를 기준으로 최종 통합은 다시 실행한다.
- `.github/`, `.agents-rule/`, project-wiki, `AGENTS.md` 등 project-wide 변경, base 변경, 모델·reasoning·한도·schema·정책 router 변경은 전체 재검토한다.
- `opened`, `reopened`, `ready_for_review`, `workflow_dispatch`는 증분 상태를 사용하지 않고 전체 검토한다. 실패한 chunk와 실패한 최종 통합은 재사용하지 않는다.
- `closed`에서는 sticky comment의 숨은 상태만 제거하고 사람이 읽는 마지막 리뷰는 남긴다. 상태가 comment 크기 한도를 넘으면 저장하지 않고 다음 실행에서 전체 검토한다.

### Prompt cache

- 고정 지침과 선택 정책을 developer message의 정확한 접두사로 두고 explicit breakpoint를 표시한다. PR SHA·본문과 patch는 breakpoint 뒤 user message에 둔다.
- GPT-5.6 요청은 모델·schema·정책 접두사 hash를 `prompt_cache_key`로 사용하고 explicit-only `30m` TTL을 설정한다. cache는 PR 종료 때 수동 삭제하지 않고 서비스 TTL을 따른다.
- GitHub comment, Discord와 Actions summary에는 총 input·output과 함께 `cache read`(`cached_tokens`), `cache write`(`cache_write_tokens`)를 표시한다.

이 방식은 OpenAI 네이티브 Multi-agent 베타가 아니라 GitHub Actions의 한 Node 프로세스가 여러 표준 Responses 호출을 고정된 fan-out/fan-in 그래프로 조율한다. 10,000줄이라는 이유만으로 더 큰 모델을 요구하지 않으며, 모델 변경은 실제 평가 결과로 결정한다.

## 저장소 설정

Actions secret:

- `OPENAI_REVIEW_API_KEY`: 애플리케이션 runtime 키와 분리한 project-scoped 키
- `DISCORD_PR_WEBHOOK_URL`: 전용 채널의 Incoming Webhook URL

주요 Actions variable:

| 이름 | 기본값 | 의미 |
|---|---:|---|
| `OPENAI_REVIEW_MODEL` | `gpt-5.6-luna` | 부분 리뷰 모델 |
| `OPENAI_REVIEW_REASONING_EFFORT` | `low` | 부분 리뷰 reasoning |
| `OPENAI_REVIEW_MERGE_MODEL` | `gpt-5.6-terra` | 최종 통합 모델 |
| `OPENAI_REVIEW_MERGE_REASONING_EFFORT` | `medium` | 최종 통합 reasoning |
| `OPENAI_REVIEW_VERBOSITY` | `low` | 부분 리뷰 응답 verbosity |
| `OPENAI_REVIEW_MERGE_VERBOSITY` | `low` | 최종 통합 응답 verbosity |
| `AI_REVIEW_MAX_FILES` | `200` | 전체 reviewable 파일 한도 |
| `AI_REVIEW_MAX_CHANGED_LINES` | `10000` | 전체 변경 줄 한도 |
| `AI_REVIEW_MAX_CONTEXT_CHARS` | `200000` | chunk별 정책·patch 컨텍스트 한도 |
| `AI_REVIEW_CHUNK_CHANGED_LINES` | `2000` | chunk별 변경 줄 목표 상한 |
| `AI_REVIEW_CHUNK_PATCH_CHARS` | `80000` | chunk별 patch 문자 상한 |
| `AI_REVIEW_MAX_CHUNKS` | `10` | 부분 리뷰 호출 수 상한 |
| `AI_REVIEW_MAX_CONCURRENCY` | `3` | 동시 부분 호출 수; 구현 상한 6 |
| `AI_REVIEW_CHUNK_MAX_FINDINGS` | `3` | 부분 리뷰 finding 상한; 구현 상한 3 |
| `AI_REVIEW_MAX_MERGE_CONTEXT_CHARS` | `300000` | 최종 통합 컨텍스트 한도 |
| `AI_REVIEW_MAX_FINDINGS` | `5` | 최종 finding 상한; 구현 상한 5 |
| `AI_REVIEW_LEAF_MAX_OUTPUT_TOKENS` | `2500` | 부분·단일 Responses 호출 출력 상한 |
| `AI_REVIEW_MERGE_MAX_OUTPUT_TOKENS` | `4000` | 최종 통합 Responses 호출 출력 상한 |

OpenAI 키에는 사용량 한도를 설정한다. 동시성과 chunk 수를 올리면 API rate limit, 비용과 Discord 메시지 양이 함께 증가한다.

## 결과와 실패 처리

리뷰 결과는 같은 head SHA를 표시하는 PR sticky comment와 `PR Policy Agent` Check에 기록된다. Discord에는 PR·Check·Actions 링크가 있는 요약, 최대 5개의 정제된 finding, 단일·분할·증분 재사용 방식과 모델·시간·합산 token·cache read/write 사용량을 순서대로 보낸다. `allowed_mentions.parse=[]`로 멘션을 막고 메시지는 1,800자 이하로 분할한다.

AI finding은 세부 문법보다 저장소 정책, 모듈 경계, 계약, ADR, 문서, 개인정보·비밀, 마이그레이션·복구, 비용·IAM, 의존성과 검증 근거를 본다.

- OpenAI 429·5xx와 Discord rate limit은 `Retry-After`를 반영해 최대 3회 재시도한다.
- OpenAI 부분 또는 통합 실패는 incomplete sticky comment와 실패 Check를 남긴다.
- Discord 실패는 GitHub 결과를 실패시키지 않고 Actions summary의 실패 수에 기록한다.
- diff, 전체 프롬프트, 모델 원문 응답, API key와 webhook URL을 log나 artifact로 남기지 않는다.
- 모든 OpenAI 입력은 `store: false`로 보내지만 기본 abuse monitoring 보존 정책은 개인정보 정본에서 별도로 관리한다.

AI Check는 Required Check로 지정하지 않는다. 안정화된 결정적 CI만 보호 규칙의 Required Check 후보로 삼는다.

## 검증과 활성화

로컬 순수 테스트:

```bash
node --check .github/scripts/pr-review-lib.mjs
node --check .github/scripts/pr-policy-review.mjs
node --test .github/scripts/tests/pr-review.test.mjs
node --check .github/scripts/pr-comment-discord-lib.mjs
node --check .github/scripts/pr-comment-discord.mjs
node --test .github/scripts/tests/pr-comment-discord.test.mjs
```

관리자는 Actions의 `PR Policy Review`에서 PR 번호를 입력해 `dry_run=true`, `invoke_openai=false`로 정책 선택, redaction, chunk 계획과 컨텍스트 한도를 먼저 확인한다. OpenAI까지 검증할 때만 `invoke_openai=true`를 사용하며 dry-run에서는 GitHub 쓰기와 Discord 전송이 계속 비활성화된다.

두 secret과 필요한 모델 변수를 설정한 뒤 전용 Discord 채널에서 팀 PR 10개를 권고형으로 운영한다. false positive, 누락, 평균 token·지연, chunk 수와 메시지 양을 확인한 뒤 모델·한도만 저장소 변수로 조정한다. CloudWatch 운영 알림이 필요해지면 이 workflow에 결합하지 않고 별도 SNS→Lambda→Discord 기능으로 결정한다.
