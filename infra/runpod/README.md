# RunPod F2 dev 서빙

공유 dev 서빙은 `sllm`(상담분석)과 `stt` 두 작업 이름을 사용한다. 기반 모델 ID는 학습자가 만든
SLLM release manifest와 Template의 STT 설정에서 관리하며 애플리케이션에 노출하지 않는다.

## 소유 경계

- 학습 담당자: 로컬에서 자유롭게 학습·평가하고 `package_release.py`로 만든 bundle 하나를 전달한다.
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

Infra 담당자가 전달받은 파일을 먼저 검사하고 private S3에 게시한다.

```bash
just -f infra/justfile sllm-artifact-inspect /handoff/consultation-v1.tar.gz
just -f infra/justfile sllm-artifact-publish /handoff/consultation-v1.tar.gz
```

사용 가능한 GPU ID를 확인한 후 Secure Cloud Pod를 생성한다. S3 presigned URL은 1시간만 유효하고
출력에 노출되지 않는다. 두 `/v1/models`가 준비된 뒤에만 SSM endpoint가 `active`로 바뀌고 기존
Backend image의 API·Worker만 재생성된다.

RunPod Console에서 사용할 정확한 Secure Cloud GPU ID를 확인한 뒤 생성한다.

```bash
just -f infra/justfile runpod-create consultation-v1 "NVIDIA GeForce RTX 4090"
just -f infra/justfile runpod-status
just -f infra/justfile runpod-reconcile
just -f infra/justfile runpod-smoke
```

작업 종료 후 출력된 정확한 Pod ID로 삭제한다. 먼저 endpoint를 `offline`으로 갱신해 F2 요청이
명시적인 503을 반환하게 한 뒤 Pod를 영구 삭제한다.

```bash
just -f infra/justfile runpod-delete <pod-id>
```

삭제해도 private S3 release는 남는다. 다음 실행은 새 Pod를 만들고 기반 모델·STT weight를 다시
내려받으므로 시작 시간이 발생하지만, 유휴 GPU·Volume 비용은 발생하지 않는다. RunPod 콘솔 로그는
장애 확인용 보조 경로이며 tmux, SSH, `PYTHONPATH` 복구는 운영 절차가 아니다.

## 실패 처리

- 생성 중 모델 health 또는 AWS refresh가 실패하면 endpoint를 이전 값으로 복원하고 새 Pod를
  삭제한다.
- 삭제 전 AWS refresh가 실패하면 이전 active endpoint를 복원하고 Pod는 삭제하지 않는다.
- 동일 이름 Pod가 이미 있거나 2개 이상이면 도구는 추측하지 않고 중단한다.
- S3 release ID는 덮어쓸 수 없다. 수정된 adapter는 새 release ID로 다시 게시한다.

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
