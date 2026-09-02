---
status: 결정
updated: 2026-09-01
---

# ADR-0018: RunPod bootstrap, 비밀 회전과 읽기 전용 감시

- 상태: 승인됨·코드 구현, 외부 자원 미적용
- 결정일: 2026-09-01
- 부분 대체: [ADR-0013](ADR-0013-dev-environment-materialization.md)의 수동 비밀 tfvars 운영
- 확장: [ADR-0017](ADR-0017-runpod-ephemeral-sllm-serving.md)의 최초 구축과 운영 관측
- 상위 결정: [프로젝트 ADR-0021](../../../project-wiki/references/decisions/ADR-0021-runpod-operations-and-secret-ownership.md)

## 결정

- `runpod-bootstrap-plan <image@digest>`는 무변경 계획을, 확인이 붙은 `runpod-bootstrap`은 멱등
  구성을 수행한다. SSM `RUNPOD_CONTROL_SET`에 generation, 상태, image, registry·Template ID와
  동기화된 AI Secret Version ID를 기록하며 완전 검증 전에는 `ready`가 되지 않는다.
- RunPod resource 이름이 중복되거나 image·port·Secret 참조·Volume·SSH·registry 연결이 다르면
  덮어쓰지 않는다. 같은 provisioning generation의 검증된 자원만 재사용한다.
- `secret-status`는 값 없이 AWSCURRENT 존재만 표시한다. `secret-rotate` 입력은 TTY에서 받고,
  F2·GHCR 회전은 endpoint offline과 공유 Pod 부재를 선행 조건으로 한다. RunPod API key는 새 key
  조회 검증 후 AWS에 전환하고 다음 감시 성공 뒤 이전 key를 Console에서 비활성화한다.
- EventBridge와 Lambda는 기본 30분마다 실행한다. 주기는 5~60분의 5분 단위, 연속 실행 경고는
  1~24시간에서 조정하며 기본은 8시간이다. Lambda IAM은 두 Secret 읽기, endpoint 읽기, log와 지정
  namespace metric 쓰기만 허용한다.
- 감시 오류·heartbeat, RunPod API 2회 실패, endpoint 불일치, SLLM/STT 2회 health 실패, offline
  orphan 60분, 실행 시간 임계치를 기존 Alarm SNS/Lambda/Discord로 전달한다.

## 제외

자동 Pod 생성·삭제, endpoint 자동 선택, 감시 Lambda의 `PutParameter`·`SendCommand`, 비밀값·hash의
Terraform/argv/log/Discord 출력은 허용하지 않는다. 실제 apply·bootstrap·회전은 별도 사람 승인을
받는다.
