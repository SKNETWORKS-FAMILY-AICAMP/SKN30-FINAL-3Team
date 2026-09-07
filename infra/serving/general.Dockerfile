# BASE_IMAGE is a reviewed official vLLM image pinned by sha256.
ARG BASE_IMAGE=vllm/vllm-openai@sha256:770fe65b2c73ee74a5c42165cf3433de4048cc2cd9c57a937ca4e35aba5aa87b
FROM ${BASE_IMAGE}
ENV HF_HOME=/workspace/huggingface VLLM_NO_USAGE_STATS=1 PYTHONUNBUFFERED=1
COPY general_runtime.py /opt/general/general_runtime.py
COPY general_middleware.py /opt/general/general_middleware.py
COPY validate_cli.py /opt/general/validate_cli.py
ENTRYPOINT []
RUN python3 -c "import vllm, bitsandbytes; import py_compile; py_compile.compile('/opt/general/general_runtime.py', doraise=True)"
RUN python3 /opt/general/validate_cli.py
CMD ["python3", "/opt/general/general_runtime.py"]
