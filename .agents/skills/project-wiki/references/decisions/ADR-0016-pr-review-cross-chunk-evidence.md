---
status: 결정
updated: 2026-08-24
---

# ADR-0016: PR 리뷰의 전체 파일·교차 chunk 근거와 오탐 기각

- 상태: 승인됨
- 결정일: 2026-08-24
- 부분 대체: [ADR-0010](ADR-0010-pr-policy-ai-review-discord.md)의 PR head 입력, 최종 통합 근거와 부분 리뷰 `high` 보존 규칙
- 운영 가이드: [PR Policy Agent](../../../../../.github/PR_REVIEW_BOT.md)

## 맥락

GitHub Pull Request Files API의 `patch`는 변경된 hunk를 모두 포함해도 파일의 비변경 줄은 생략한다. 따라서 `.gitignore`의 뒤쪽 hunk만 본 부분 리뷰가 앞쪽의 기존 `.env` 규칙을 보지 못하고 “규칙이 없다”고 단정할 수 있다.

결정적 분할 리뷰에서는 구현 파일과 같은 PR에서 바뀐 ADR이 서로 다른 chunk에 들어간다. 각 부분 리뷰가 base SHA의 승인 정책과 자기 chunk patch만 보면 동일 PR이 명시적으로 제안한 대체 관계를 알 수 없다. 또한 ADR에 과거 조항이 남아 있거나 부분 대체 상태가 섞이면 오래된 문구를 최신 의무처럼 적용할 수 있다. 기존 최종 통합은 모든 부분 리뷰 `critical`·`high` finding을 무조건 복원했기 때문에 통합 단계가 전체 근거로 오탐을 확인해도 제거할 수 없었다.

이 문제를 해결하면서도 `pull_request_target`에서 PR head 코드를 실행하지 않는 공급망 경계를 유지해야 한다.

## 결정

### 신뢰 경계와 전체 파일 근거

- workflow는 계속 base SHA의 검증된 코드만 checkout하고 실행한다. PR head를 checkout, import, shell 실행 또는 빌드하지 않는다.
- workflow가 checkout한 SHA를 runner에 전달하고 현재 PR base SHA와 일치할 때만 검토한다. Files API 수집 직후와 결과 게시 직전에 PR head·base·open/Draft 상태를 다시 확인하며 달라진 stale 실행은 게시하지 않는다.
- 내부 non-Draft PR에 한해 GitHub Contents API를 저장소, `pr.head.sha`와 경로로 직접 호출한다. PR 응답의 임의 `raw_url`·`contents_url`을 따라가지 않는다.
- 전체 파일 근거는 변경된 `.gitignore`, `.gitattributes`, `AGENTS.md`, `CLAUDE.md`, `.github/pr-review-policy.json`, `.agents-rule/**/*.md`, `.agents/skills/*/SKILL.md`, `.agents/skills/*/references/**/*.md`로 제한한다. 허용 경로 안에서도 `.env*`, `*.tfvars*`, private-key·certificate 확장자는 제외하며 script·asset·일반 구현 파일은 대상이 아니다.
- Contents 응답 SHA가 Pull Request Files API의 blob SHA와 같고 디코딩한 byte로 다시 계산한 Git blob SHA도 일치하는지 확인한다. 이로써 regular file처럼 target 내용을 반환하는 symlink 응답을 제외한다. UTF-8 텍스트만 허용하며 NUL/binary, 삭제 파일, SHA 누락, 지원하지 않는 인코딩도 제외한다.
- 기본 한도는 파일당 20,000자·80,000바이트, PR당 20개·60,000자다. 결정 ADR과 루트 설정을 먼저 읽도록 정렬하고 한도를 넘는 파일은 보조 근거에서 제외한다.
- 전체 파일도 patch와 같은 secret-like line redaction을 적용하고 private-key block은 BEGIN부터 END까지 가린다. 비변경 전체 파일에서만 감지한 행은 외부 전송 방어와 집계에 쓰되 “변경에서 비밀 발견” finding 근거로 사용하지 않는다. 원문은 log, artifact, sticky state에 저장하지 않는다.
- 전체 파일 내용은 developer message의 승인 정책이 아니라 user message의 `untrusted_pr_head_evidence`로만 전달한다. JSON 문자열로 직렬화하고 `<`·`>`를 escape해 PR 텍스트가 정책 태그 경계를 가장하지 못하게 한다.

### 정책 제안과 부재 판단

- base SHA에서 읽은 문서만 `accepted_policy`다. PR head의 ADR·정책 파일은 아직 병합되지 않은 제안이지만, 변경 자체와 병합 후 일관성을 검토하는 근거다.
- 같은 PR의 승인 상태 문서가 대체 대상·부분 대체 범위를 명시하고 결정 인덱스·영향 문서·구현이 일관되면 옛 base 조항만으로 구현을 `high` 위반 처리하지 않는다. 제안·미확정 상태이거나 대체 관계가 불명확하면 기존 정책을 자동 무효화하지 않는다.
- accepted policy끼리 충돌하면 명시적 상태, 대체 관계와 범위를 우선한다. 우선순위를 해결할 근거가 없으면 임의의 한 문서를 선택해 확정적인 `high` finding을 만들지 않는다.
- patch는 changed hunk 근거다. 특정 규칙이나 항목이 파일 전체에 없다는 finding은 같은 경로의 완전한 PR head 파일 근거가 있을 때만 허용한다. 보조 전체 파일을 읽지 못한 사실만으로 리뷰 전체를 `incomplete`로 만들지 않고 부재 추론을 금지한다. GitHub patch 자체가 없거나 잘린 기존 incomplete 규칙은 유지한다.
- base 정책·patch가 컨텍스트 한도 안에 있지만 보조 전체 파일을 더하면 초과하는 경우에는 낮은 우선순위의 보조 파일부터 제외하고 unavailable로 표시한다. 보조 근거만으로 전체 리뷰를 incomplete로 만들지 않는다.
- 허용된 PR head 근거를 모든 부분 리뷰와 최종 통합에 공유한다. 근거 파일의 SHA·가용 상태 hash와 PR 제목·본문 hash를 모든 chunk fingerprint에 포함하고 `.agents/skills/`, `.gitignore`, `.gitattributes` 변경은 전체 증분 리뷰를 무효화한다.

### 최종 통합과 finding

- 최종 통합에는 일반 구현 raw diff를 다시 넣지 않는다. 변경 파일 inventory, 정제된 부분 결과와 제한된 `untrusted_pr_head_evidence`만 제공한다.
- 부분 리뷰의 `critical`은 항상 보존한다. 명시적으로 기각되지 않은 `high`와 함께 일반 최종 finding 상한 5개를 넘어도 누락하지 않는다.
- 부분 리뷰의 `high`는 최종 findings에 유지하는 것이 기본이다. 전체 파일, 동일 PR 정책 변경 또는 다른 chunk 근거로 오탐·중복을 입증한 경우에만 strict schema의 `dismissed_findings`에 정확한 `root_cause`, 사유와 근거를 기록해 제외한다. 단순 누락으로 제거할 수 없다.
- 최종 통합 호출이 실패하거나 컨텍스트 한도를 넘으면 기존 fallback이 부분 리뷰 finding을 보존하고 상태를 `incomplete`로 둔다.
- 중복 제거는 `root_cause`뿐 아니라 Unicode NFKC로 정규화한 파일·제목과 파일·라인·규칙 위치를 함께 사용한다. 최종 통합은 표현 언어가 달라도 의미가 같은 finding을 하나로 합친다. sticky comment에는 보존 finding 전체 표, 최대 5개 상세와 bounded `dismissed_findings` 감사 요약을 남긴다.

## 결과

- partial hunk에 보이지 않는 기존 설정을 “없음”으로 단정하는 오탐을 줄일 수 있다.
- 구현 chunk가 같은 PR의 명시적 ADR 대체를 보면서 정책 변경 자체와 병합 후 상태를 함께 검토할 수 있다.
- 유효한 `critical`과 통합 실패 시 부분 결과는 보존하면서, 성공한 최종 교차 검증은 근거를 남기고 `high` 오탐을 제거할 수 있다.
- 제한된 전체 파일 텍스트가 OpenAI 입력에 추가되므로 외부 전송량과 token 사용량이 늘어난다. 허용 경로·문자 한도·redaction과 `store: false` 경계를 유지한다.

## 제외 범위

- PR head checkout 또는 PR 코드 실행
- 개인 `.env`, 비밀 파일이나 일반 구현 파일의 전체 내용 전송
- AI 리뷰를 Required Check 또는 사람 승인 대체 수단으로 승격
- 자연어 finding을 완전히 결정적으로 판정하는 정적 분석기 구현
