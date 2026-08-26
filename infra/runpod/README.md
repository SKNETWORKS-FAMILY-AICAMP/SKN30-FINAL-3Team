# RunPod F2 로컬 연동 runbook

이 절차는 로컬 Frontend·Backend에서 개발자별 RunPod Pod의 Qwen3-4B와 Whisper를 호출하는 1차
검증용이다. 합성·비식별 음성만 사용하며 API key, Pod 주소와 SSH 개인키는 저장소에 기록하지 않는다.

## Pod 준비

24 GiB 이상 NVIDIA GPU Pod와 영속 `/workspace` volume을 사용한다. Pod Web Terminal에서 다음 환경을
한 번 준비한다.

```bash
cd /workspace
uv venv --python 3.12 --seed f2-venv
source /workspace/f2-venv/bin/activate
uv pip install "vllm[audio]" --torch-backend=auto
```

아래 명령은 두 개의 Web Terminal 또는 tmux session에서 각각 실행한다. 두 서비스 모두 Pod의
loopback에만 bind하고 SSH tunnel로만 접근하므로 HTTP port를 공개하지 않는다.

```bash
source /workspace/f2-venv/bin/activate
CUDA_VISIBLE_DEVICES=0 vllm serve Qwen/Qwen3-4B \
  --host 127.0.0.1 \
  --port 8001 \
  --dtype bfloat16 \
  --max-model-len 4096 \
  --gpu-memory-utilization 0.65 \
  --default-chat-template-kwargs '{"enable_thinking": false}'
```

```bash
source /workspace/f2-venv/bin/activate
VLLM_MAX_AUDIO_CLIP_FILESIZE_MB=25 CUDA_VISIBLE_DEVICES=0 \
vllm serve openai/whisper-large-v3-turbo \
  --host 127.0.0.1 \
  --port 8002 \
  --gpu-memory-utilization 0.20
```

두 서버가 동시에 메모리 부족으로 시작하지 못하면 더 큰 GPU를 선택하거나 Qwen의
`--gpu-memory-utilization`을 먼저 낮춘다. 두 모델의 물리적 Pod 통합은 고정 결정이 아니므로 실제 GPU와
상담 음성 길이로 지연·VRAM을 측정한다.

## Mac SSH tunnel

RunPod HTTP port를 공개하지 않고 Pod별 SSH key로 두 내부 포트를 한 번에 전달한다.

```bash
ssh -N -o IdentitiesOnly=yes \
  -i ~/.ssh/개인_Pod_전용키 \
  -L 8001:127.0.0.1:8001 \
  -L 8002:127.0.0.1:8002 \
  root@POD_IP -p POD_SSH_PORT
```

공용 RunPod 계정 Settings에는 개인키를 등록하지 않는다. 공개키는 해당 Pod의
`/root/.ssh/authorized_keys`에만 추가하고 Pod 삭제 시 함께 폐기한다.

별도 Terminal에서 모델 목록을 확인한다.

```bash
curl http://127.0.0.1:8001/v1/models \
  --fail
curl http://127.0.0.1:8002/v1/models --fail
```

## 애플리케이션 설정과 실행

공개 설정은 `ai/.env.local`의 Qwen `8001`, Whisper `8002` endpoint와 모델명을 사용한다.
`backend/.env.local`의 `F2_ENABLED=true` 상태에서 기존 로컬 DB·개발 세션을 준비한 뒤 Backend와
Frontend를 각각 실행한다.

```bash
cd backend
uv run uvicorn main:app --reload
```

```bash
cd frontend
npm run dev
```

F1 상세에서 `음성메모 입력`을 열고 주의 문구 확인, WAV·MP3·M4A 선택, `분석 시작` 순서로 실행한다.
성공 시 현재값과 Qwen 제안값이 검토표에 나타나며 `선택 항목 반영`은 부모 상세 draft만 바꾸고 DB에
저장하지 않는다.

RunPod HTTP proxy로 전환할 때는 서비스 host를 `0.0.0.0`으로 바꾸고 Pod의 HTTP port를 노출해야 한다.
그 경로는 공개 접근이므로 vLLM API key와 HTTPS proxy URL을 반드시 함께 설정하며, 동기 분석이 proxy의
연결 제한을 넘을 수 있어 현재 1차 로컬 SSH tunnel 검증에는 사용하지 않는다.
