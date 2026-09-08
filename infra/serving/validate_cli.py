"""Parse the real runtime command at image build time without loading a model."""

import json
from unittest.mock import patch

from general_runtime import build_command
from model_profiles import PROFILE_FILE, load_profile


def main() -> None:
    from vllm.entrypoints.openai.cli_args import make_arg_parser
    from vllm.platforms import current_platform
    from vllm.utils.argparse_utils import FlexibleArgumentParser

    # Image builders have no GPU. Only construct/parse the real CLI here;
    # device detection and model compatibility are checked on the actual GPU.
    with patch.object(current_platform, "device_type", "cpu"):
        parser = make_arg_parser(FlexibleArgumentParser())
    for name in json.loads(PROFILE_FILE.read_text())["profiles"]:
        args = parser.parse_args(build_command(load_profile(name)["model"], name)[2:])
        assert args.enable_log_requests is False
    print("general vLLM runtime command parsing: OK")


if __name__ == "__main__":
    main()
