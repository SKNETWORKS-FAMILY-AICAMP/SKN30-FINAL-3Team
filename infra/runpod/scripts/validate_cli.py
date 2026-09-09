"""Check generated commands against the installed vLLM parser during image build.

No GPU initialization, model download, credential loading, or server startup.
"""

from unittest.mock import patch

from supervisor import RuntimeConfig, build_commands


def main() -> None:
    from vllm.entrypoints.openai.cli_args import make_arg_parser
    from vllm.platforms import current_platform
    from vllm.utils import FlexibleArgumentParser

    # The CUDA image is built on a host without GPU drivers. This only supplies
    # a device type while constructing parser defaults; no engine is created.
    with patch.object(current_platform, "device_type", "cpu"):
        parser = make_arg_parser(FlexibleArgumentParser())
    for mode in ("base", "lora"):
        config = RuntimeConfig(
            release_mode=mode,
            sllm_model_id="Qwen/Qwen3-4B",
            sllm_model_revision="a" * 40,
            sllm_adapter_path="/opt/f2-models/adapter" if mode == "lora" else None,
            stt_model_id="openai/whisper-large-v3-turbo",
            stt_model_revision="b" * 40,
            sllm_max_model_len=4096,
            sllm_gpu_memory_utilization=0.65,
            stt_gpu_memory_utilization=0.20,
            sllm_api_key="",
            stt_api_key="",
        )
        for command in build_commands(config, "vllm").values():
            parser.parse_args(command[2:])
    print("vLLM runtime command parsing: OK")


if __name__ == "__main__":
    main()
