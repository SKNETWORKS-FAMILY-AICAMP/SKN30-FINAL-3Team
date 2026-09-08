# BASE_IMAGE is a reviewed official vLLM image pinned by sha256.
ARG BASE_IMAGE=vllm/vllm-openai@sha256:2286e8533ca8b6bc777594bae30524f1426ba46ca21797524e06df6a94b06635
FROM ${BASE_IMAGE}
ENV HF_HOME=/workspace/huggingface VLLM_NO_USAGE_STATS=1 PYTHONUNBUFFERED=1
COPY general_runtime.py /opt/general/general_runtime.py
COPY general_middleware.py /opt/general/general_middleware.py
COPY model_profiles.py model-profiles.json /opt/general/
COPY validate_cli.py /opt/general/validate_cli.py
ENTRYPOINT []
COPY runtime-requirements.txt /opt/general/runtime-requirements.txt
RUN python3 -m pip install --no-cache-dir --no-deps --require-hashes -r /opt/general/runtime-requirements.txt
RUN python3 -c "import vllm, bitsandbytes; import py_compile; py_compile.compile('/opt/general/general_runtime.py', doraise=True)"
RUN python3 /opt/general/validate_cli.py
CMD ["python3", "/opt/general/general_runtime.py"]
