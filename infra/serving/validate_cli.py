"""Parse the real runtime command at image build time without loading a model."""

import json

from general_runtime import build_command
from model_profiles import PROFILE_FILE, load_profile


def main() -> None:
    from vllm.entrypoints.openai.cli_args import make_arg_parser
    from vllm.utils.argparse_utils import FlexibleArgumentParser

    parser = make_arg_parser(FlexibleArgumentParser())
    for name in json.loads(PROFILE_FILE.read_text())["profiles"]:
        args = parser.parse_args(build_command(load_profile(name)["model"], name)[2:])
        assert args.enable_log_requests is False
    print("general vLLM runtime command parsing: OK")


if __name__ == "__main__":
    main()
