---
status: 제안
updated: 2026-08-17
---

# 아키텍처 문서 안내

## 문서 안내

- **이 문서가 답하는 질문:** 기능별 아키텍처 문서를 어디에서 찾고, 어떤 상태로 해석해야 하는가?
- **관련 요구사항:** [요구사항 인덱스](../requirements/index.md)
- **관련 승인 ADR:** [ADR-0006: AI–Backend 실행 경계](../../.agents/skills/project-wiki/references/decisions/ADR-0006-ai-backend-boundary.md)
- **이 문서가 소유하지 않는 상세:** 기능 요구사항, 승인된 프로젝트 공통 결정의 원문, 모듈 내부 폴더·클래스 구조
- **탐색:** [F2 개요](f2/overview.md) · [F2 온라인 실행](f2/online-runtime.md) · [F2 오프라인 데이터·학습·평가](f2/offline-data-training-evaluation.md) · [F3 개요](f3/overview.md) · [F3 온라인 실행](f3/online-runtime.md) · [F3 오프라인 데이터·평가](f3/offline-data-evaluation.md)

## 목적과 적용 범위

`docs/architecture/`는 확정 요구사항을 구현 가능한 큰 흐름과 모듈 책임으로 번역하는 팀 검토용 문서 공간이다. 기능의 온라인 실행, 오프라인 준비 과정, 모듈 사이의 상호작용과 실패 복구 방식을 설명한다.

이 문서는 승인된 결정의 정본이 아니다. 팀 승인 전에는 설계 대화의 기준으로만 사용하며, 승인된 프로젝트 공통 결정은 project-wiki의 ADR에 기록한다.

## 문서 체계와 정본

| 위치 | 답하는 질문 | 정본으로 다루는 내용 |
|---|---|---|
| [`docs/requirements/`](../requirements/index.md) | 무엇을 만들어야 하는가? | 기능 범위와 사용자 요구사항 |
| `docs/architecture/` | 요구사항을 어떤 큰 구조로 구현할 것인가? | 팀 검토 중인 구조와 흐름의 설명 |
| [project-wiki](../../.agents/skills/project-wiki/references/index.md) | 어떤 프로젝트 공통 결정이 승인되었는가? | ADR, 공통 계약·정책, 프로젝트 미해결 질문 |
| 모듈별 skill references | 각 모듈 내부를 어떻게 구현하는가? | 모듈 내부 원칙, 결정, 미해결 질문 |

모듈별 구현 지침은 [Frontend](../../.agents/skills/frontend/references/index.md), [Backend](../../.agents/skills/backend/references/index.md), [AI](../../.agents/skills/ai/SKILL.md), [Data](../../.agents/skills/data/references/index.md), [Infra](../../.agents/skills/infra/SKILL.md)에서 확인한다.

## 문서 상태

| 상태 | 의미 | 사용 규칙 |
|---|---|---|
| 결정 | 기존 승인 ADR에 근거한 내용 | 해당 ADR을 직접 연결한다. |
| 제안 | 팀 검토를 위해 선택한 방향 | 승인된 사실로 인용하지 않는다. |
| 미확정 | 선택이 필요하거나 외부 조건 확인이 필요한 내용 | project-wiki 또는 모듈 `open-questions.md`에 연결한다. |
| 구현됨 | 실제 코드로 존재하고 검증 가능한 내용 | 코드 경로가 생긴 뒤에만 사용한다. |

각 파일의 머리말 `status`는 문서 전체의 승인 수준이다. 문서 안에서 승인 수준이 다른 항목은 상태 표로 다시 구분한다.

## 기능별 문서

| 문서 | 언제 읽는가? | 다루는 범위 |
|---|---|---|
| [F2 개요](f2/overview.md) | F2 전체 흐름과 팀별 책임을 처음 파악할 때 | 범위, 시스템 구성, 온라인·오프라인 관계, 파일럿 가정 |
| [F2 온라인 실행](f2/online-runtime.md) | 업로드부터 사용자 승인 저장까지 구현 흐름을 논의할 때 | 작업 상태, Backend–AI 경계, 진행 알림, 복구, 저장 일관성 |
| [F2 오프라인 데이터·학습·평가](f2/offline-data-training-evaluation.md) | 평가셋과 모델 개선·승격 기준을 논의할 때 | 합성 데이터, 분할, 평가 계층, 버전, 피드백 루프 |
| [F3 개요](f3/overview.md) | F3 전체 흐름과 팀별 책임을 처음 파악할 때 | 핵심 교차 판정, 모듈 경계, SQL 후보와 하이브리드 로그 검색 |
| [F3 온라인 실행](f3/online-runtime.md) | 자동 트리거부터 최종 판정까지 구현 흐름을 논의할 때 | 영속 작업, 단계 공개, AI facade·Backend capability, 캐시·복구 |
| [F3 오프라인 데이터·평가](f3/offline-data-evaluation.md) | 데이터셋과 멀티 에이전트 효과를 검증할 때 | 합성·비식별 데이터, 검색 비교, 단일 프롬프트 A/B, 성능셋 |

필요해질 때 기능 폴더를 추가한다. 빈 `common/`, `f1/`, `assets/` 구조는 미리 만들지 않으며, Mermaid 다이어그램은 관련 문서 안에서 관리한다.

## 작성과 승인 규칙

1. 요구사항 문장이나 필드 목록을 복사하지 않고 정본 문서에 연결한다.
2. 승인된 모듈 경계는 [ADR-0006](../../.agents/skills/project-wiki/references/decisions/ADR-0006-ai-backend-boundary.md)을 재정의하지 않는다.
3. DB·큐·웹 프레임워크·모델 서빙 제품은 승인 ADR이 생기기 전까지 후보 또는 미확정으로 표시한다.
4. 모듈 내부 폴더 구조와 클래스 패턴은 모듈별 skill references가 소유한다.
5. 미확정 사항은 해당 `open-questions.md`에 두고 이곳에는 링크와 아키텍처 영향만 기록한다.
6. 팀 승인 후 프로젝트 공통 결정만 ADR로 옮기고, 이 문서는 흐름과 다이어그램을 설명하는 자료로 유지한다.

