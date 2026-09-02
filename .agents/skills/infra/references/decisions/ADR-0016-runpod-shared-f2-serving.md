---
status: 결정
updated: 2026-09-01
---

# ADR-0016: RunPod 공유 F2 서빙 운영

- 상태: 대체됨 ([ADR-0017](ADR-0017-runpod-ephemeral-sllm-serving.md))
- 결정일: 2026-09-01
- 대체 범위: [ADR-0002](ADR-0002-dev-demo-aws-runpod-architecture.md)의 개발자별 Pod
  생성·삭제와 조건부 custom image 결정
- 해소 질문: `INFRA-OQ-009`

## 맥락

현재 Qwen과 Whisper 서빙은 Pod마다 vLLM을 수동 설치하고 `uv` archive와 tmux로 복구한다.
실행법이 개인 PC에만 있어 Pod 중지·마이그레이션 후 재현성과 인수인계가 보장되지 않는다.
F2 개발 서빙은 기존 OpenAI-compatible 동기 API와 비용 조건에 맞는 RunPod를 유지한다.

## 결정

### 소유 경계

- Infra는 공유 dev용 private image, dependency lock, Team Template 명세, runtime, lifecycle 도구와
  runbook을 소유한다.
- 학습 Pod, QLoRA 설정, 개인 실험, GPU 종류와 데이터센터 선택은 Infra 통제 범위가 아니다.
- 공유 Pod 이름은 `skn30-f2-serving-dev`이며 Secure Cloud, GPU 1개, VRAM 24 GiB 이상을 기본으로
  한다. Community Cloud는 합성·비식별 데이터임을 확인한 경우에만 사용한다.
- Team Template은 `skn30-f2-serving-v<version>`의 불변 버전으로 관리한다. image digest,
  `22/tcp`, `8001/http`, `8002/http`, 30 GiB container disk, 40 GiB Volume Disk,
  `/workspace` mount, Secret 참조와 기본 모델값을 소유한다.

### 실행환경

- 검증된 `runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404` amd64 digest와 정확히 잠근 vLLM
  audio 의존성으로 private GHCR image를 만든다. Template은 tag가 아니라 digest를 참조한다.
- Container는 Qwen과 Whisper vLLM, 각 서비스의 인증 proxy를 자동 시작한다. 하나라도 종료되면
  container를 실패시키며 로그는 stdout/stderr로만 보낸다. tmux와 `PYTHONPATH` 복구는 운영
  경로가 아니다.
- vLLM `0.11.0`은 현재 base와 호환되지만 API 인증 우회와 Completions 취약점의 영향 범위에
  있다. vLLM은 loopback에만 bind하고 proxy가 서비스별 key와 method·path allowlist를 검증한다.
  base와 patched vLLM을 함께 검증하기 전에는 이 경계를 제거하지 않는다.
- 서로 다른 두 API key를 RunPod Secret과 AWS Secrets Manager에 주입한다. image와 Git에는
  model weight, LoRA adapter, HF token, API key를 넣지 않는다. model cache는
  `/workspace/.cache/huggingface`에 둔다.
- Template의 Qwen·Whisper는 고정 commit revision을 기본값으로 사용한다. 검토된 model override는
  Hugging Face `owner/model` ID와 40자리 commit revision을 함께 요구한다. Qwen LoRA는
  `/workspace/adapters/<alias>`에 수동 전달한 adapter만 선택적으로 사용한다.

관련 vLLM 근거는 공식 [model loading advisory](https://github.com/vllm-project/vllm/security/advisories/GHSA-2pc9-4j83-qjmr),
[API 인증 advisory](https://github.com/vllm-project/vllm/security/advisories/GHSA-94f4-hr76-p5j6),
[Completions advisory](https://github.com/vllm-project/vllm/security/advisories/GHSA-mrw7-hf4f-83pf)를
따른다.

### lifecycle과 endpoint

- 저빈도 Template·Pod 생성과 교체는 Team Console checklist로 수행한다. `manage_runpod.py`는
  `doctor`, `pod-start`, `pod-status`, `pod-stop`만 제공하며 변경은 기본 dry-run이다.
- 공유 Pod는 유지하고 미사용 시 수동 중지한다. 자동 중지는 없으며 시작 작업자가 중지를 책임진다.
  중지 중에도 Volume Disk 비용은 발생한다.
- stop/start로 Pod ID가 유지되면 endpoint를 변경하지 않는다. 교체 시 새 Pod smoke 후 SSM
  `AI_VLLM_ENDPOINT_SET` JSON 한 값으로 두 URL을 함께 변경하고, 기존 배포 script로 같은 Backend
  image의 API·Worker만 재생성한다.
- 실패 시 백업한 JSON을 복원하고 같은 refresh를 다시 실행한다. 자동 교체 transaction, 자동
  rollback, GraphQL Pod 생성, Terraform RunPod provider와 별도 load balancer는 도입하지 않는다.
- 일반 lifecycle에 Pod 삭제를 포함하지 않는다. 프로젝트 종료 시 정확한 ID와 Volume 비용을
  확인한 별도 폐기 절차를 따른다.

## 결과

공유 서빙의 재현성·인증·비용 책임은 Git에서 검토할 수 있고 Template은 GPU와 실험 모델을 강제하지
않는다. 저빈도 제어면 자동화 대신 Console checklist와 수동 rollback을 사용해 운영 코드의 유지보수
부담을 줄인다. 최초 image 게시, Team Template·Pod 생성과 24 GiB GPU stop/start·smoke는 외부 적용
검증으로 남는다.
