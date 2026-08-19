# PR Policy Agent 운영 가이드

이 기능은 별도 서버 없이 GitHub Actions에서 PR의 정책·아키텍처·문서 일관성을 권고형으로 검토하고 결과를 GitHub와 Discord에 전달한다. 사람 1명 이상의 승인과 squash merge 정책을 대체하지 않는다.

## 구성

- [workflow](workflows/pr-policy-review.yml): `pull_request_target` 이벤트, 권한, concurrency와 base SHA checkout을 정의한다.
- [review engine](scripts/pr-policy-review.mjs): GitHub API로 PR metadata와 patch를 읽고 OpenAI Responses API를 호출하며 sticky comment, Check와 Discord 알림을 갱신한다.
- [policy router](pr-review-policy.json): 파일·변경 줄·컨텍스트 한도와 변경 경로별로 읽을 스킬·위키·ADR을 선택한다.
- [pure library and fixtures](scripts/pr-review-lib.mjs): redaction, schema, retry, 메시지 포맷과 fixture 테스트를 제공한다.

PR head를 checkout하거나 실행하지 않는다. workflow는 base branch의 검증된 스크립트만 checkout하고 PR patch를 GitHub API 응답의 신뢰할 수 없는 데이터로 취급한다.

## 이벤트

| 이벤트 | 처리 |
|---|---|
| 일반 PR opened/reopened/ready_for_review | Discord 생성 또는 시작 알림 후 AI 리뷰 |
| synchronize | 이전 SHA 만료 알림 후 최신 SHA 리뷰; PR별 이전 실행 취소 |
| closed/merged | 최종 Discord 상태 알림 |
| Draft | secret을 사용하는 job과 AI·Discord 호출 모두 생략 |
| 외부 fork | secret을 사용하는 job과 AI·Discord 호출 모두 생략 |
| workflow_dispatch | 기본 dry-run; 실제 PR을 읽되 쓰기와 Discord를 비활성화 |

Discord는 Incoming Webhook 단방향 알림만 사용한다. 병합 승인 버튼, Discord 대화형 Bot, Forum thread 자동 생성은 구현하지 않는다.

## 저장소 설정

Actions secret:

- `OPENAI_REVIEW_API_KEY`: 애플리케이션 runtime 키와 분리한 project-scoped 키
- `DISCORD_PR_WEBHOOK_URL`: 전용 채널의 Incoming Webhook URL

Actions variable:

| 이름 | 기본값 |
|---|---:|
| `OPENAI_REVIEW_MODEL` | `gpt-5.6-terra` |
| `AI_REVIEW_MAX_FILES` | `60` |
| `AI_REVIEW_MAX_CHANGED_LINES` | `2000` |
| `AI_REVIEW_MAX_CONTEXT_CHARS` | `200000` |

선택적인 `OPENAI_REVIEW_REASONING_EFFORT`, `AI_REVIEW_MAX_FINDINGS`, `AI_REVIEW_MAX_OUTPUT_TOKENS`은 각각 `medium`, 최대 10, 4000을 기본값으로 사용한다. OpenAI 키에는 사용량 한도를 설정한다.

## 결과와 실패 처리

리뷰 결과는 같은 head SHA를 표시하는 PR sticky comment와 `PR Policy Agent` Check에 기록된다. Discord에는 PR·Check·Actions 링크가 있는 요약, 최대 10개의 정제된 finding, 모델·시간·token 사용량 완료 기록을 순서대로 보낸다. `allowed_mentions.parse=[]`로 멘션을 막고 메시지는 1,800자 이하로 분할한다.

AI finding은 세부 문법보다 저장소 정책, 모듈 경계, 계약, ADR, 문서, 개인정보·비밀, 마이그레이션·복구, 비용·IAM, 의존성과 검증 근거를 본다. patch를 받지 못한 파일과 읽지 못한 정책은 `missing_evidence`로 표시한다. 파일 60개, 변경 2,000줄 또는 컨텍스트 200,000자를 넘으면 부분 리뷰를 하지 않고 PR 분할을 요청한다.

- OpenAI 429·5xx와 Discord rate limit은 `Retry-After`를 반영해 최대 3회 재시도한다.
- OpenAI 실패는 incomplete sticky comment와 실패 Check를 남긴다.
- Discord 실패는 GitHub 결과를 실패시키지 않고 Actions summary의 실패 수에 기록한다.
- diff, 전체 프롬프트, 모델 원문 응답, API key와 webhook URL을 log나 artifact로 남기지 않는다.
- 입력은 `store: false`로 보내지만 OpenAI의 기본 abuse monitoring 보존 정책은 개인정보 정본에서 별도로 관리한다.

AI Check는 Required Check로 지정하지 않는다. 안정화된 결정적 CI만 보호 규칙의 Required Check 후보로 삼는다.

## 검증과 활성화

로컬 순수 테스트:

```bash
node --check .github/scripts/pr-review-lib.mjs
node --check .github/scripts/pr-policy-review.mjs
node --test .github/scripts/tests/pr-review.test.mjs
```

관리자는 Actions의 `PR Policy Review`에서 PR 번호를 입력해 `dry_run=true`, `invoke_openai=false`로 컨텍스트 선택과 한도를 먼저 확인한다. OpenAI까지 검증할 때만 `invoke_openai=true`를 사용하며 dry-run에서는 GitHub 쓰기와 Discord 전송이 계속 비활성화된다.

두 secret과 모델 변수를 설정한 뒤 전용 Discord 채널에서 팀 PR 10개를 권고형으로 운영한다. false positive, 누락, 평균 token·지연과 메시지 양을 확인한 뒤 모델·한도만 저장소 변수로 조정한다. CloudWatch 운영 알림이 필요해지면 이 workflow에 결합하지 않고 별도 SNS→Lambda→Discord 기능으로 결정한다.
