---
status: 구현됨
updated: 2026-09-09
---

# ADR-0036: 공유 dev 서빙 선택과 명시적 DB 모델 적용

- 상태: 사용자의 전체 계획 구현 승인에 따른 코드·자동 검증. 팀 병합 검토·공유 환경 적용·새 이미지 게시·실제 기동 검증은 별도다.
- 출처: [manifest](../../sources/manifest.yaml)의 `shared-dev-serving-selection-implementation-2026-09-09`.
- 부분 대체: ADR-0030의 실행 중 GPU 전환·분리 선택 흐름, ADR-0034의 공유 dev 단일 대상 DB 명령만 제공하던 운영 경로.
- 유지: local OpenAI·모듈별 환경 소유권·AI provider/model enum·고정 모델 provenance·Backend DB 소유권·이력 보존·수동 전원·자동 fallback 금지.

## 선택과 저장

공유 dev만 통합 메뉴 `ai-select`로 구성한다. 인자 없는 메뉴와 명시형을 모두 제공하며 F2/general별
cloud·hardware·release 또는 model profile을 선택한다. 통합 메뉴의 provider는 vLLM이며 기존
OpenAI·Bedrock 고급 수동 경로를 제거하지 않는다. CPU 전환은 이번 승인 계획에서 제외했다.

지원 조합·이미지·검증 근거는 Git 카탈로그, 공유 희망 구성은 기존 SSM `serving/SELECTION` v2에 둔다.
선택 ID·변경자·시각과 명시한 모델·클라우드를 보존한다. 마지막 적용 단계·결과는 `serving/APPLIED`,
실제 주소·준비 상태는 기존 endpoint 문서, 활성 모델 이력은 Backend DB가 소유한다. 비밀은 기존
Secret 저장소에 유지하고 별도 감사 DB·상시 controller를 추가하지 않는다.

선택은 앱/Worker와 관리 GPU가 정지된 때만 허용하며 GPU·DB 변경을 수행하지 않는다.
기존 선택을 읽기만 해도 SSM을 쓰지 않는다. 지원하지 않는 값은 거부하고 다른 조합으로 대체하지 않는다.

## 기동과 DB 책임

일반 변경은 `dev-stop → ai-select → dev-start`, 최초 앱 전환은
`ai-select → dev-prepare-app → app-deploy → dev-start`다. 새 앱 배포는 별도 명령으로 유지한다.
종료 후 새 호스트 복구는 이전 실제 호스트의 배포 성공·앱 합성 검증으로 기록한 정확한 revision에만
허용하며, 검증하지 않은 최신 revision이나 새 Pipeline을 자동 실행하지 않는다.
기동 시 인프라 계획·비용을 확인한 뒤 RDS와 maintenance 호스트에서 Backend CLI로 사무소·capability
목록을 읽고 사용자가 대상과 전후 모델을 확인한다. 구 revision/CLI가 없으면 배포 선행 조건을 표시한다.

GPU 준비 뒤 확인한 대상만 새 설정 버전으로 적용한다. 같은 설정은 건너뛰고 이전 설정·run snapshot과
업무 데이터를 보존한다. 하나의 general 서버와 호환되지 않는 활성 설정을 대상 밖에 남겨 두거나
대기·실행 요청이 있으면 기동을 막는다. DB snapshot이 달라지면 다시 검토한다. Infra가 직접 SQL을
쓰거나 새 HTTP API·전체 seed 초기화·자동 일괄 변경을 추가하지 않는다.

Backend 상세 계약은 [모델 대상 선택](../../../backend/references/model-selection.md),
Terraform·RunPod·계획 검증·실패 정리는 [Infra ADR-0024](../../../infra/references/decisions/ADR-0024-shared-serving-selection-lifecycle.md)가 정본이다.

## 수용 기준

코드와 자동 검증은 선택 Enum·지원 조합·stale plan·정지 조건·DB snapshot·선택 대상 제한·동일 설정
건너뛰기·원자적 rollback·이력 보존을 확인한다. GPU 모델 기동·추론·관측 VRAM·응답시간과 일반 재기동·
deep 재생성·양방향 전환은 사용자가 수행한다. 새 consultation-v3/A5000 조합을 과거 24GB 후보의
성공으로 승격하지 않으며 이미지 게시·등록·기동·합성 통과·품질 평가는 서로 다른 상태다.
