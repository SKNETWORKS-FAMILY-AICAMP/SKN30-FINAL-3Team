---
status: 결정
updated: 2026-09-04
---

# F3 Backend–AI 구현 현황

구현·계획·미확정 범위를 대조할 때만 읽는다. 현재 작업의 계약은 [F3 계약 인덱스](f3-ai.md)에서 선택한다.

## 구현 범위

### 이번 구현 범위 (`구현됨`)

- `negotiation_side`, intent, urgency, contactability, evidence, price_kind 어휘
- 계약 버전 `position-card:v1`
- 요청·결과 DTO와 LISTING/REQUIREMENT 입력 격리
- `PositionCardGenerator` Protocol
- `PositionCardGeneratorVersions`와 실제 prompt·workflow 버전
- `SYNTHETIC_PROTOTYPE`·`MASKED` 입력 모드와 합성 모드의 명시적 생성기 opt-in
- `LlmPositionCardGenerator` 구조화 출력 생성 구현
- 모델 출력에서 서버 소유 대상·source identity·장부 표기 금액을 제거한 내부 schema
- 대리 측면별 한국어 프롬프트와 전체 상담 로그 시간순 전달
- 주입한 fake Provider로 모델 요청·출력 조립을 검증하는 단위 테스트
- 생성 결과 반환 전 요청·결과 교차 검증을 강제하는 순수 함수
- Backend `AnchorType`과의 값 일치 계약 테스트
- 정본 등록과 OQ-012 종료를 강제하는 계약 테스트
- 합성 F1 장부·측면별 상담 로그를 `SYNTHETIC_PROTOTYPE` 요청 snapshot으로 조립
- 입력 전체 fingerprint와 상담 범위 identity를 포함하는 Backend cache key `position-card:v3`
- AI 호출 전후 transaction 분리와 lease·attempt·입력 버전·상담 범위·source identity 재검증
- 검증된 카드·거래 유형별 가격·근거 인용과 quote offset 저장
- cache hit 재사용과 저장 경합 단일화, `ANCHOR_READY` 상태 전이
- 결정적 SQL 후보 snapshot의 상위 5건에 대한 반대편 카드 병렬 생성·순차 검증/저장·캐시 재사용
- 후보 카드 ID snapshot 기록과 전건 성공 후 `CANDIDATE_CARDS_READY` 상태 전이
- 중개 판정 계약 `brokerage-judgment:v1`, 등급·행동·근거 어휘와 프레임워크 중립 Protocol
- 앵커 1장과 후보 1~5장을 한 번에 보내는 Provider 중립 구조화 출력 생성기
- 합성 입력 이중 opt-in과 생성 결과 반환 전 후보 집합·순위·근거 교차 검증
- 저장된 앵커·후보 카드의 판정 요청 조립과 `SYNTHETIC_PROTOTYPE` privacy mode 고정
- AI 호출 전후 transaction 분리와 lease·attempt·바인딩·앵커·후보 장부 버전·후보 집합 재검증
- 후보별 등급·순위·걸림돌·양보·행동·기각 사유·근거의 원자 저장
- `JUDGING`·`COMPLETED` 상태 전이와 만료된 `JUDGING` lease 재선점·재실행
- 후보 0건의 AI 호출 없는 빈 결과 완료
- RDS polling Worker와 저장 상태 기반 F3 handler 연결
- capability별 모델 설정의 단계별 lazy binding과 합성 프로토타입 이중 opt-in
- `F3_ALLOW_SYNTHETIC_PROTOTYPE=true`가 없으면 DB·Provider 접근과 claim 전에 활성 Worker 기동 거절
- 일시 Provider 오류의 lease release·3회 상한 재시도, 입력 변경 `SUPERSEDED`, 영구 오류
  `FAILED_TERMINAL` 처리

### 아직 구현하지 않음 (`계획됨`)

- 실제 F1 사용자 데이터를 위한 상담 로그 마스킹과 `MASKED` 모드 전환
- Bedrock runtime·endpoint·IAM Terraform 코드의 실제 AWS apply와 합성 smoke. 적용 전에는
  공유 dev DB의 활성 모델을 Bedrock 프로필로 전환하지 않는다
- F3 전체 production LangGraph와 checkpoint. 포지션 카드 1회 구조화 호출에는 이름뿐인 graph를
  덧씌우지 않는다

### 미확정

- prod 모델 평가 통과 기준과 최종 승격 모델
- LangGraph checkpoint 저장 계약 (AI-OQ-004)
