FROM runpod/pytorch@sha256:4d1721e62b56d345c83b4fd6090664be6daf9312caab5b2e76f23d8231941851

LABEL org.opencontainers.image.source="https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN30-FINAL-3Team" \
      org.opencontainers.image.description="SKN30 SLLM and STT vLLM serving runtime" \
      io.skn30.runpod.base.index-digest="sha256:0a360022e8de4375af99430f84e8b38951acc397252163a37ceac7204d01be35" \
      io.skn30.runpod.base.config-digest="sha256:02b731f844d2fbc4dd0de87253081363864327c7931b1ae2b5daa60abc600c51" \
      io.skn30.runpod.base.source-tag="runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404"

ENV DEBIAN_FRONTEND=noninteractive \
    HF_HOME=/workspace/.cache/huggingface \
    HUGGINGFACE_HUB_CACHE=/workspace/.cache/huggingface/hub \
    PYTHONUNBUFFERED=1 \
    VLLM_NO_USAGE_STATS=1

WORKDIR /opt/f2-runtime

COPY pyproject.toml requirements.lock ./

RUN uv pip install \
      --system \
      --break-system-packages \
      --require-hashes \
      --no-cache \
      --requirement requirements.lock \
    && uv pip check --system \
    && python -c "import sys; assert sys.version_info[:2] == (3, 12)" \
    && python -c "import aiohttp, multidict, torch; assert torch.__version__.split('+')[0] == '2.8.0'; assert torch.version.cuda == '12.8'" \
    && python -c "from vllm.entrypoints.cli.main import main; assert callable(main)" \
    && vllm --version

COPY scripts/ ./scripts/

RUN chmod 0755 scripts/artifact_bootstrap.py scripts/supervisor.py scripts/auth_proxy.py scripts/healthcheck.py \
    && python -c "import sys; sys.path.insert(0, '/opt/f2-runtime/scripts'); import artifact_bootstrap, auth_proxy, healthcheck, supervisor" \
    && mkdir -p /workspace/.cache/huggingface \
    && chmod 0700 /workspace/.cache/huggingface

HEALTHCHECK --interval=30s --timeout=15s --start-period=30m --retries=3 \
  CMD ["python", "/opt/f2-runtime/scripts/healthcheck.py"]

CMD ["python", "/opt/f2-runtime/scripts/supervisor.py"]
