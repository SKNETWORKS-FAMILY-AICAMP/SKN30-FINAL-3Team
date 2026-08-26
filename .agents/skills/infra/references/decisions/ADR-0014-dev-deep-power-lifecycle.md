---
status: 결정
updated: 2026-08-25
---

# ADR-0014: 개발 환경 deep 전원 수명주기

- 상태: 승인됨
- 결정일: 2026-08-25
- 부분 대체: [ADR-0009](ADR-0009-dev-power-lifecycle.md)의 ASG·RDS 외 자원을 전원 도구가 변경하지 않는 경계와 ALB·public IPv4 잔여 비용 수용

## 맥락

일상적인 `dev-stop`은 ASG desired capacity를 0으로 내리고 RDS를 정지하지만 ALB와 ALB가 사용하는 두 public IPv4의 시간 비용은 남는다. 여러 날 이상 공유 dev를 사용하지 않을 때 자원 정체성·RDS 데이터·배포 연결점을 유지하면서 edge 고정비를 줄일 별도 수명주기가 필요하다.

ALB는 stop/start API가 없으며 public IPv4는 ALB service-managed 자원이므로 ALB를 삭제해야 반납된다. CloudFront distribution은 비활성화하면 고정 식별자와 기본 domain을 보존하면서 요청 비용을 멈출 수 있으므로 반복 삭제하지 않는다.

## 결정

### 두 수명주기

- `dev-start`/`dev-stop`은 기존처럼 RDS 실행 상태와 ASG desired 0↔1만 변경하는 일상 전원 명령으로 유지한다.
- `dev-deep-start`/`dev-deep-stop`은 여러 날 이상의 미사용 기간에 ASG·RDS와 edge를 함께 전환한다.
- 두 수명주기를 동시에 실행하지 않고, 배포·migration·API·Worker 작업 종료를 먼저 확인한다.

### Terraform edge 경계

- `dev_edge_enabled`의 기본값은 `true`며 일반 `dev-plan`/`dev-drift`는 활성 edge를 기준으로 한다.
- deep 전용 plan이 `dev_edge_enabled=false` 또는 `true`를 CLI로 명시하고 saved plan에 고정한다. 공유 원격 state 밖의 지속 변수 파일을 deep 상태 정본으로 사용하지 않는다.
- deep suspend에서 ALB, HTTP listener, ALB unhealthy/target-5xx alarm을 Terraform으로 제거한다. ALB service-managed public IPv4는 AWS가 함께 반납한다.
- target group, ALB·App security group, ASG, Launch Template, IAM, CodeDeploy 연결은 유지한다. 별도 시간 비용이 없고 target group은 ASG·CodeDeploy의 안정적인 복구 연결점이다.
- singleton에서 조건부 instance `[*]` 주소로의 최초 전환은 Terraform `moved` 블록으로 소유권을 보존한다. 활성 자원은 이동한 `[0]` 주소에서 삭제·재생성되고 이미 수동 삭제된 원격 자원은 plan refresh가 drift로 제거한다.

### CloudFront와 Backend 설정

- CloudFront distribution, OAC, private Frontend S3와 bucket policy는 삭제하지 않는다.
- deep suspend에서 distribution을 비활성화하고 ALB custom origin과 `/api/*`, `/health/*` behavior를 제거한다. S3 default origin은 distribution 구성을 유효하게 유지하기 위해 보존한다.
- deep start에서 새 ALB DNS를 CloudFront origin과 Backend `HTTP_ALLOWED_HOSTS`에 함께 반영한다. suspend 중 allowed-host에는 localhost 경계만 남긴다.
- deep suspend 중에는 통합 Pipeline의 자동 변경 감지를 끄고 deep start가 edge를 복구할 때 승인된 변수값으로 되돌린다. 수동 Pipeline도 suspend 중에는 실행하지 않는다.
- distribution을 재생성하지 않으므로 Frontend URL, distribution ID, S3 SourceArn와 delivery IAM 연결은 변경하지 않는다.

### 승인·순서·복구

- deep stop은 `plan → show → 승인 → ASG 0/RDS stopped → saved plan apply → deep drift`를 순차 실행한다.
- deep start는 `plan → show → 승인 → saved plan apply → RDS available/ASG 1/SSM Online → 일반 drift`를 순차 실행한다.
- deep suspend 중에는 일반 `dev-plan`/`dev-apply`/`dev-drift`를 사용하지 않고 `dev-deep-drift` 또는 deep start 절차를 사용한다. 일반 plan은 활성 edge 기준이므로 ALB 복구를 예고한다.
- 중단·timeout·부분 실패 후에는 `dev-deep-status`와 Terraform plan을 확인한 뒤 실패한 단계만 재시도한다. 자원을 AWS CLI나 Console로 수동 생성·삭제하지 않는다.

## 비용과 결과

2026-08-25 공식 단가 기준 deep suspend의 고정비 절감은 서울 ALB USD 0.0225/시간과 public IPv4 두 개 USD 0.0100/시간을 합한 USD 0.0325/시간이다. LCU·CloudFront request 절감은 사용량에 따라 추가된다. 대신 deep 전환은 CloudFront 전역 배포와 ALB 생성·삭제 시간을 포함하므로 일상적인 수시간 정지보다 여러 날 이상의 미사용에 사용한다.

이 변경은 Terraform 코드·명령·문서를 구현하지만 AWS deep stop/start apply는 별도 saved plan 검토와 승인 전에 수행하지 않는다.
