---
status: 결정
updated: 2026-09-04
---

# ADR-0024: PR 리뷰 정책 pack 라우팅과 조건부 중재

- 상태: 승인됨
- 결정일: 2026-09-04
- 부분 대체: [ADR-0010](ADR-0010-pr-policy-ai-review-discord.md)의 모든 관련 정책 문서 재귀 포함과 chunk 수에만 따른 최종 정책 중재 규칙
- 관련 결정: [ADR-0016](ADR-0016-pr-review-cross-chunk-evidence.md)
- 운영 가이드: [PR Policy Agent](../../../../../.github/PR_REVIEW_BOT.md)

## 맥락

PR Policy Agent의 목적은 문법·스타일 검사가 아니라 변경에 적용되는 저장소 정책, 모듈 경계, 계약, ADR, 개인정보·비밀, IAM·비용과 복구·검증 근거를 권고형으로 확인하는 것이다. 기존 경로 router는 작은 공통 정본뿐 아니라 API 계약 전문과 변경 모듈의 모든 ADR·가이드를 각 chunk에 반복 포함했다. 그 결과 Frontend와 Infra처럼 정책이 많은 영역에서는 patch보다 정책 본문이 입력 한도를 먼저 소진했고, 여러 모듈을 통합할 때도 같은 정책 전문을 다시 보냈다.

정책 문서별 상시 에이전트를 추가하면 서로 다른 cache prefix와 출력 호출이 늘지만 필수 정책을 선택하는 문제는 해결하지 못한다. 정책 누락 여부를 재현할 수 있도록 선택은 결정적 코드가 담당하고, 모델은 선택된 정책의 의미 판단에 집중해야 한다.

## 결정

### 정책 router

- `.github/pr-review-policy.json`을 정책 pack manifest로 사용한다. 각 pack은 안정적인 ID, 적용 phase(`leaf`·`arbiter`), 경로·모듈·주제 조건, 정본 파일과 필요하면 Markdown 절 목록을 가진다.
- 모든 호출의 공통 정책은 루트 지침, Git 정책, project-wiki 사용 규칙·인덱스와 결정 인덱스로 제한한다. API·event·개인정보 계약과 프로젝트·모듈 ADR 전문은 `always`에 두지 않는다.
- router는 변경 경로에서 모듈과 정책 pack을 결정적으로 선택한다. 정책 문서 자체가 변경되면 base에 존재하는 같은 문서는 자동으로 승인 정책에 포함하고, 신규 문서는 ADR-0016의 제한된 PR head 근거로만 다룬다.
- 큰 정본은 manifest에 지정한 Markdown 절만 읽을 수 있다. 절 이름이 정본에 없거나 필요한 base 파일을 읽지 못하면 리뷰는 `incomplete`다.
- 디렉터리 전체를 암묵적으로 재귀 포함하지 않는다. 새 정책이 리뷰에 적용되어야 하면 적절한 pack 또는 공통 core에 명시한다.

### 변경 모듈 리뷰와 정책 중재

- 변경 모듈별 chunk는 기본 `gpt-5.6-luna`가 작은 공통 core, 선택된 모듈 core와 해당 정책 pack만 사용해 독립 검토한다. `frontend-1`, `infra-1` 같은 이름은 계속 결정적 chunk 식별자이며 장기 상태를 가진 에이전트가 아니다.
- Infra는 bootstrap/state, runtime/storage/network, delivery, lifecycle/cost, observability, RunPod/SLLM, IAM/secrets pack으로 나눈다. pack마다 상시 호출을 만들지 않고 변경 경로에 맞는 문서만 기존 Infra leaf에 넣는다.
- 최종 `gpt-5.6-terra` 호출은 chunk가 둘 이상이거나, 둘 이상의 모듈이 바뀌거나, 정책·계약·개인정보·비밀·IAM·delivery처럼 `requiresArbiter`인 pack이 선택된 경우에만 실행한다. 단순 단일 모듈·단일 chunk 변경은 leaf 결과로 종료한다.
- 중재 입력에는 공통 core, 교차 검토 pack, 부분 finding이 실제 `rule_source`로 인용한 leaf 정책, 변경 파일 inventory, 구조화된 부분 결과와 ADR-0016의 제한된 PR head 근거만 포함한다. 일반 구현 raw diff와 인용되지 않은 모듈 정책 전문은 다시 포함하지 않는다.
- 중재자는 중복·충돌 조정, 모듈 간 계약과 같은 PR 정책 제안 검토, ADR-0016에 따른 `high` 기각을 함께 담당한다. 별도 상시 정책 전문 에이전트나 OpenAI 네이티브 multi-agent는 추가하지 않는다.

### 비용과 관측

- Responses 요청은 비용 예측을 위해 `service_tier: default`를 명시한다.
- Actions summary와 GitHub 결과에 실제 input·output·cache read·cache write token과 설정된 표준 요금표로 계산한 예상 USD 비용을 기록한다. 실제 응답 모델의 요금 정보가 없으면 비용을 확정값으로 표시하지 않는다.
- GPT-5.6의 272,000 input token 장기 컨텍스트 기준을 넘은 호출 수를 별도로 표시한다. 문자 한도는 직렬화 결함 방지용으로 유지하고, 비용 판단은 API가 반환한 실제 token 사용량을 사용한다.
- 요금표는 외부 정본의 변경 가능성이 있으므로 날짜가 있는 설정으로 관리하고 공식 모델 문서와 함께 갱신한다. 비용 표시는 청구서가 아니라 운영 추정치다.

## 결과

- 정책 전문을 같은 leaf와 정책 중재에 반복 전송하지 않아 정책 증가가 곧바로 context 증가로 이어지는 정도가 줄어든다.
- 상시 모델 호출 수는 늘지 않는다. 의미적 교차 검토가 필요한 단일 chunk에서는 Terra 호출이 한 번 추가될 수 있지만, 단순 변경은 기존보다 적은 정책 입력으로 Luna 한 번만 사용한다.
- 서로 다른 전문 에이전트마다 cold cache write가 생기는 구조를 피하면서, 같은 정책 pack을 쓰는 분할 chunk는 기존 explicit cache를 재사용한다.
- 중앙 manifest의 경로·주제 조건이 실제 코드 경로를 따라가지 못하면 관련 정책을 누락할 수 있다. 대표 Frontend·Infra·교차 모듈 PR을 dry-run으로 회귀 검증하고 새 정책·경로가 생길 때 pack을 함께 갱신한다.

## 제외 범위

- 정책 문서별 상시 에이전트 또는 항상 실행되는 모듈별 모델 호출
- LLM·embedding 검색을 필수 정책 선택의 유일한 근거로 사용
- AI 리뷰를 Required Check나 사람 승인 대체 수단으로 변경
- 외부 청구 내역 없이 월 비용을 확정하거나 예상 비용을 회계 정본으로 사용
