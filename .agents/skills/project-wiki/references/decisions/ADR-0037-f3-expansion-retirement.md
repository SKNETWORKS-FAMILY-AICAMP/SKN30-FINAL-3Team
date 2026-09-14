---
status: 결정
updated: 2026-09-09
---

# ADR-0037: PR #116·#117·#118의 F3 확장 기능 폐기

- 출처: 2026-09-09 프로젝트 요청자의 세 PR 롤백 및 해당 범위 기능 폐기 지시.
- 대체: [ADR-0035](ADR-0035-f3-conditional-automation-results.md).

## 결정

세 PR을 Git revert로 역적용한다. 조건부 자동 판정, 변경 revision/outbox, 완료 판정 재사용, 저장 결과 조회 API·목록·상세와 결과 시드를 폐기한다. 과거 관련 제안은 재구현 승인이 아니다.
기존 F3의 저장 시 앵커 카드 생성과 사용자 요청에 의한 후보 조회·판정은 [ADR-0018](ADR-0018-f3-save-trigger-anchor-card-scope.md)로 복원한다.
후속 #119 공유 dev 서빙 변경과 자동 판정 외 로컬 설정은 유지한다. 원래 작업 폴더의 미커밋 변경은 보존하며 롤백 브랜치에 포함하지 않는다.

## 운영 경계

이 결정의 실행 범위는 저장소 코드·계약·문서다. Git은 이미 적용된 DB schema, migration 적용 이력, 생성된 시드 데이터 또는 실행 중인 서비스를 되돌리지 않는다.
020·021 migration 파일은 역적용 범위에서 제거한다. 이미 적용한 DB에서는 match_source_revision·match_change_outbox·match_target_state, 변경 trigger/function 및 agent_run의 next_attempt_at·priority가 남을 수 있다. 적용 이력과 실제 schema를 확인하고 백업 후 별도 전환 절차를 정해야 한다. 과거 migration 번호 020·021을 다른 목적으로 재사용하지 않는다.
이번 작업에서는 DB 접속·데이터 삭제·배포·클라우드 적용을 수행하지 않는다. 기존 DB에서 migration 실행과 통합 동작은 검증되지 않았다.