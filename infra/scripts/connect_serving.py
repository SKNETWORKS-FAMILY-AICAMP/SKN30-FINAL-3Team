# /// script
# requires-python = ">=3.13,<3.14"
# dependencies = ["boto3>=1.40,<2"]
# ///
"""Export private local connection settings and optionally hold fixed SSM tunnels."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "scripts"))
from serving_contract import GENERAL_KEY, PORTS, endpoint_urls

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "serving"))
from model_profiles import load_profile

LOCAL_PORTS = {8000: 18000, 8001: 18001, 8002: 18002}


def local_environment(
    workload: str, urls: list[str], keys: list[str], model_profile: str | None = None
) -> dict[str, str]:
    if workload == "f2":
        return {
            "AI_VLLM_SLLM_BASE_URL": urls[0],
            "AI_VLLM_STT_BASE_URL": urls[1],
            "AI_VLLM_SLLM_API_KEY": keys[0],
            "AI_VLLM_STT_API_KEY": keys[1],
        }
    if not model_profile:
        raise ValueError("explicit general model profile required")
    return {
        "AI_GENERAL_PROVIDER": "vllm",
        "AI_GENERAL_MODEL": load_profile(model_profile)["model"],
        "AI_GENERAL_BASE_URL": urls[0],
        GENERAL_KEY: keys[0],
    }


def main() -> int:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("workload", choices=("f2", "general"))
    cli.add_argument("--account-id", required=True)
    cli.add_argument("--profile", default="skn30-session")
    cli.add_argument("--project", default="skn30-final-3team")
    cli.add_argument(
        "--output",
        type=Path,
        required=True,
        help="new ignored private env file; existing files are never replaced",
    )
    args = cli.parse_args()
    sessions = []
    try:
        session = boto3.Session(profile_name=args.profile, region_name="ap-northeast-2")
        identity = session.client("sts").get_caller_identity()
        if identity["Account"] != args.account_id or identity["Arn"].endswith(":root"):
            raise ValueError("wrong AWS account or unsupported identity")
        prefix = f"{args.project}-dev"
        parameter = (
            "AI_VLLM_ENDPOINT_SET"
            if args.workload == "f2"
            else "AI_GENERAL_ENDPOINT_SET"
        )
        endpoint = json.loads(
            session.client("ssm").get_parameter(Name=f"/{prefix}/ai/{parameter}")[
                "Parameter"
            ]["Value"]
        )
        if endpoint.get("status") != "active":
            raise ValueError(
                "shared GPU is offline; ask the Infra operator to start it"
            )
        cloud = endpoint.get("cloud", "runpod")
        if cloud == "aws":
            iid = endpoint.get("instance_id", endpoint.get("resource_id"))
            instance = session.client("ec2").describe_instances(InstanceIds=[iid])[
                "Reservations"
            ][0]["Instances"][0]
            tags = {entry["Key"]: entry["Value"] for entry in instance.get("Tags", [])}
            if (
                instance["State"]["Name"] != "running"
                or tags.get("Project") != args.project
                or tags.get("Environment") != "dev"
                or tags.get("ServingWorkload") != args.workload
                or tags.get("ManagedBy") != "Terraform"
            ):
                raise ValueError(
                    "shared GPU was stopped/replaced; reconnect after dev-status"
                )
            urls = [
                f"http://127.0.0.1:{LOCAL_PORTS[port]}/v1"
                for port in PORTS[args.workload]
            ]
            for port in PORTS[args.workload]:
                with socket.socket() as check:
                    check.bind(("127.0.0.1", LOCAL_PORTS[port]))
        else:
            resource = endpoint.get("pod_id", endpoint.get("resource_id"))
            urls = endpoint_urls(cloud, resource, args.workload)
        if not sys.stdin.isatty():
            raise ValueError(
                "connection export requires a private interactive terminal"
            )
        names = (
            ["AI_VLLM_SLLM_API_KEY", "AI_VLLM_STT_API_KEY"]
            if args.workload == "f2"
            else [GENERAL_KEY]
        )
        keys = [
            getpass.getpass(f"{name} (provided by Infra operator): ") for name in names
        ]
        if not all(re.fullmatch(r"[A-Za-z0-9_-]{43,128}", key) for key in keys):
            raise ValueError("invalid service key")
        values = local_environment(
            args.workload, urls, keys, endpoint.get("model_profile")
        )
        # Do not write into a tracked/default env file or overwrite a developer's settings.
        destination = args.output.resolve()
        ignored = (
            subprocess.run(
                ["git", "check-ignore", "--quiet", str(destination)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            ).returncode
            == 0
        )
        if not ignored:
            raise ValueError("output must be a Git-ignored private env file")
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as output:
            output.write(
                "\n".join(
                    f"{name}={json.dumps(value, ensure_ascii=False)}"
                    for name, value in values.items()
                )
                + "\n"
            )
        print(
            "Private AI overrides created. Merge into ai/.env; the general model matches the deployed profile. Run local-config before use. No dev routing changed."
        )
        if cloud == "aws":
            for port in PORTS[args.workload]:
                suffix = {8001: "f2_sllm", 8002: "f2_stt", 8000: "general"}[port]
                sessions.append(
                    subprocess.Popen(
                        [
                            "aws",
                            "ssm",
                            "start-session",
                            "--target",
                            iid,
                            "--document-name",
                            f"{prefix}-gpu-{suffix}-tunnel",
                            "--parameters",
                            json.dumps({"localPortNumber": [str(LOCAL_PORTS[port])]}),
                            "--profile",
                            args.profile,
                            "--region",
                            "ap-northeast-2",
                        ],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                )
            print(
                "SSM tunnels starting on loopback. Keep this command running; Ctrl-C closes all tunnels."
            )
            while all(process.poll() is None for process in sessions):
                time.sleep(1)
            raise ValueError(
                "SSM tunnel ended; check permissions/port conflicts and reconnect"
            )
        return 0
    except KeyboardInterrupt:
        return 0
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    except (OSError, ClientError, BotoCoreError):
        print(
            "Local connection unavailable: verify active GPU, account/permissions, private output path and keys. No dev changes were made.",
            file=sys.stderr,
        )
        return 2
    finally:
        for process in sessions:
            if process.poll() is None:
                process.terminate()
        for process in sessions:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    sys.exit(main())
