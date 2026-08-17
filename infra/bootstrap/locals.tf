locals {
  state_bucket_name = "${var.project_name}-tfstate-${var.target_account_id}-${var.aws_region}"
  operator_user_names = {
    for arn in var.operator_user_arns : arn => element(reverse(split("/", arn)), 0)
  }
  state_keys = [
    "bootstrap/terraform.tfstate",
    "bootstrap/terraform.tfstate.tflock",
    "environments/dev/terraform.tfstate",
    "environments/dev/terraform.tfstate.tflock",
  ]
}
