# AWS 앱 → GPU 사설 통합 검증

상태: 2026-09-07 AWS 사설 앱 합성 검증 통과. 자원 종료·복구·drift 확인 완료.

## 범위와 재현성

사용자가 AWS 검증을 먼저 진행하고, 외부 공개 없이 사설·SSM 경로만 사용할 것을 선택했다.
승인 한도는 GPU 두 대 합계 2시간, 약 $7.92(앱·DB·EBS·IPv4·빌드 비용 별도)다.
PC는 AWS/Terraform 제어와 작은 코드·metadata 전송에만 사용했다. 이미지·모델 실행과
다운로드는 AWS GPU, 앱 EC2와 기존 CodeBuild에서 수행했다.

- 기존 dev VPC/앱 SG, F2 `g6.2xlarge` L4 24GB, general `g6e.2xlarge` L40S 48GB.
- DLAMI `ami-0097a4a30ec557269`, Ubuntu 24.04, Docker 29.7.2, Compose 5.5.0, NVIDIA driver 595.91.07.
- 두 GPU root는 암호화 gp3 160GiB, IMDSv2 hop limit 1.
- F2: 기존 dev Qwen3-4B LoRA release와 Whisper-large-v3-turbo.
- general: `unsloth/Qwen3.8-27B-FP8`, revision `d51e38f6f2b5877bb91e06ba231e41ffc63bde6f`.
  vLLM 0.26.0, FP8/auto, context 8192, 동시 처리 1, GPU utilization 0.85, eager/text-only/non-thinking.
- [게시 이미지와 RunPod 검증 기록](remote-validation-2026-09-07.md)의 digest를 사용하되,
  검증한 F2 supervisor·HF transfer 비활성화, general python3·FP8 runtime을 원격 후보로 적용했다.
  **수정 이미지 자체의 게시·검증 완료를 뜻하지 않는다.**
- 기존 CodeBuild의 후보 source content fingerprint는 `6ceb03a6184a027b659e96291c3fdbae7634e430`이다.
  Git commit SHA가 아니다. 소스 163개/381,694 bytes, 배포 bundle SHA256
  `3806cfb975882de39b724a6bc6bd9c34c2fa195966b5709def8097601123cd98`.
- 기존 앱 EC2에서 별도 Compose project를 실행하고 host `127.0.0.1:18080`에만 바인딩했다.
  후보 프로세스에만 AWS private endpoint를 주입했다. 공유 SSM 선택·endpoint·DB 활성 모델을 변경하지 않았다.
- 실제 F2 HTTP 경로와 Backend 관리 명령을 통한 F3 공개 AI workflow를 대상으로 한다.
  F3 HTTP 큐/Worker 전체 실행, CodeDeploy 공개 배포, ALB·CloudFront와 cloud 전환의 검증은 별도다.

## 먼저 확인한 결과

| 항목 | F2 | general FP8 |
|---|---|---|
| GPU 직접 합성 추론 | 통과: JSON·Whisper 응답 계약 | 통과: JSON 생성 |
| 호스트 모델 준비 명령부터 직접 추론 통과 | 775초 | 884초 |
| 준비 후 VRAM 단일 관측 | 19,760 MiB / 23,034 MiB | 38,735 MiB / 46,068 MiB |
| 준비 후 디스크 여유 | 64.01 GiB | 50.16 GiB |
| 모델/release 읽기 전용·캐시 쓰기 분리 | 확인 | 확인 |
| 컨테이너 IMDS token 요청 불가 | 확인 | 확인 |
| GPU ingress에 public CIDR 없음 | 확인 | 확인 |

메모리는 최대 관측치나 부하 시험 결과가 아니다. 준비 시간에는 최초 이미지 pull과 다운로드가
포함되고, EC2 생성·cloud-init 대기 시간은 제외된다. stop/start 캐시 재사용 시간은 아직 측정하지 않았다.

## 발견·수정한 문제

1. 앱 → GPU 송신 규칙이 빠져 private 요청이 socket timeout으로 실패했다.
   앱은 HTTPS·DB 송신만 허용하고 있었다. `serving.tf`에 GPU SG·지정 포트만 대상으로 한
   송신 규칙을 추가하고 `security.tf`의 exclusive 규칙 집합에 포함했다.
2. 기존 마지막 성공 앱 revision의 ASG 자동 배포가 AfterInstall에서 실패해 EC2가 교체됐다.
   사설 시험 중에만 Terraform으로 CodeDeploy–ASG 연결을 해제했다. 실패 원인을 ALB로 단정하지 않는다.
   정식 통합 운영 전 새 앱 revision의 배포·기동 검증이 필요하다.
3. SSM 온라인과 Docker/API 준비 완료 시점은 다르다. 검증용 설치는 cloud-init 완료 후,
   합성 요청은 HTTP readiness 통과 후 수행했다.

변경별 saved plan과 정확한 범위는 [검토 기록](aws-integration-plan-review.md)을 따른다.

## AWS 앱에서 실행한 최종 결과

| 검증 | 결과 |
|---|---|
| Backend readiness | HTTP 200 |
| GPU 무인증 요청 | SLLM·STT·general 모두 HTTP 401 |
| F2 실제 Backend HTTP 음성 분석 | 통과, 11.77초 |
| Backend 실행환경의 범용 한국어 생성 | 통과, 3.51초 |
| Backend 관리 명령 → AI 포지션 카드 2개·중개 판정 | 통과, 합계 155.88초 |
| AI 요청 제한 | 기존 요청별 60초 유지, SDK 자동 retry 0 |
| DB 비교 | property_listing·property_requirement·client_interaction·agent_run 행 수와 ai_model_config 행 수/내용 fingerprint 동일 |

3.51초와 155.88초에는 disposable 앱 컨테이너 시작 비용도 포함된다.
F3 합계 시간은 단일 모델 호출 지연이 아니며, 동시 부하·요청 제한 여유·품질 평가를 대체하지 않는다.
검증은 전체 seed나 DB 모델 활성화를 실행하지 않았다. 개발 세션 발급에 따른 합성 세션 기록은
위 업무 테이블 비교에서 제외한다. 원문 요청·응답과 비밀값은 결과 문서에 보존하지 않는다.

## 비용 범위

EC2 LaunchTime부터 stop 요청까지 F2 36.48분, general 36.54분이다.
현재 서울 On-Demand 단가를 곱한 GPU 합계는 약 **$2.41**이다. 청구서 확정값이 아니며
종료 지연·EBS·IPv4·앱/RDS·CodeBuild·이미지/소스 보관 비용과 세금은 별도다.
Cost Explorer 조회 권한이 없어 실제 누적 청구액은 확인하지 않았다.

## 종료 확인

- 검증용 앱 drain 완료, 앱 ASG desired 0 / EC2 0.
- GPU EC2 두 대 terminated, 연결됐던 root EBS 두 개 삭제 확인. 캐시 snapshot은 만들지 않았다.
- CodeDeploy–ASG 연결 원복 완료. 마지막 성공 deployment 참조는 기존 값 그대로다.
- CloudFront disabled, 관리 ALB 0. 외부 edge 복구 plan은 적용하지 않았다.
- 공유 선택은 f2/general 모두 null, endpoint는 기존 offline 상태다.
- F2 release.json·bundle.tar.gz 정본 보존 확인. 기존 GPU IAM/SG·profile, 앱 후보 이미지와 작은 배포 artifact는 보존한다.
- 같은 중지 입력의 최종 Terraform plan은 **No changes, exit 0**이다.
- RDS stopped 확인 완료(2026-09-07 17:17 KST).

수정 runtime을 포함한 이미지 재게시, FP8의 정식 설정 반영, 새 앱 revision 배포와
공유 모델의 명시적 활성화는 후속 작업이다. 이 기록으로 공개 배포·양방향 전환·
일반/deep start의 캐시 재사용/재생성·동시 부하 검증까지 완료됐다고 간주하지 않는다.
