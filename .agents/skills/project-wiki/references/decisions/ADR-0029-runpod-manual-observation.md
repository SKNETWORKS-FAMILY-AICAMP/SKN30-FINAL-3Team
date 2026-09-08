---
status: 구현됨
updated: 2026-09-07
---

# ADR-0029: 시연용 RunPod 자체 감시 제거와 offline 복구

- 상태: 사용자 선택 반영·코드 구현·팀 검토 전·외부 미적용
- 부분 대체: [ADR-0021](ADR-0021-runpod-operations-and-secret-ownership.md)의 자체 감시,
  [ADR-0031](ADR-0031-runpod-junior-operations.md)의 감시 유지·이전 endpoint 복원

## 결정

약 10명 부트캠프 프로젝트의 자체 운영 코드가 여전히 크다는 사용자 지적에 따라 범위를 더 줄인다.
사용자는 RunPod 자체 감시를 제거하고 운영자가 시작·종료를 확인하는 방식을 선택했다.

- RunPod 전용 Lambda·EventBridge·8개 경보·감시용 Secret/IAM을 제거한다.
  기존 Backend·AI 오류와 AWS 자원 경보는 유지한다.
- 운영자는 시작 시 status·smoke, 종료 시 정확한 Pod ID 삭제·Pod 부재·offline smoke를 확인한다.
  Console에서 사용액도 확인한다. 미종료·상태 불일치 자동 알림과 자동 비용 차단은 제공하지 않는다.
- Pod lifecycle 실패는 F2를 offline으로 전환·유지하고 정리·재시도한다. 이전 active 상태를 자동
  복원하지 않는다. AWS 쓰기·refresh까지 실패하면 복구 미완료로 보고하며 완료로 표시하지 않는다.
- 최초 Secret 이름·값은 Console에서 확인한다. 등록 시 Template의 Secret 참조를 검증하고 실제
  존재·값 일치는 Pod 기동의 인증 health에서 확인한다. 별도 GraphQL Secret 조회는 제거한다.

점검 중단을 허용하는 대신 운영자가 이해할 실패 분기를 줄인다. 기존 등록, 불변 release,
인증 proxy와 API 동시 분석 제한은 유지한다. 구현 상세는
[Infra ADR-0021](../../../infra/references/decisions/ADR-0021-runpod-operational-reduction.md),
일상 절차는 [runbook](../../../../../infra/runpod/README.md)이 정본이다.

Terraform 변경은 배포 전 saved plan에서 검토한다. 기존 환경에 해당 감시 자원이 있다면 삭제가
계획에 나타나는지 확인해야 하며 이번 작업에서 실제 자원을 삭제하거나 apply하지 않았다.
