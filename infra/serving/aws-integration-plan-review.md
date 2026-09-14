# AWS 앱·GPU 통합 검증 계획

2026-09-07 사용자 요청: AWS GPU 우선, AWS 앱에서 실제 LLM serving 연동 검증.
기존 30만원 한도 내 2시간 검증과 GPU 약 $7.92(기타 자원 별도)를 사용자가 승인했다.
Cost Explorer는 AccessDenied라 잔여 예산은 사용자의 확인을 근거로 한다.

- 계정 398563707017, 서울, 기존 TerraformOperatorRole, On-Demand.
- saved plan: `dev-aws-gpu-validation.tfplan`
- SHA256: `0f18d007dda2a0b39a0ac529133b57aef7d388900397d60dd8d2a58df5bfdd42`
- 17 생성, 변경·삭제·교체 없음. GPU EC2 2, role/profile/policy/SSM attachment 각 2,
  SG 2, HTTPS egress 2, 앱 SG 전용 inference ingress 3.
- F2 g6.2xlarge / general g6e.2xlarge, ap-northeast-2a. On-Demand 각각 $1.20208/h, $2.75652/h.
- AMI ami-0097a4a30ec557269, AWS DLAMI owner 898082745236, available x86_64.
- 각 암호화 gp3 160GiB, termination 시 삭제. IMDSv2 hop 1, SSH 없음.
- `dev_edge_enabled=false`; 기존 DB·업무 S3·앱·CloudFront에는 Terraform 변경 없음.
- 등록된 F2/general 이미지 digest 사용. RunPod에서 검증한 수정 runtime과 FP8 후보를
  AWS 호스트에 임시 읽기 전용 마운트하여 시험한다. 게시 이미지 자체의 검증으로 보고하지 않는다.
- 앱 후보는 기존 CodeBuild에서 원격 빌드한다. 합성 입력만 사용하고 전체 seed·DB 초기화는 하지 않는다.
- 종료 시 앱/RDS는 원래 정지 상태로 복구하고 GPU는 종료한다. 캐시 EBS 제거는 별도 saved plan으로 검토한다.

`fmt -check`, `validate` 통과. 서울 AZ offering과 G/VT On-Demand quota 768 vCPU 확인.
실제 가용 용량과 AMI의 runtime 도구는 생성 이후 검증한다.

## 기존 앱 edge 복구 — 별도 사용자 승인 대기

CodeDeploy는 기존 ALB target group의 트래픽 검증을 사용한다.
- saved plan `dev-aws-app-validation.tfplan`
- SHA256 `ce1bec06981b3e861ab5a580407774a903b477c3c0031bb884b325d5d93f1495`
- 4 생성(ALB·listener·기존 alarm 2), 4 변경(CloudFront·앱 IAM policy·frontend bucket policy·allowed hosts SSM).
- 삭제·교체 없음. GPU, RDS와 업무 S3에는 변경 없음.
- 검증 종료 후 기존 deep 중지 상태로 복원한다.
- 자동 승인 검토가 공유 외부 접속 경계·정책 변경의 명시적 승인 부족으로 적용을 거절했다.
  GPU·앱 통합 요청과 별도로 사용자에게 이 구체적인 범위의 승인을 요청했다. 적용되지 않았다.

사용자는 edge 복구 대신 **외부 공개 없는 사설·SSM 검증만** 선택했다.
따라서 edge 복구 plan은 적용하지 않는다. 앱 후보 bundle을 SSM 관리 경로에서 검증하고
CodeDeploy·ALB·CloudFront 공개 배포 검증 완료로 표현하지 않는다.

## 사설 앱 검증용 자동 배포 연결 임시 해제

기존 마지막 성공 revision의 ASG 자동 배포가 AfterInstall(exit 1)에서 실패해 새 앱을 종료했다.
원인을 ALB 미복구로 단정하지 않는다. 기존 revision은 새 통합 앱 후보와 다르다.
별도 후보 stack의 사설 검증 동안 자동 배포와 인스턴스 교체가 간섭하지 않도록 연결만 임시 해제한다.

- saved plan `dev-private-app-validation.tfplan`
- SHA256 `accb96a5ec44015ea6b624880102428eccec3c21f271b0e9db98f2975287d24f`
- 유일한 변경: `aws_codedeploy_deployment_group.backend.autoscaling_groups`를 기존 앱 ASG 1개에서 빈 목록으로 변경.
- 자원 생성·삭제·교체 없음. IAM·SG·S3 정책·edge·DB·GPU 변경 없음.
- ignored `validation_override.tf`로 시험하며, 종료 후 삭제하고 saved plan으로 원래 연결을 복구한다.

## 앱 → GPU 송신 규칙 누락 수정

실제 사설 요청이 socket timeout으로 실패했다. 앱 SG가 HTTPS·DB 송신만 허용하고 있었다.

- saved plan `dev-gpu-egress-fix.tfplan`
- SHA256 `bd1b971716e3ee38fed99eebce8e6ce2850c2c6865ef5962691b11557e06dd5e`
- 앱 → 각 GPU SG의 TCP 8000·8001·8002 송신 규칙 3개 생성. CIDR 대상 없음.
- 앱 SG exclusive 관리에 이 규칙을 포함하는 변경 1개. 삭제·교체·외부 ingress 변경 없음.
- GPU 수신 규칙의 목적지 SG·포트를 재사용해 양방향 설정의 불일치를 방지한다.
- fmt·validate와 plan 목적지/포트/변경 범위 검증 통과. 실제 앱 요청으로 회귀 검증한다.

## 검증 종료·정리 계획

- saved plan `dev-aws-validation-cleanup.tfplan`
- SHA256 `dedf827be22a04b7d8c0c016a5751bbef007931fb0a01bf08f1366318b1371f6`
- GPU EC2 2개 삭제(root EBS 각 160GiB도 DeleteOnTermination), CodeDeploy–앱 ASG 연결 원복 1개.
- 앱 후보 drain·ASG 0·RDS stop 후 적용한다. 데이터베이스·업무 S3·모델 release·이미지는 삭제하지 않는다.
- GPU profiles와 IAM/SG는 보존한다. 활성 capacity 입력은 빈 목록이며 선택·endpoint는 원래 값으로 유지했다.
- ALB·CloudFront 복구 plan은 적용하지 않았다. 기존 deep 중지 상태를 유지한다.

종료 saved plan 적용: 0 생성·1 변경·2 삭제. GPU 2개와 root EBS 삭제, CodeDeploy 연결 복구를 확인했다.
후속 동일 입력 drift plan은 No changes(exit 0)다. RDS 최종 중지 확인은 검증 기록에 남긴다.
