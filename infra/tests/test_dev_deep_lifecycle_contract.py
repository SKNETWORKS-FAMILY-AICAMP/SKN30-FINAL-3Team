import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def read(relative_path: str) -> str:
    return (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")


def section(source: str, start: str, end: str) -> str:
    start_index = source.index(start)
    return source[start_index : source.index(end, start_index)]


class DevDeepLifecycleContractTests(unittest.TestCase):
    def test_edge_flag_defaults_to_active(self) -> None:
        variables = read("infra/environments/dev/variables.tf")
        edge_variable = section(
            variables,
            'variable "dev_edge_enabled"',
            'variable "integrated_pipeline_detect_changes"',
        )

        self.assertIn("type        = bool", edge_variable)
        self.assertIn("default     = true", edge_variable)

    def test_only_alb_listener_and_alb_alarms_are_conditional(self) -> None:
        runtime = read("infra/environments/dev/runtime.tf")
        observability = read("infra/environments/dev/observability.tf")
        delivery = read("infra/environments/dev/delivery.tf")

        load_balancer = section(
            runtime,
            'resource "aws_lb" "app"',
            'resource "aws_lb_target_group" "app"',
        )
        target_group = section(
            runtime,
            'resource "aws_lb_target_group" "app"',
            'resource "aws_lb_listener" "http"',
        )
        listener = section(
            runtime,
            'resource "aws_lb_listener" "http"',
            'resource "aws_launch_template" "app"',
        )

        self.assertIn("count = var.dev_edge_enabled ? 1 : 0", load_balancer)
        self.assertIn("count = var.dev_edge_enabled ? 1 : 0", listener)
        self.assertNotIn("count =", target_group)
        self.assertIn(
            "target_group_arns   = [aws_lb_target_group.app.arn]", runtime
        )
        self.assertIn(
            "autoscaling_groups     = [aws_autoscaling_group.app.name]", delivery
        )
        self.assertEqual(
            observability.count("count = var.dev_edge_enabled ? 1 : 0"), 2
        )

    def test_state_moves_preserve_existing_singletons(self) -> None:
        runtime = read("infra/environments/dev/runtime.tf")
        observability = read("infra/environments/dev/observability.tf")

        for before, after in (
            ("aws_lb.app", "aws_lb.app[0]"),
            ("aws_lb_listener.http", "aws_lb_listener.http[0]"),
        ):
            self.assertIn(f"from = {before}\n", runtime)
            self.assertIn(f"to   = {after}\n", runtime)

        for name in ("alb_unhealthy_hosts", "alb_target_5xx"):
            self.assertIn(
                f"from = aws_cloudwatch_metric_alarm.{name}\n", observability
            )
            self.assertIn(
                f"to   = aws_cloudwatch_metric_alarm.{name}[0]\n", observability
            )

    def test_cloudfront_identity_is_retained_while_edge_blocks_toggle(self) -> None:
        frontend = read("infra/environments/dev/frontend.tf")
        distribution = section(
            frontend,
            'resource "aws_cloudfront_distribution" "frontend"',
            'data "aws_iam_policy_document" "frontend_bucket"',
        )

        self.assertNotIn("count =", distribution)
        self.assertIn("enabled             = var.dev_edge_enabled", distribution)
        self.assertIn("wait_for_deployment = true", distribution)
        self.assertIn('dynamic "origin"', distribution)
        self.assertIn('dynamic "ordered_cache_behavior"', distribution)
        self.assertIn("depends_on = [aws_lb_listener.http]", distribution)
        self.assertIn("distribution_enabled = var.dev_edge_enabled", frontend)

    def test_alb_dns_and_automatic_delivery_follow_edge_mode(self) -> None:
        configuration = read("infra/environments/dev/configuration.tf")
        delivery = read("infra/environments/dev/delivery.tf")

        self.assertIn("aws_lb.app[*].dns_name", configuration)
        self.assertIn('["localhost", "127.0.0.1"]', configuration)
        self.assertIn(
            "tostring(var.dev_edge_enabled && "
            "var.integrated_pipeline_detect_changes)",
            delivery,
        )
        self.assertIn(
            "automatic_dev_delivery = "
            "var.dev_edge_enabled && var.integrated_pipeline_detect_changes",
            delivery,
        )

    def test_deep_commands_use_reviewed_plans_and_safe_order(self) -> None:
        justfile = read("infra/justfile")
        stop_recipe = section(
            justfile,
            "dev-deep-stop:",
            "# deep suspend 상태",
        )
        start_recipe = section(
            justfile,
            "dev-deep-start:",
            "# Terraform state의 edge mode",
        )

        self.assertIn("-var=dev_edge_enabled=false", justfile)
        self.assertIn("-out=dev-deep-stop.tfplan", justfile)
        self.assertIn("-var=dev_edge_enabled=true", justfile)
        self.assertIn("-out=dev-deep-start.tfplan", justfile)
        self.assertIn("apply dev-deep-stop.tfplan", stop_recipe)
        self.assertLess(stop_recipe.index(" stop --apply"), stop_recipe.index(" apply "))
        self.assertIn("apply dev-deep-start.tfplan", start_recipe)
        self.assertLess(start_recipe.index(" apply "), start_recipe.index(" start --apply"))
        self.assertNotIn("aws elbv2 delete-load-balancer", justfile)
        self.assertNotIn("aws elbv2 create-load-balancer", justfile)

    def test_runbook_separates_active_and_suspended_drift(self) -> None:
        readme = read("infra/README.md")

        self.assertIn("just dev-deep-stop-plan", readme)
        self.assertIn("just dev-deep-start-plan", readme)
        self.assertIn("just dev-deep-drift", readme)
        self.assertIn("Deep suspend 중에는 기본값이 active인 일반", readme)
        self.assertIn("distribution ID와 기본 domain", readme)


if __name__ == "__main__":
    unittest.main()
