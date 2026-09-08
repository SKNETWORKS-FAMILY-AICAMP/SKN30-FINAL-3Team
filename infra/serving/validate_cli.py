"""Parse the real runtime command at image build time without loading a model."""

from general_runtime import MODEL, build_command


def main() -> None:
    from vllm.entrypoints.openai.cli_args import make_arg_parser
    from vllm.utils.argparse_utils import FlexibleArgumentParser

    parser = make_arg_parser(FlexibleArgumentParser())
    args = parser.parse_args(build_command(MODEL)[2:])
    assert args.enable_log_requests is False
    print("general vLLM runtime command parsing: OK")


if __name__ == "__main__":
    main()
