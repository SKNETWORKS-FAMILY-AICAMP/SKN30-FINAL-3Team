---
status: 구현됨
updated: 2026-09-08
---

# ADR-0022: AWS·RunPod GPU 전원, 캐시와 SSM 경계

> 2026-09-09 부분 대체: 공유 선택 형식·실행 중 전환·일반/deep 시작 계획은 [ADR-0024](ADR-0024-shared-serving-selection-lifecycle.md)를 따른다. 아래 검증/기반 적용 기록과 AWS 전원·캐시·권한 경계는 보존한다.

- 상태: 사용자 구현·기반 적용 승인·SSM/IAM 적용 및 AWS 후보 사설 검증 완료·팀 병합 검토 대기·정식 배포/왕복 검증 미완료
- 승인 경계: 사용자 작업 승인과 작성자 외 팀원의 PR 병합 승인은 별개다. 이 문서는 팀 승인 완료를 주장하지 않는다.
- 부분 대체: ADR-0009·0014의 앱/RDS/edge만 다루는 전원 범위,
  ADR-0017·0020의 F2 전용 RunPod 운영. Console 최초 설정과 감시 제거는 유지한다.
- 공통 정책: [프로젝트 ADR-0030](../../../project-wiki/references/decisions/ADR-0030-local-dev-dual-cloud-serving.md)

## 소유권과 구성

기존 dev Terraform root에 독립 GPU EC2를 둔다. 기본 검증 대상은 F2
`g6.2xlarge`(24GB VRAM), general `g6e.2xlarge`(48GB VRAM)다. GPU 전용 ALB,
NAT Gateway, Elastic IP, ASG는 추가하지 않는다. 기존 public subnet·IGW로 모델을
받고 추론 포트는 앱 SG에서만 허용한다. 자동 public IPv4는 정지 시 반납하며 앱 접속에는 쓰지 않는다.

`gpu_profiles`는 검토한 AMI·GHCR image digest·EBS 크기를 보존한다.
`gpu_provisioned_workloads`는 생성할 작업의 집합이며 기본값은 빈 집합이다.
`capacity-config`가 ignored `serving-capacity.auto.tfvars.json`을 생성한다.
일반·deep·전환 plan은 이 파일과 같은 `dev.tfvars`를 읽는다. 다른 변수나 환경변수로
생성 대상 값을 중복 지정하지 않는다. SSM `serving/SELECTION`은 장소·RunPod GPU 종류·F2
release 선택만 보존하고 endpoint 문서는 실행 자원을 가리킨다. Terraform은 운영값을 덮어쓰지 않는다.

AWS 전환 plan은 기존 EC2를 보존하며 대상을 추가한다. deep-start plan은 선택이 AWS인
작업만 생성 대상으로 기록한다. 운영자가 plan·전환·배포를 동시에 실행하지 않는다.
잠금 서비스나 별도 controller DB를 만들지 않는다.

## 호스트와 보존

고정 NVIDIA DLAMI의 Docker Compose·driver/toolkit·AWS CLI·SSM 호환성을 먼저 검증한다.
systemd가 호스트 준비와 Compose를 실행한다. 자동 재시작 루프는 없다.
암호화 gp3 root EBS(기본 160GiB)에 모델·캐시를 보존한다. 모델·release는 읽기 전용
마운트로 제공하고 다운로드·컴파일 캐시는 별도 디렉터리에 둔다. revision이 바뀌면 모델을
다시 받는다. root와 모델을 별도 EBS로 분리하지 않는다.

Instance Role은 호스트의 Secret·S3 읽기에 사용한다. 컨테이너는 bridge network·IMDSv2
hop limit 1을 사용하고 AWS 자격증명과 호스트 Secret 파일을 마운트하지 않는다.
GHCR pull은 password-stdin으로 실행하고 인증을 제거한다. 서비스 키는 0600 환경파일로
필요한 프로세스에만 주입한다. AWS와 RunPod는 같은 등록 image digest를 사용한다.
범용 vLLM은 F2와 별도로 고정하며 실제 GPU 호환성 결과를 기록한다.

RunPod Secret·registry·작업별 Template은 Console에서 처음 생성한다. 기존 도구를
`f2` 기본값과 `general` 선택자로 확장한다. Volume·Network Volume 없이 실행하고 Pod를
삭제한다. Template·registry·등록값·S3 release와 이미지 정본은 보존한다.

## 전원과 권한

- stop: 앱 drain → 두 장소의 관리 GPU 종료 시도 → ASG 0·RDS stop.
  AWS EBS는 보존하고 RunPod는 삭제한다. 일부 실패에도 다른 종료를 시도하고 실패를 반환한다.
- start: 선택 GPU 준비·직접 추론 → endpoint → RDS·앱 복구 → 합성 추론 → 잔존 GPU 정리.
- deep-stop: stop 후 saved plan으로 기존 edge와 GPU EC2/root EBS를 제거한다.
  캐시 snapshot을 만들지 않는다. DB·모델 정본·Template·선택은 보존한다.
- deep-start: saved plan으로 edge·선택 AWS GPU를 재생성하고 캐시 재다운로드·연결 등록을 수행한다.
- `team-gpu-tunnel`은 지정 GPU·고정 target port Session Document와 자신의 session 관리만
  허용한다. 그룹 가입은 기존 운영자가 관리한다. Shell·RunCommand·전원·배포 권한을 포함하지 않는다.
  로컬 포트 18000·18001·18002로 앱 8000과 충돌을 피한다.

## 비용과 검증

무요청 실행 중에도 GPU 요금이 발생한다. AWS stop 뒤 EBS, RunPod stop 뒤 남긴 Volume과
독립 Network Volume은 과금된다. GPU·캐시 삭제 뒤에도 DB·S3·이미지 정본과 일반 stop의
기존 edge 비용은 남는다. On-Demand만 사용한다. 생성 전 서울 AZ offering·실시간 용량·vCPU
quota·단가·검증 시간·잔여 예산을 확인한다.

`fmt → validate → saved plan → 승인 → apply → 검증 → drift`를 따른다.
실제 왕복 검증은 [운영 절차](../../../../../infra/serving/README.md)에 연결한다.

## 기반 적용 기록

2026-09-07 승인된 saved plan 적용(9 생성·7 변경·16 삭제)과 같은 deep 중지 입력의 drift 없음 확인을 마쳤다. 앱 0·RDS stopped·GPU 0이며 기존 F2 등록과 업무 S3를 보존했다. GPU·앱 새 revision과 실제 왕복 추론은 후속 검증 대상이다. 상세 기록은 [기반 plan 검토](../../../../../infra/serving/foundation-plan-review.md)에 둔다.

## AWS 사설 통합 검증

2026-09-07 AWS GPU 수정 후보에서 F2 HTTP·general FP8 합성 workflow를 검증했다.
앱 SG의 송신과 GPU SG의 수신을 같은 작업별 포트로 제한하고, 앱 exclusive 규칙 집합에도
GPU 송신 규칙을 포함해야 한다. GPU inbound만 허용하면 앱 HTTPS-only egress 때문에 연결이 실패한다.
후보·정식 배포와 검증 범위의 구분은 [실제 검증 기록](../../../../../infra/serving/aws-private-validation-2026-09-07.md)을 따른다.
