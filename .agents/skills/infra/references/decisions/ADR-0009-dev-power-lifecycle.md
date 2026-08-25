---
status: 부분 대체됨
updated: 2026-08-25
---

# ADR-0009: 개발 환경 전원 수명주기

- 상태: 부분 대체됨
- 결정일: 2026-08-19
- 부분 대체: ADR-0004의 ASG `min=desired=max=1`과 고정 1대 기준 용량 알람
- 대체 관계: ASG·RDS 외 자원 변경 금지와 ALB·public IPv4 잔여 비용 수용은 [ADR-0014](ADR-0014-dev-deep-power-lifecycle.md)가 deep 수명주기에 한해 부분 대체한다.

## 맥락

공유 개발 환경은 업무 외 시간에도 EC2와 RDS compute 비용이 계속 발생한다. 일상적인 비용 절감에 `terraform destroy/apply`를 사용하면 RDS 보존, Secret, state와 복구 시간이 불필요하게 흔들린다. RDS 임시 정지와 ASG 0↔1 전환으로 데이터와 Terraform 관리 자원을 유지하면서 compute 비용을 줄일 운영 경계가 필요하다.

AWS 계정 root 사용자는 일상 운영에 사용하지 않는다. 일반 팀원에게 전원 제어 권한을 추가하지 않고 기존 지정 Infra 운영자만 현재 `TerraformOperatorRole`을 assume해 실행한다.

## 결정

### Terraform과 운영 상태 소유권

- Terraform은 ASG `min_size=0`, 최초 `desired_capacity=1`, `max_size=1`, Launch Template과 연결 자원을 소유한다.
- 최초 생성 이후 ASG `desired_capacity`의 0 또는 1은 전원 관리 도구가 소유하며 Terraform은 해당 속성의 후속 변경을 무시한다.
- RDS 구성, 스토리지, 백업, Secret과 삭제 방지는 계속 Terraform이 소유한다. 실행 상태인 `available/stopped`만 전원 관리 도구가 바꾼다.
- 그 밖의 AWS 자원은 전원 관리 도구가 생성, 수정 또는 삭제하지 않는다.
- Terraform plan/apply와 전원 전환을 동시에 실행하지 않는다.

### 인증과 권한

- 별도 IAM 사용자, 그룹, 정책과 role을 만들지 않는다.
- `infra/.env`의 계정 guard와 `skn30-session` 임시 로그인 세션을 사용한다.
- 호출자가 대상 계정과 일치하고 AWS account root가 아닌지 확인한 뒤 기존 `TerraformOperatorRole`을 assume한다.
- 일반 팀원과 `team-readonly`, `team-db-tunnel` 그룹에는 start/stop 권한을 추가하지 않는다.

### 전원 관리 도구

- `infra/scripts/manage_dev_power.py` 하나가 `start --apply`, `stop --apply --workloads-stopped-confirmed`, `status`를 제공한다.
- 대상은 프로젝트·환경·Terraform 관리 태그와 고정 이름이 모두 일치하는 dev ASG와 RDS로 제한한다.
- 명령은 현재 상태를 먼저 읽고 이미 목표 상태이면 성공하므로 반복 실행할 수 있다.
- `stop`은 활성 배포, migration, API 요청과 Worker 작업이 끝났다는 운영자 확인 후 ASG를 0으로 내리고 EC2 종료를 기다린 다음 RDS를 정지한다.
- `start`는 RDS `available`, ASG 1대 `InService/Healthy`, SSM `Online` 순으로 기다린다.
- delivery가 구현되기 전에는 새 EC2에 애플리케이션 자동 복구를 보장하지 않는다. ALB target 상태는 결과에 포함하지만 start 성공 조건으로 사용하지 않는다.
- 중단 또는 timeout 후에는 `status`로 실제 상태를 확인한 뒤 재시도한다.

### 관측과 비용

- ASG 용량 알람은 `desired - in_service > 0`일 때만 장애로 판단한다. 의도적인 `desired=0`은 정상이다.
- RDS는 최대 7일 연속 정지만 보장하고 이후 자동 시작될 수 있으므로 장기 휴무에는 상태를 다시 확인한다.
- RDS 스토리지·백업, ALB, public IPv4, S3, CloudFront, Secrets Manager와 CloudWatch 비용은 정지 중에도 남는다.
- ASG 축소는 EC2 종료이며 root EBS는 삭제된다. 애플리케이션과 로컬 상태는 Launch Template과 delivery로 재현해야 한다.

## 결과

일상적인 비용 절감이 Terraform destroy와 분리되고 RDS 데이터·endpoint·Secret을 유지할 수 있다. 반면 공유 환경은 운영자 명령으로 전체 팀에 중단되므로 실행 전 작업 종료 확인이 필요하다. 전원 상태는 Terraform drift 대상에서 제외되며 비용 절감률과 실제 시작 시간은 사용 패턴과 RDS 복구 시간에 따라 달라진다.

이번 구현은 Terraform apply, 실제 ASG 축소·확장과 RDS start/stop을 수행하지 않는다.
