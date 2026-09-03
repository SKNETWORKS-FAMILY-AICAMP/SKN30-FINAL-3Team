# RunPod F2 dev 서빙

공유 dev 서빙은 `sllm`(상담분석)과 `stt` 두 작업 이름을 사용한다. 기반 모델 ID는 학습자가 만든
SLLM release manifest와 Template의 STT 설정에서 관리하며 애플리케이션에 노출하지 않는다.

## 소유 경계

- 학습 담당자: 로컬에서 자유롭게 학습·평가하고 `package_release.py`로 만든 v2 metadata bundle
  하나를 전달한다. LoRA bundle에만 adapter가 있으며 base-only도 tar bundle 자체는 사용한다.
  AWS, RunPod, `infra/` 실행 권한은 필요하지 않다.
- Infra 담당자: bundle 검증, private S3 불변 게시, RunPod Pod 생성·삭제와 dev endpoint 전환을
  담당한다.
- S3 `releases/sllm/<release-id>/`가 전달받은 모델의 정본이다. Pod disk는 cache일 뿐 보존 대상이
  아니며 Volume Disk와 Network Volume을 사용하지 않는다.

## 최초 1회 준비

Terraform saved plan을 먼저 적용해 Secret 컨테이너와 SSM 제어 문서를 만든다. 이 plan에는 Secret
version이나 평문 입력이 없어야 하고 기존 AI·Discord version의 state 분리는 `destroy=false`여야 한다.

GHCR workflow는 Ruff와 runtime/proxy 테스트가 성공해야 image를 게시한다. summary의 정확한
`ghcr.io/...@sha256:...`를 변경 없는 계획에 먼저 전달한 뒤 확인이 붙은 bootstrap을 한 번 실행한다.
기존 generation과 다른 digest는 endpoint가 offline이고 공유 Pod가 없을 때만 새 immutable Template
generation을 만들 수 있다.

```bash
just -f infra/justfile runpod-bootstrap-plan ghcr.io/.../f2-serving@sha256:<64-hex>
just -f infra/justfile runpod-bootstrap ghcr.io/.../f2-serving@sha256:<64-hex>
just -f infra/justfile runpod-doctor
```

도구는 AWS 계정·리전·컨테이너를 확인하고 누락값만 TTY 비표시로 받는다. F2 key 두 개는 내부
생성한다. RunPod Secret, GHCR registry auth와 private immutable Template을 만들고 검증한 뒤에만
SSM 제어 상태를 `ready`로 바꾼다. 실패 시 `provisioning`이 남으므로 같은 digest로 재실행한다.
중복 이름이나 설정 불일치는 덮어쓰지 않는다. RunPod API key와 GHCR PAT의 최초 발급만 각 Console에서
수행하며 개인 `.env`, key 명령 인자나 영구 `runpodctl` 설정은 사용하지 않는다.

비밀값 존재와 회전은 다음 명령으로 관리한다. 값·hash는 출력하지 않는다. `f2`, `ghcr`은 endpoint가
offline이고 공유 Pod가 없을 때만 허용한다.

```bash
just -f infra/justfile secret-status
just -f infra/justfile secret-rotate openai
just -f infra/justfile secret-rotate f2
just -f infra/justfile secret-rotate ghcr
just -f infra/justfile secret-rotate delivery-discord
just -f infra/justfile secret-rotate alarm-discord
just -f infra/justfile secret-rotate runpod-operator
just -f infra/justfile secret-rotate runpod-monitor
```

## 매 릴리스 운영

먼저 Terraform 적용 후 Secret 컨테이너·SSM 문서가 있고 control이 `ready`인지, 공유 Pod가 없는지
값 노출 없이 확인한다.

```bash
just -f infra/justfile secret-status
just -f infra/justfile runpod-doctor
just -f infra/justfile runpod-status
```

Infra 담당자가 전달받은 파일을 먼저 검사하고 private S3에 게시한다. 새 package는
`release.json:v2`만 생성하며 `release_mode=lora|base`, 기반 모델 ID·40자리 commit, dataset
release/checksum, 원본 전체 평가 요약 checksum과 승인 연결을 검증한다. LoRA에는 adapter·training이 필수이고 base에는 둘 다
`null`이다. 검사기와 Pod runtime은 기존 v1 LoRA bundle도 계속 읽는다.

```bash
just -f infra/justfile sllm-artifact-inspect /handoff/consultation-v2.tar.gz
just -f infra/justfile sllm-artifact-publish /handoff/consultation-v2.tar.gz
```

v2의 `bundle.tar.gz`와 `release.json`은 자기 SHA-256과 상대 객체 SHA-256 metadata를 양방향으로
결속한다. 같은 release ID를 재실행하면 기존 객체 checksum이 완전히 같은 경우에만 누락 객체를
이어 게시하고, 다른 내용이면 불변 충돌로 중단한다. 원본 데이터·전사·예측 원문·checkpoint·로컬
경로·비밀값은 bundle에 넣지 않는다.

사용 가능한 GPU ID를 확인한 후 먼저 비용 없는 plan을 실행한다. plan은 control ready, 공유 Pod
부재, S3 두 객체와 cross-hash, 실행 중인 Backend EC2와 API·Worker health를 확인하며 presigned URL과
Pod를 만들지 않는다.

RunPod Console에서 사용할 정확한 Secure Cloud GPU ID를 확인한 뒤 생성한다.

```bash
just -f infra/justfile runpod-create-plan consultation-v2 "NVIDIA GeForce RTX 4090"
just -f infra/justfile runpod-create consultation-v2 "NVIDIA GeForce RTX 4090"
just -f infra/justfile runpod-status
just -f infra/justfile runpod-reconcile
just -f infra/justfile runpod-smoke
```

평가 전 기동·통합 확인은 `release_stage=dev`이고 ID가 `dev-`로 시작하는 bundle만 허용한다.
`dev` bundle은 평가·승인 파일 대신 `not-evaluated` 상태를 명시하므로 품질 검증이나 정식 승격으로
간주하지 않는다. 일반 create는 이를 거부하며 아래 전용 명령만 shared dev endpoint를 변경할 수 있다.

```bash
just -f infra/justfile sllm-artifact-inspect /handoff/dev-<release>.tar.gz
just -f infra/justfile sllm-artifact-publish /handoff/dev-<release>.tar.gz
just -f infra/justfile runpod-create-dev-plan dev-<release> "NVIDIA GeForce RTX 4090"
just -f infra/justfile runpod-create-dev dev-<release> "NVIDIA GeForce RTX 4090"
```

팀에 미평가 모델 사용 중임을 알리고 확인이 끝나면 verified release와 동일하게 정확한 Pod ID로
삭제한 뒤 `runpod-offline-smoke`를 실행한다.

create만 GPU 비용을 발생시킨다. S3 presigned URL은 1시간만 유효하고 출력에 노출되지 않는다. LoRA는
`--enable-lora --lora-modules sllm=<adapter>`로, base는 LoRA 옵션 없이 기반 모델을 `sllm` 이름으로
기동한다. 두 `/v1/models` 응답에 각각 정확한 `sllm`, `stt` ID가 확인된 뒤에만 SSM endpoint가
`active`로 바뀌고 기존 Backend image의 API·Worker만 재생성된다.

기반 가중치는 bundle이나 GHCR image에 넣지 않고 Pod 시작 시 공개 Hugging Face 저장소의 불변
commit에서 받는다. Template과 자식 프로세스는 HF token 계열 환경변수를 거부·제거하므로
private/gated 모델은 지원하지 않으며 health 전에 실패해 정리된다. Qwen ID는 명령 형식 예시일 뿐
승인된 운영 모델이 아니다.

작업 종료 후 출력된 정확한 Pod ID로 삭제한다. 먼저 endpoint를 `offline`으로 갱신해 F2 요청이
명시적인 503을 반환하게 한 뒤 Pod를 영구 삭제한다.

```bash
just -f infra/justfile runpod-delete <pod-id>
just -f infra/justfile runpod-offline-smoke
```

삭제해도 private S3 release는 남는다. 다음 실행은 새 Pod를 만들고 기반 모델·STT weight를 다시
내려받으므로 시작 시간이 발생하지만, 유휴 GPU·Volume 비용은 발생하지 않는다. RunPod 콘솔 로그는
장애 확인용 보조 경로이며 tmux, SSH, `PYTHONPATH` 복구는 운영 절차가 아니다.

## 실패 처리

- 생성 중 모델 health 또는 AWS refresh가 실패하면 endpoint를 이전 값으로 복원하고 새 Pod를
  삭제한다.
- active F2 smoke가 실패해도 같은 rollback을 수행한다.
- 삭제 전 AWS refresh가 실패하면 이전 active endpoint를 복원하고 Pod는 삭제하지 않는다.
- rollback refresh 또는 자동 Pod 삭제까지 실패하면 완료 이벤트를 내지 않고
  `runpod-reconcile-required`와 안전한 상태 확인·수동 조정 순서를 출력한다. 이 경우 출력된
  `runpod-status`와 `runpod-reconcile`부터 실행하고 SSM endpoint 의도값과 Backend refresh를 확인한다.
- 동일 이름 Pod가 이미 있거나 2개 이상이면 도구는 추측하지 않고 중단한다.
- S3 release ID는 덮어쓸 수 없다. checksum이 다른 adapter나 metadata는 새 release ID로 게시한다.

## 관측과 수동 조정

EventBridge가 기본 30분마다 읽기 전용 Lambda를 실행한다. RunPod API, 공유 Pod, endpoint 일치,
인증된 SLLM/STT health, 연속 실행 시간·시간당 비용과 heartbeat를 기존 프로젝트 namespace에 기록한다.
기본 8시간 실행, offline orphan 60분, API·health 연속 실패와 endpoint 불일치는 기존 Alarm
SNS·Discord로 전달한다. 감시는 endpoint를 쓰거나 Pod를 생성·삭제하지 않는다.

알림을 받으면 `runpod-status → runpod-reconcile → runpod-smoke → Alarm OK` 순서로 확인한다.
`runpod-reconcile`은 기본 dry-run이다. active endpoint의 Pod가 실제로 없을 때만
`runpod-reconcile-apply`로 offline 전환과 API·Worker refresh를 확인할 수 있다. endpoint와 다른 Pod,
복수 Pod, health 실패나 RunPod API 장애는 상태를 바꾸지 않는다. offline orphan은 출력된 정확한
`runpod-delete <pod-id>` 명령을 별도로 검토한다.

## 사용자 실검증 순서

현재 `dev-f2-handwritten-v05-qwen3-4b-full-v1`은 private S3에 게시됐고 RunPod Pod와 이번 Terraform
변경은 미적용이다. 운영자가 비용과 변경 내용을 확인한 뒤 다음 순서로 검증한다. presigned URL·token·
응답 원문은 어떤 출력에도 복사하지 않는다.

1. 필요한 Terraform 변경이 있으면 `plan → show → 승인 → apply`를 먼저 완료한다.
2. 변경된 runtime의 새 GHCR digest를 build하고 `runpod-bootstrap-plan → runpod-bootstrap`을 실행한다.
3. API·Worker에 `preflight_runpod_create.sh`와 offline smoke가 포함된 현재 Backend revision을 배포한다.
4. 새 release는 mode와 stage에 맞춰 package하고 `sllm-artifact-inspect → publish`한다. 현재 dev LoRA
   release의 이 단계는 완료됐다.
5. 현재 dev release는 `runpod-create-dev-plan`으로 S3·control·공유 Pod·Backend target을 확인한다.
6. GPU 비용을 확인한 뒤 `runpod-create-dev`를 실행하고 `runpod-status → runpod-smoke`를 확인한다.
7. 출력된 정확한 Pod ID로 `runpod-delete`를 실행한다.
8. `runpod-offline-smoke`가 503 `F2_UNAVAILABLE`을 확인하는지 검증한다.

제한된 sandbox 밖의 정상 로컬 환경에서 AI 전체 212개 테스트와 두 Terraform root `validate`가
통과했다. 실제 apply 전에는 저장한 plan의 변경 대상을 별도로 검토한다.
