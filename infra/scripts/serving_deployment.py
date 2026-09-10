"""Fail closed before first-deploy GPU costs if old ASG launch deployment remains."""

from manage_dev_power import Settings, ToolError
from model_profiles import load_profile


def require_maintenance_deployment(session, settings: Settings) -> None:
    name = f"{settings.name_prefix}-backend"
    group = session.client("codedeploy").get_deployment_group(
        applicationName=name, deploymentGroupName=name
    )["deploymentGroupInfo"]
    if group.get("autoScalingGroups"):
        raise ToolError(
            "first deployment requires the reviewed app_deployment_mode=maintenance "
            "Terraform plan; automatic ASG launch deployment is still attached"
        )
    style = group.get("deploymentStyle", {})
    if (
        style.get("deploymentType") != "IN_PLACE"
        or style.get("deploymentOption") != "WITHOUT_TRAFFIC_CONTROL"
    ):
        raise ToolError(
            "maintenance deployment must use IN_PLACE / WITHOUT_TRAFFIC_CONTROL; "
            "the stopped app cannot satisfy CodeDeploy ALB health checks"
        )
    expected = {
        ("Project", settings.project),
        ("Environment", settings.environment),
        ("Name", f"{settings.name_prefix}-app-asg"),
    }
    groups = group.get("ec2TagSet", {}).get("ec2TagSetList", [])
    if len(groups) != 3 or any(
        len(tags) != 1 or tags[0].get("Type") != "KEY_AND_VALUE" for tags in groups
    ):
        raise ToolError(
            "maintenance deployment must match all three exact app tag groups"
        )
    actual = {(tags[0].get("Key"), tags[0].get("Value")) for tags in groups}
    if actual != expected or group.get("ec2TagFilters"):
        raise ToolError("maintenance deployment target differs from the exact app tags")


def require_general_selection(ssm, prefix: str, selection: dict) -> None:
    public = {
        name: ssm.get_parameter(Name=f"/{prefix}/ai/AI_GENERAL_{name}")["Parameter"][
            "Value"
        ]
        for name in ("PROVIDER", "MODEL")
    }
    if public["PROVIDER"] not in {"openai", "vllm", "bedrock"}:
        raise ToolError("unsupported shared general provider")
    general = selection["general"]
    if public["PROVIDER"] == "vllm":
        if (
            not general
            or load_profile(general["model_profile"])["model"] != public["MODEL"]
        ):
            raise ToolError(
                "configure a general GPU profile matching the Terraform provider/model before preparing deployment"
            )
    elif general:
        raise ToolError(
            "general GPU selection conflicts with the configured application provider"
        )
