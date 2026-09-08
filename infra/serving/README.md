# Local·dev LLM 운영

상태: 코드·자동 검증과 기반 Terraform 적용 완료. **RunPod에서 F2 수정 후보와 general Unsloth FP8 후보의 직접 추론 검증을 통과했다. AWS GPU 후보와 사설 앱의 F2 HTTP·F3 두 capability도 통과했다. 수정 이미지 재게시·정식 앱 배포·왕복 검증은 남아 있다.**
공통 결정은 [프로젝트 ADR-0030](../../.agents/skills/project-wiki/references/decisions/ADR-0030-local-dev-dual-cloud-serving.md),
전원·권한은 [Infra ADR-0022](../../.agents/skills/infra/references/decisions/ADR-0022-dual-cloud-gpu-lifecycle.md),
측정·적용 현황은 [validation.md](validation.md), AWS 사설 앱 결과는
[검증 기록](aws-private-validation-2026-09-07.md)을 따른다.

| 구분 | local | 공유 dev |
|---|---|---|
| 앱 실행 | 개발자 PC | 기존 AWS 앱 EC2 |
| 범용 기본값 | 개인 OpenAI·기존 모델 | 명시적 모델 활성화 필요; FP8 후보 합성 검증 통과 |
| GPU 선택 | 개인 프로세스에 명시 주입 | 운영자가 f2/general별 AWS·RunPod 선택 |
| AWS 접속 | 고정 target port SSM 터널 | 앱 SG에서 GPU 사설 주소 |
| RunPod 접속 | 승인된 키·해당 Pod HTTPS proxy | Secrets Manager 키·해당 Pod HTTPS proxy |
| 전원·배포 | Infra 운영자만 | 아래 dev 명령 |

F2는 기존 SLLM·Whisper를 유지하며 OpenAI로 대체하지 않는다. general은 F3와 향후 기능이 공유한다.
자동 fallback·상시 예비 GPU·자체 감시를 두지 않는다. 시연 중 로컬 사용 시간은 운영자와 조정한다.

## 최초 준비

1. 기존 [계정 preflight](../README.md)·예산을 확인한다. 현재 작업 브랜치의 Backend 배포에는
   `serving_maintenance.sh`, `smoke_general.sh`, 새 renderer와 AI 코드가 모두 포함되어야 한다.
   기존 앱 revision에는 이 파일이 없을 수 있다. 새로운 배포가 검증되기 전 통합 전원 명령을 쓰지 않는다.
2. 새 Parameter Store 문서와 IAM 변경은 dev saved plan을 검토·승인해 적용한다.
   GPU 생성 기본값은 빈 집합이다. deep suspend 중이라면 plan에 edge/GPU false를 명시해 현재 중지를 보존한다.
   기존 RunPod 감시 제거 변경과 앱 Launch Template 변경도 같은 plan에 포함될 수 있으므로 전체를 검토한다.
3. F2 이미지는 기존 `Publish RunPod Image`, general 이미지는 `Publish General Serving Image`
   수동 workflow로 게시한다. 두 cloud에 동일한 **완성 이미지 digest**를 사용한다.
   `general.Dockerfile`의 공식 vLLM base digest는 게시할 프로젝트 이미지 digest와 다르다.
   F2 AWS local-model 경로·상태 조회를 사용하려면 이 변경을 포함한 F2 이미지가 필요하다.
4. RunPod Console에서 작업별 Secret·registry·Template을 처음 생성한다. F2 절차는
   [기존 문서](../runpod/README.md)를 유지한다. general은 workflow artifact의
   `template.json`과 `AI_GENERAL_API_KEY` Secret 참조를 사용한다. 두 키의 값은 승인된 채널로만 전달한다.
   Volume·Network Volume·SSH 없이 각각 HTTP 8001/8002와 8000만 노출한다.
5. 기존 등록 도구로 검증·등록한다. `image`, `template_id`, `registry_id`는 자신의 실제 값으로
   **로컬 명령 인자**에만 전달한다. 키는 인자·터미널 출력으로 전달하지 않는다.

```bash
just -f infra/justfile runpod-general-register-plan IMAGE_DIGEST TEMPLATE_ID REGISTRY_ID
just -f infra/justfile runpod-general-register IMAGE_DIGEST TEMPLATE_ID REGISTRY_ID
just -f infra/justfile ai-general-secret
just -f infra/justfile ai-ghcr-secret
```

키 명령은 private TTY로 입력받는다. `ai-general-secret`은 AWS AI provider Secret에 general 키를
추가한다. RunPod Console Secret에는 같은 값을 설정한다. `ai-ghcr-secret`은 AWS GPU 호스트용
읽기 전용 GHCR 사용자·token을 기존 Secret 컨테이너에 넣는다. F2·OpenAI 키를 삭제하지 않는다.

이미지 게시 전 Docker build 안에서 해당 이미지에 설치된 vLLM parser로 실제 시작 인자를
검증한다. 범용은 `python3`을 사용하며 F2의 vLLM 0.11과 범용의 고정 0.28 옵션을 섞지 않는다.
F2 기본 이미지의 선택적 HF transfer는 비활성화한다. RunPod의 `RUNNING`만으로 준비를
판단하지 말고 추론·fatal 로그를 확인한다. 컨테이너 재시작 중에도 Pod 과금이 이어질 수 있다.

## GPU 구성과 선택

`dev.tfvars`의 `gpu_profiles`에 검토한 Ubuntu 24.04 NVIDIA DLAMI, 완성 이미지 digest,
root EBS 크기를 넣는다. 형태는 [gpu.example.tfvars](gpu.example.tfvars)를 참조한다.
AMI의 Docker Compose·toolkit·AWS CLI·SSM을 첫 기동에서 검증해야 한다.
F2 기본 대상은 24GB, general은 48GB다. RunPod도 이에 맞는 명시 GPU ID를 선택한다.

```bash
# offline 상태에서만 저장한다. 이 단계는 GPU를 생성하거나 켜지 않는다.
just -f infra/justfile ai-configure f2 runpod 'NVIDIA RTX A5000' --release-id RELEASE_ID --bucket MODEL_BUCKET --apply
just -f infra/justfile ai-configure general runpod 'NVIDIA L40S' --apply
# 미평가 dev F2 release를 의도적으로 사용하는 경우에만 --allow-dev-release를 추가한다.
```

이미 active인 F2는 기존 선택을 덮어쓰지 않는다. 점검 중 기존 `runpod-delete`로 offline을
만든 뒤 첫 통합 선택을 등록한다. 이후에는 통합 전환 명령을 사용한다.

AWS 배포를 추가할 때는 다음 순서를 따른다.

```bash
just -f infra/justfile ai-capacity-plan general
just -f infra/justfile dev-show
# saved plan 검토·승인 후
just -f infra/justfile dev-apply
just -f infra/justfile ai-switch-plan general aws
just -f infra/justfile ai-switch general aws
```

`ai-capacity-plan`은 현재 AWS 인스턴스를 보존하고 대상 작업을 추가하는
`serving-capacity.auto.tfvars.json`을 로컬에 만든다. 일반·전환·deep plan이 모두 이 입력을 사용한다.
`dev.tfvars`나 `TF_VAR_*`에 `gpu_provisioned_workloads`를 중복 지정하지 않는다.
이 파일이 없으면 생성 대상 기본값은 빈 집합이므로 다른 운영자 PC에서는 먼저
`ai-capacity-plan`으로 입력을 복원하고 삭제 대상이 없는지 확인한다.
Terraform apply 순간부터 생성된 GPU는 준비 중이어도 과금된다. 생성을 나중으로 예약하지 않는다.

## 일상 운영과 전환

- `dev-status`: 앱·RDS, 선택 장소, 관리 GPU 상태, 모델 ready, 할당 EBS와 남은 디스크를 확인한다.
  정지 호스트·준비 실패·구형 F2 이미지의 남은 디스크는 `null`이며 0을 의미하지 않는다.
  상태 조회는 모델 목록을 확인하고, 추론 검증은 `ai-smoke f2|general`로 실행한다.
- `dev-start`: 선택 GPU 로딩·직접 추론 → endpoint → RDS·앱 복구 → 합성 smoke.
  앱 EC2가 교체되면 마지막 성공 CodeDeploy revision을 복구한다. 새 버전 배포를 대신하지 않는다.
- `dev-stop`: 배포·migration 충돌 확인 → API/Worker SIGTERM·최대 300초 drain → 모든 관리 GPU
  종료 시도 → 앱 ASG 0·RDS stop. 실패한 GPU는 `dev-status` 후 `dev-stop`으로 재시도한다.
- `ai-switch-plan f2|general aws|runpod`: 대상·선택·GPU 종류·비용 항목을 확인한다. GPU를 만들지 않는다.
- `ai-switch f2|general aws|runpod`: 대상 준비 → 직접 추론 → 앱 drain → 연결 → 앱 합성 smoke
  → 이전 AWS stop 또는 RunPod delete. F2의 주소 쌍과 general alias를 보존한다.

한 운영자만 명령을 실행한다. 배포·migration과 동시에 실행하지 않는다. 준비 실패나 사용자가
중단한 경우 후보 GPU가 남을 수 있으므로 `dev-status`에서 확인한다. 전체 중단을 허용하면
`dev-stop`으로 함께 정리한다. 전환 실패 후에는 앱을 점검 상태로 두고 `ai-switch`를 다시 실행해
선택한 대상으로 복구한다. `dev-start`는 마지막 성공 선택으로 복구한다. 자동으로 OpenAI로 가지 않는다.

`dev-deep-stop-plan → dev-deep-stop-show → 승인 → dev-deep-stop`은 일반 stop 후 edge와 AWS GPU
root/model/compile 캐시를 제거한다. `dev-deep-start-plan → dev-deep-start-show → 승인 → dev-deep-start`는
선택이 AWS인 작업만 재생성한다. DB·모델 release 정본·이미지·Template·등록·선택은 보존한다.
캐시 snapshot은 만들지 않는다. 이후 새 주소 등록과 캐시 재다운로드가 필요하다.

## Local 연결

개인 OpenAI 설정과 기존 모델은 그대로 둔다. F2는 기존 로컬 endpoint 설정을 사용할 수 있다.
GPU를 선택할 때만 아래 명령으로 **새 ignored 파일**을 만든다. 명령은 공유 dev 설정과 DB를
변경하지 않는다. 기존 파일은 덮어쓰지 않으므로 재연결 시 이전 개인 파일을 제거하거나 새 이름을 쓴다.

```bash
just -f infra/justfile ai-connect general ../backend/.env.gpu-general
just -f infra/justfile ai-connect f2 ../backend/.env.gpu-f2
```

just recipe는 `infra/`에서 실행된다. Backend용과 AI 단독용 파일은 각각 해당 모듈 안에 만든다.
키는 운영자가 승인한 값을 TTY에 입력한다. AWS는 터널 명령을 계속 열어 두고
general 18000, F2 18001·18002의 loopback만 사용한다. 공유 GPU가 꺼졌다면 운영자에게 시작을
요청한다. 권한 부족·포트 충돌·교체된 인스턴스는 명령을 실패시키며 재연결이 필요하다.
팀원에게 `team-gpu-tunnel`과 기존 AWS 로그인 권한만 제공한다. 운영자 Role을 공유하지 않는다.

```bash
# 별도 터미널, 저장소 루트에서 명시적으로 해당 프로세스에 주입
uv run --locked --project backend --env-file backend/.env.gpu-general python backend/src/manage.py smoke-general
uv run --locked --project ai --env-file ai/.env.gpu-general python -m brokerage_ai.smoke
```

Backend 실행에도 같은 `--env-file`을 명시한다. F2의 합성 전체 경로는 연결 파일을 주입해
Backend를 시작한 뒤 기존 `infra/deploy/scripts/smoke_f2.py`의 loopback API·합성 audio로 검사한다.
local DB에서 general을 실제 선택하려면 해당 로컬 사무소에 `activate-general-qwen`을 명시 실행한다.
local 프로세스가 SSM 터널로 공유 DB를 가리키는 설정은 사용하지 않는다.

## 최초 dev Qwen 활성화

GPU 연결과 두 capability smoke가 통과한 뒤 대상 사무소별로 실행한다.

```bash
just -f infra/justfile ai-smoke general
just -f infra/justfile ai-activate-general BROKERAGE_ID
```

앱을 drain한 상태에서 모델 설정만 변경한다. 대기·진행 작업이 있으면 중단한다.
업무 데이터·기존 profile·실행 이력을 보존하며 `dev-seed-f3`를 실행하지 않는다.
클라우드만 전환할 때는 이 명령을 다시 실행하지 않는다.

## 비용과 완료 기준

2026-09-07 AWS Price List 조회: 서울 Linux Shared On-Demand는 F2 $1.20208/h,
general $2.75652/h, 합계 $3.95860/h다. 4시간 동시 실행의 GPU 비용은 약 $15.83이며
EBS·public IPv4·기존 앱·세금·환율은 별도다. 실시간 GPU 용량을 보장하는 견적이 아니다.

| 상태 | AWS GPU | RunPod |
|---|---|---|
| 실행·무요청 | GPU + EBS + 자동 public IPv4 | GPU + container disk |
| 일반 stop | EBS 보존·과금 | Pod 삭제. 별도 Volume이 남았다면 과금 |
| deep-stop | GPU와 캐시 EBS 제거 | Pod 삭제. 독립 Network Volume은 별도 확인 |

AWS 누적 30만원·기존 종료일, RunPod 2개월 $300의 기존 한도를 바꾸지 않는다.
생성 직전 잔여 예산·예상 사용 시간·서울 AZ·할당량·RunPod 가격을 확인한다.
[EBS 요금](https://aws.amazon.com/ebs/pricing/),
[EC2 stop/start](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/how-ec2-instance-stop-start-works.html),
[RunPod 요금](https://docs.runpod.io/pods/pricing)을 기준으로 잔존 비용을 확인한다.
[validation.md](validation.md)의 실제 환경 행을 모두 통과해야 운영 완료다.

## 비교 검토와 게시 이미지 재사용

[검토 재현 절차](comparison-reproduction.md)에서 저장된 근거 검사와 원본 요약 재생성,
동일 조건 재평가 명령을 확인한다. [게시 이미지 catalog](published-images.json)는 태그·digest별
AWQ·BnB·공식 FP8의 실제 GPU 검증 범위를 구분한다. 최신 이미지를 모든 모델의 검증 완료로 간주하지 않는다.
