"""Parse the real runtime command at image build time without loading a model."""

import json
from unittest.mock import patch

from general_runtime import build_command
from model_profiles import PROFILE_FILE, load_profile


def main() -> None:
    from vllm.entrypoints.openai.cli_args import make_arg_parser
    from vllm.platforms import current_platform
    from vllm.utils.argparse_utils import FlexibleArgumentParser

    # Image builders have no GPU. Register the installed entry-point and inspect
    # the actual registries, without downloading weights or creating an engine.
    with patch.object(current_platform, "device_type", "cpu"):
        from torch import nn
        from vllm.config import LoadConfig
        from vllm.model_executor.layers.linear import LinearBase
        from vllm.model_executor.layers.quantization import get_quantization_config
        from vllm.model_executor.model_loader import get_model_loader
        from vllm.model_executor.models.utils import WeightsMapper
        from vllm.plugins import load_general_plugins
        from vllm_bnb_plugin.bitsandbytes import BitsAndBytesConfig
        from vllm_bnb_plugin.bitsandbytes_loader import BitsAndBytesModelLoader

        load_general_plugins()
        assert get_quantization_config("bitsandbytes") is BitsAndBytesConfig
        assert get_quantization_config("fp8").get_name() == "fp8"
        loader = get_model_loader(LoadConfig(load_format="bitsandbytes"))
        assert isinstance(loader, BitsAndBytesModelLoader)
        # Exercise the plugin's real mapper setup, which registry-only checks
        # miss. This small CPU module creates no weights or model engine.
        fixture = nn.Module()
        fixture.packed_modules_mapping = {"projection": ["projection"]}
        fixture.hf_to_vllm_mapper = WeightsMapper(
            orig_to_new_prefix={"checkpoint.": ""}
        )
        fixture.add_module(
            "projection",
            LinearBase(8, 8, quant_config=BitsAndBytesConfig(), disable_tp=True),
        )
        loader._initialize_loader_state(fixture, None)
        assert (
            loader.weight_mapper("checkpoint.projection.weight") == "projection.weight"
        )
        assert "projection" in loader.target_modules
        parser = make_arg_parser(FlexibleArgumentParser())
    for name in json.loads(PROFILE_FILE.read_text())["profiles"]:
        profile = load_profile(name)
        args = parser.parse_args(build_command(profile["model"], name)[2:])
        assert args.quantization == profile["quantization"]
        assert args.load_format == profile["load_format"]
        assert args.enable_log_requests is False
    print("general vLLM BnB registries and runtime command parsing: OK")


if __name__ == "__main__":
    main()
