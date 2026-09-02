# 폐기 예정: 이전 Pod uv archive 복구

> 이 문서는 `runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404`에서 수동 설치하던 **이전 Pod만**
> 진단하기 위한 임시 자료다. 새 공유 Pod에는 사용하지 않는다. 새 image·Template의 stop/start 인수가
> 끝나면 이 파일을 삭제한다.

적용 조건은 Pod 중지 또는 마이그레이션 뒤 `/workspace`는 남았지만 다음 오류로 기존 vLLM이 실행되지
않는 경우다.

```text
ModuleNotFoundError: No module named 'vllm.entrypoints'
```

이 절차는 영속 `/workspace`의 기존 uv archive와 Hugging Face cache를 임시 연결한다. 재현 가능한
설치나 운영 복구 수단이 아니며 새 package를 내려받지 않는다.

## 1. 보존 데이터 확인

```bash
ls -ld /workspace/f2-venv
ls /workspace/.cache/huggingface/hub
find /workspace/.cache/uv/archive-v0 -type d -path '*/vllm/entrypoints' -print
```

다음 model cache와 하나 이상의 `vllm/entrypoints`가 없으면 중단한다.

```text
models--Qwen--Qwen3-4B
models--openai--whisper-large-v3-turbo
```

## 2. 기존 uv archive 연결

새 Web Terminal마다 실행한다.

```bash
export VLLM_CACHE_ROOT="$(
  find /workspace/.cache/uv/archive-v0 \
    -type d \
    -path '*/vllm/entrypoints' \
    -print \
    -quit \
  | sed 's#/vllm/entrypoints$##'
)"
test -n "$VLLM_CACHE_ROOT"
```

재설치 없이 import와 CLI를 확인한다.

```bash
PYTHONPATH="$VLLM_CACHE_ROOT" /workspace/f2-venv/bin/python \
  -c "from vllm.entrypoints.cli.main import main; print('legacy vLLM archive found')"
PYTHONPATH="$VLLM_CACHE_ROOT" /workspace/f2-venv/bin/vllm --version
```

## 3. 이전 tmux session 정리

```bash
tmux ls
tmux kill-session -t qwen 2>/dev/null || true
tmux kill-session -t stt 2>/dev/null || true
```

## 4. Loopback 진단 실행

이전 Pod의 API key 없는 서비스가 인터넷에 공개되지 않도록 loopback에만 bind한다.

```bash
tmux new-session -d -s qwen
tmux send-keys -t qwen \
  "export PYTHONPATH='$VLLM_CACHE_ROOT'; export HF_HOME=/workspace/.cache/huggingface; CUDA_VISIBLE_DEVICES=0 /workspace/f2-venv/bin/vllm serve Qwen/Qwen3-4B --host 127.0.0.1 --port 8001 --dtype bfloat16 --max-model-len 4096 --gpu-memory-utilization 0.65 --default-chat-template-kwargs '{\"enable_thinking\":false}'" \
  Enter
tmux capture-pane -pt qwen -S -50
```

```bash
tmux new-session -d -s stt
tmux send-keys -t stt \
  "export PYTHONPATH='$VLLM_CACHE_ROOT'; export HF_HOME=/workspace/.cache/huggingface; export VLLM_MAX_AUDIO_CLIP_FILESIZE_MB=25; CUDA_VISIBLE_DEVICES=0 /workspace/f2-venv/bin/vllm serve openai/whisper-large-v3-turbo --host 127.0.0.1 --port 8002 --gpu-memory-utilization 0.20" \
  Enter
tmux capture-pane -pt stt -S -50
```

`Application startup complete` 또는 Uvicorn 실행 메시지를 확인한다.

```bash
tmux ls
nvidia-smi
curl --fail http://127.0.0.1:8001/v1/models
curl --fail http://127.0.0.1:8002/v1/models
```

로컬에서 진단해야 하면 개인 key와 현재 `runpodctl ssh info POD_ID`가 반환한 IP·port로 SSH tunnel을
연다.

```bash
ssh -N -o IdentitiesOnly=yes \
  -i ~/.ssh/개인_RunPod_key \
  -L 8001:127.0.0.1:8001 \
  -L 8002:127.0.0.1:8002 \
  root@POD_IP -p POD_SSH_PORT
```

이 legacy 절차에서 `0.0.0.0` 또는 RunPod HTTP proxy로 바꾸지 않는다. vLLM 자체 인증은 모든
경로를 보호하지 않으며 새 runtime의 all-path 인증 proxy가 이 이전 Pod에는 없다.

## 종료

- 진단이 끝나면 tmux session을 종료하고 Pod를 중지한다.
- `/workspace` cache와 Volume 비용은 Pod 중지 중에도 남는다.
- archive를 새 image에 복사하거나 `PYTHONPATH` 값을 Template에 넣지 않는다.
- 새 runtime 검증 뒤 필요한 합성 artifact만 반출하고 이전 Pod·Volume과 이 문서를 폐기한다.
