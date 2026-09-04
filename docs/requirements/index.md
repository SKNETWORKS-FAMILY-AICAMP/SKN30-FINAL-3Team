---
status: 결정
updated: 2026-09-03
---

# 요구사항 인덱스

현재 작업과 관련된 문서만 읽는다. 정확한 요구사항 ID가 있으면 먼저 다음처럼 검색한다.

```bash
rg -n --glob '*.md' --glob '!sources/**' '<요구사항-ID>' docs/requirements
```

## 공통

| 문서 | 읽는 조건 |
|---|---|
| [현재 MVP 범위·평가 중심](common/mvp-scope-and-evaluation.md) | 구현 범위, 우선순위, F1 축소 또는 F2·F3 평가 기준을 판단할 때. 기존 상세 요구사항과 충돌하면 이 문서가 우선 |
| [개요·책임 경계·원칙](common/overview-and-principles.md) | 시스템 개요, F1·F2·F3 책임, 공통 원칙을 확인할 때 |
| [연동 접점](common/integrations.md) | F1↔F2 또는 F1↔F3의 화면·데이터 연결을 바꿀 때 |
| [용어·역할·AI 구조](common/glossary-and-roles.md) | 공통 용어, 권한 역할 또는 AI 배치를 확인할 때 |
| [통합 완료 기준·미해결 사항](common/acceptance-and-open-questions.md) | 기능 간 수용 기준이나 통합 질문을 확인할 때 |
| [개정 이력](common/revision-history.md) | 요구사항 변경 배경을 확인할 때 |

## F1 장부 시스템

| 문서 | 주요 검색 의도·ID |
|---|---|
| [개요·용어](f1/overview-and-terms.md) | F1 범위, 설계 원칙, 역할 |
| [매물장 그리드](f1/grid.md) | `F1-GR`, 표시, 컬럼, 필터, 정렬, 편집 |
| [검색 및 호출](f1/search.md) | `F1-SR`, 통합검색, 상세 호출 |
| [세대 상세](f1/unit-detail.md) | `F1-UD`, 인물·연락처·관계 관리 |
| [구입장](f1/buyer-ledger.md) | 손님대장, 구입 조건, 담당자 |
| [상담 로그](f1/consultation-log.md) | `F1-LG`, append 규칙, 로그 팝업 |
| [문자 발송](f1/messaging.md) | `F1-MS`, 연락 대상, 개인·단체 발송 |
| [F2·F3 연동](f1/integrations.md) | `F1-ST`, `F1-AG`, AI 반영·조회·쓰기 경계 |
| [일정·계약·알림](f1/schedules-and-contracts.md) | `F1-SC`, `F1-CT`, `F1-AL` |
| [마스터 데이터](f1/master-data.md) | `F1-MD`, 단지·직원·코드 관리 |
| [권한·개인정보](f1/security.md) | `F1-SE`, 마스킹, 감사, 삭제 권한 |
| [데이터 항목](f1/data-fields.md) | `F1-DM`, 매물장 33개·구입장 17개 필드, 정규화 |
| [사용법·비기능](f1/guide-and-nfr.md) | `F1-HP`, `F1-NF`, 성능·동시성·가이드 |
| [제외 범위·미해결](f1/scope-and-open-questions.md) | MVP 제외, F1 질문과 해소 이력 |

## F2 STT 음성 입력

| 문서 | 주요 검색 의도·ID |
|---|---|
| [기능 정의·흐름](f2/overview-and-flow.md) | F2 범위, 적용 장부, 신규 행·음성 채우기 흐름 |
| [목록·팝업](f2/list-and-popup.md) | `F2-LIST`, `F2-POP`, 업로드 화면, 실행 조건 |
| [STT·LLM 처리](f2/processing.md) | Whisper, 전사, 로컬 LLM, 보안·실패 처리 |
| [장부별 필드](f2/fields.md) | 매물장·구입장 채우기 필드, 최소 저장 조건 |
| [검토·저장](f2/review-and-save.md) | `F2-REV`, 제안 선택, 로그 초안, 저장 실패 |
| [제외 범위·완료 기준](f2/scope-and-acceptance.md) | F2 MVP 제외와 수용 기준 |

F2의 처리·필드·완료 기준 일부는 아직 독립 요구사항 ID가 없으므로 키워드와 문서 경로로 찾는다. 새 ID는 팀 검토 없이 임의로 부여하지 않는다.

## F3 비서 에이전트

| 문서 | 주요 검색 의도·ID |
|---|---|
| [개요·공통](f3/overview-and-common.md) | `F3-CM`, 구성 요소와 공통 원칙 |
| [포지션 카드](f3/position-card.md) | `F3-PC`, 카드 규격·캐시 |
| [대리·중개 판정](f3/delegates-and-brokerage.md) | `F3-LA`, `F3-CA`, `F3-BR` |
| [후보 추출·도구](f3/candidate-selection-and-tools.md) | `F3-SQ`, `F3-TL`, 코드 필터·공유 도구 |
| [교차 판정](f3/cross-judgment.md) | `F3-CR`, 트리거·결과·사용자 행동 |
| [배치 판정](f3/batch.md) | `F3-BT`, 캠페인·대상·발송 |
| [문안 생성·F1 연동](f3/generation-and-integration.md) | `F3-GN`, `F3-IF`, 로그·일정 쓰기 |
| [신뢰·비기능·개인정보](f3/trust-nfr-privacy.md) | `F3-TR`, `F3-NF`, `F3-SE` |
| [제외·수용·미해결](f3/scope-acceptance-open.md) | F3 제외 범위, 멀티 에이전트 검증, 질문 |

## F4 업무 비서

| 문서 | 주요 검색 의도·ID |
|---|---|
| [개요·구성·공통](f4/overview-and-common.md) | `F4-CM`, 구성 서비스, F1 알림 요구사항과의 대응 |
| [Time Keeper 일정·할 일](f4/time-keeper.md) | `F4-TK`, 대상 일정, 조회 범위, 브리핑, 수용 기준 |
| [캘린더](f4/calendar.md) | `F4-CAL`, 캘린더 일정 CRUD, Time Keeper 조회 통합, 월간 그리드 |
| [제외·미착수·미해결](f4/scope-and-open-questions.md) | 뉴스·문자 초안·블로그 초안의 미착수 사유, F4 제외 범위 |

F4의 다섯 서비스 중 Time Keeper와 캘린더가 구현됐다. 나머지 셋은 설계 전이므로 상세 문서를 미리
만들지 않는다.

## 출처와 추적

| 문서 | 용도 |
|---|---|
| [관리 규칙](README.md) | 정본, 승인 상태, 검색 및 변경 절차 |
| [추적 정보](traceability.yaml) | 요구사항 ID와 구현·테스트 경로 연결 |
| [변경 이력](changelog.md) | 변경 ID, 이유와 날짜 기록 |
| [2026-08-17 MVP 범위 재정의 원문](sources/mvp-scope-redefinition-2026-08-17.md) | 현재 MVP 범위 결정의 사용자 원문과 대조할 때만 읽는 변경 금지 스냅샷 |
| [2026-08-14 통합 원문](sources/integrated-requirements-2026-08-14.md) | 출처 대조가 필요할 때만 읽는 변경 금지 스냅샷 |
