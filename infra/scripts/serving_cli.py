"""CLI argument contract for explicit serving operations."""

import argparse
import os

from serving_contract import WORKLOADS


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--account-id", default=os.environ.get("TARGET_ACCOUNT_ID", ""))
    result.add_argument("--profile", default="skn30-session")
    result.add_argument("--project", default="skn30-final-3team")
    commands = result.add_subparsers(dest="command", required=True)
    for action in ("start", "stop", "status", "prepare-deployment"):
        p = commands.add_parser(action)
        if action != "status":
            p.add_argument("--apply", action="store_true")
            p.add_argument("--workloads-stopped-confirmed", action="store_true")
        if action in {"start", "prepare-deployment"}:
            p.add_argument("--hours", type=float, default=2)
            p.add_argument(
                "--hourly-usd", action="append", default=[], metavar="WORKLOAD=RATE"
            )
    selection = commands.add_parser("select")
    selection.add_argument("--workload", choices=WORKLOADS)
    selection.add_argument("--cloud", choices=("aws", "runpod"))
    from selection_catalog import GeneralModelProfile, HardwareProfile

    selection.add_argument(
        "--hardware-profile", choices=[p.value for p in HardwareProfile]
    )
    selection.add_argument(
        "--model-profile", choices=[p.value for p in GeneralModelProfile]
    )
    selection.add_argument("--release")
    selection.add_argument("--bucket")
    selection.add_argument("--allow-dev-release", action="store_true")
    selection.add_argument("--apply", action="store_true")
    activation = commands.add_parser("activate-general")
    activation.add_argument("brokerage_id", type=int)
    activation.add_argument(
        "--capability",
        required=True,
        choices=("POSITION_CARD", "BROKERAGE_JUDGMENT", "CHATBOT"),
    )
    activation.add_argument("--apply", action="store_true")
    activation.add_argument("--workloads-stopped-confirmed", action="store_true")
    capacity = commands.add_parser("capacity-config")
    capacity.add_argument("--candidate", choices=WORKLOADS)
    for action in ("switch", "configure", "smoke", "verify"):
        p = commands.add_parser(action)
        p.add_argument("workload", choices=WORKLOADS)
        if action not in {"smoke", "verify"}:
            p.add_argument("cloud", choices=("aws", "runpod"))
            p.add_argument("--apply", action="store_true")
        if action == "configure":
            p.add_argument("--gpu-id", required=True)
            p.add_argument("--model-profile")
            p.add_argument("--release-id")
            p.add_argument("--bucket")
            p.add_argument("--allow-dev-release", action="store_true")
    return result
