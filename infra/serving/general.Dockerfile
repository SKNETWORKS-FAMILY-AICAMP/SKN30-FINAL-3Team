# BASE_IMAGE is a reviewed official vLLM image pinned by sha256.
ARG BASE_IMAGE=vllm/vllm-openai@sha256:770fe65b2c73ee74a5c42165cf3433de4048cc2cd9c57a937ca4e35aba5aa87b
FROM ${BASE_IMAGE}
ENV HF_HOME=/workspace/huggingface VLLM_NO_USAGE_STATS=1 PYTHONUNBUFFERED=1
COPY general_runtime.py /opt/general/general_runtime.py
COPY general_middleware.py /opt/general/general_middleware.py
ENTRYPOINT []
CMD ["python", "/opt/general/general_runtime.py"]
