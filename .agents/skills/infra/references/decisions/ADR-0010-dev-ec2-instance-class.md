---
status: 결정
updated: 2026-08-20
---

# ADR-0010: 개발 환경 EC2 instance class 축소

- 상태: 승인됨
- 결정일: 2026-08-20
- 부분 대체: [ADR-0004](ADR-0004-dev-runtime-and-observability-baseline.md)의 EC2 `t3.medium` instance class 결정

## 맥락

4인이 공유하는 개발·시연 환경에서 Backend API와 Worker를 한 EC2 호스트에 배치하지만 모델 추론은 RunPod나 OpenAI로 분리한다. 적용 전 예상 비용을 재검토한 결과, 초기 공유 부하에 대해 4 GiB 메모리를 고정 배치하는 것보다 2 GiB로 시작하고 측정 결과로 조정하는 편이 예산에 맞다.

## 결정

- Amazon Linux 2023 x86_64 Launch Template의 instance class를 `t3.small`로 사용한다.
- CPU credit은 `standard`, root volume은 암호화된 gp3 40 GiB를 유지한다.
- ASG 0↔1 전원 수명주기, ALB, public IPv4, AMI architecture와 runtime IAM은 변경하지 않는다.
- RDS instance class와 스토리지를 포함한 데이터베이스 구성은 변경하지 않는다.
- 실제 적용 후 EC2 CPU, CPU credit, 메모리, OOM·swap, 디스크와 API·Worker 지연을 측정한다. 재조정 임계값은 `INFRA-OQ-007`에서 계속 관리한다.

## 결과

EC2는 2 vCPU·2 GiB 기준으로 시작해 4 GiB 기준보다 상시 compute 비용을 줄인다. 반면 API와 Worker의 합산 메모리가 부족할 수 있으며, OOM·swap 또는 지연 회귀가 확인되면 Launch Template의 instance class를 `t3.medium`으로 되돌린다.

Terraform 코드와 문서만 이 결정에 맞게 변경하며, AWS workload apply와 기존 instance 교체는 별도 plan·승인 절차 전에 수행하지 않는다.
