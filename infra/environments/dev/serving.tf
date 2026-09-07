# GPU capacity is opt-in. Empty defaults never create billable GPU instances.
variable "gpu_profiles" {
  description = "Reviewed AWS GPU profiles. AMI must provide Ubuntu 24.04, NVIDIA driver/toolkit and Docker. Images are immutable GHCR references."
  type = map(object({
    ami_id         = string
    image          = string
    root_volume_gb = optional(number, 160)
  }))
  default = {}
  validation {
    condition     = alltrue([for name, p in var.gpu_profiles : contains(["f2", "general"], name) && can(regex("^ami-[0-9a-f]+$", p.ami_id)) && can(regex("^ghcr.io/[a-z0-9._/-]+@sha256:[0-9a-f]{64}$", p.image)) && p.root_volume_gb >= 80])
    error_message = "Use f2/general, a pinned AMI and GHCR digest, and at least 80 GiB for images plus model cache."
  }
}
variable "gpu_provisioned_workloads" {
  description = "Capacity intent, distinct from retained profiles and active endpoints. Written to serving-capacity.auto.tfvars.json by capacity-config."
  type        = set(string)
  default     = []
  validation {
    condition     = alltrue([for name in var.gpu_provisioned_workloads : contains(keys(var.gpu_profiles), name)])
    error_message = "Every requested GPU requires a reviewed pinned gpu_profiles entry."
  }
}
variable "dev_gpu_enabled" {
  description = "Deep suspend removes GPU EC2 and all disposable root/model caches; profiles remain configured."
  type        = bool
  default     = true
}
locals {
  gpu_instances = { for name, profile in var.gpu_profiles : name => profile if var.dev_gpu_enabled && contains(var.gpu_provisioned_workloads, name) }
  gpu_types     = { f2 = "g6.2xlarge", general = "g6e.2xlarge" }
  gpu_ports     = { f2 = [8001, 8002], general = [8000] }
}
resource "aws_ssm_parameter" "serving_selection" {
  name  = "/${local.name_prefix}/serving/SELECTION"
  type  = "String"
  value = jsonencode({ f2 = null, general = null })
  lifecycle { ignore_changes = [value] }
}
resource "aws_ssm_parameter" "general_endpoint" {
  name  = "/${local.name_prefix}/ai/AI_GENERAL_ENDPOINT_SET"
  type  = "String"
  value = jsonencode({ status = "offline" })
  lifecycle { ignore_changes = [value] }
}
resource "aws_ssm_parameter" "general_runpod_control" {
  name  = "/${local.name_prefix}/runpod/GENERAL_CONTROL_SET"
  type  = "String"
  value = jsonencode(local.runpod_control_set_bootstrap)
  lifecycle { ignore_changes = [value] }
}
resource "aws_security_group" "gpu" {
  for_each    = var.gpu_profiles
  name        = "${local.name_prefix}-${each.key}-gpu"
  description = "Private inference from the application; SSM for administration"
  vpc_id      = aws_vpc.dev.id
}
resource "aws_vpc_security_group_ingress_rule" "gpu_inference" {
  for_each                     = merge({}, [for name, p in var.gpu_profiles : { for port in local.gpu_ports[name] : "${name}-${port}" => { workload = name, port = port } }]...)
  security_group_id            = aws_security_group.gpu[each.value.workload].id
  referenced_security_group_id = aws_security_group.app.id
  ip_protocol                  = "tcp"
  from_port                    = each.value.port
  to_port                      = each.value.port
}
resource "aws_vpc_security_group_egress_rule" "app_to_gpu" {
  for_each                     = aws_vpc_security_group_ingress_rule.gpu_inference
  security_group_id            = aws_security_group.app.id
  referenced_security_group_id = each.value.security_group_id
  ip_protocol                  = "tcp"
  from_port                    = each.value.from_port
  to_port                      = each.value.to_port
}
resource "aws_vpc_security_group_egress_rule" "gpu_https" {
  for_each          = var.gpu_profiles
  security_group_id = aws_security_group.gpu[each.key].id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}
resource "aws_iam_role" "gpu" {
  for_each           = var.gpu_profiles
  name               = "${local.name_prefix}-${each.key}-gpu"
  assume_role_policy = data.aws_iam_policy_document.app_instance_assume_role.json
}
resource "aws_iam_role_policy_attachment" "gpu_ssm" {
  for_each   = var.gpu_profiles
  role       = aws_iam_role.gpu[each.key].name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}
resource "aws_iam_role_policy" "gpu_runtime" {
  for_each = var.gpu_profiles
  role     = aws_iam_role.gpu[each.key].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["ssm:GetParameter"], Resource = [aws_ssm_parameter.serving_selection.arn] },
    { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = [aws_secretsmanager_secret.application["ai_provider"].arn, aws_secretsmanager_secret.runpod["ghcr_registry"].arn] },
    { Effect = "Allow", Action = ["s3:GetObject"], Resource = ["${aws_s3_bucket.workload["data_model"].arn}/releases/sllm/*"] }
  ] })
}
resource "aws_iam_instance_profile" "gpu" {
  for_each = var.gpu_profiles
  name     = "${local.name_prefix}-${each.key}-gpu"
  role     = aws_iam_role.gpu[each.key].name
}
resource "aws_instance" "gpu" {
  for_each                    = local.gpu_instances
  ami                         = each.value.ami_id
  instance_type               = local.gpu_types[each.key]
  subnet_id                   = aws_subnet.public["a"].id
  associate_public_ip_address = true
  vpc_security_group_ids      = [aws_security_group.gpu[each.key].id]
  iam_instance_profile        = aws_iam_instance_profile.gpu[each.key].name
  user_data_replace_on_change = true
  user_data_base64 = base64gzip(templatefile("${path.module}/../../serving/user-data.sh.tftpl", {
    host_script     = base64encode(file("${path.module}/../../serving/gpu_host.py"))
    probe_script    = base64encode(file("${path.module}/../../serving/probe.py"))
    download_script = base64encode(file("${path.module}/../../serving/download_models.py"))
    config = base64encode(jsonencode({ workload = each.key, prefix = local.name_prefix, image = each.value.image, model_bucket = aws_s3_bucket.workload["data_model"].id,
    model = "unsloth/Qwen3.8-27B-unsloth-bnb-4bit", revision = "8aa5f05d26b7205477066e1449e0af13f762a299" }))
  }))
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }
  root_block_device {
    encrypted             = true
    volume_type           = "gp3"
    volume_size           = each.value.root_volume_gb
    delete_on_termination = true
    tags                  = merge(local.runtime_tags, { Name = "${local.name_prefix}-${each.key}-gpu-cache", ServingWorkload = each.key })
  }
  tags       = merge(local.runtime_tags, { Name = "${local.name_prefix}-${each.key}-gpu", ServingWorkload = each.key, ServingImage = each.value.image })
  depends_on = [aws_iam_role_policy.gpu_runtime, aws_iam_role_policy_attachment.gpu_ssm]
}
output "gpu_instances" {
  description = "Managed GPU identities for guarded operations; no credentials or endpoint URLs"
  value       = { for name, instance in aws_instance.gpu : name => { instance_id = instance.id, image = var.gpu_profiles[name].image, root_volume_gb = var.gpu_profiles[name].root_volume_gb } }
}
# Local developers receive only fixed-port sessions, never shell or RunCommand.
resource "aws_iam_group" "team_gpu_tunnel" {
  name = "team-gpu-tunnel"
}
resource "aws_ssm_document" "gpu_tunnel" {
  for_each        = { f2_sllm = 8001, f2_stt = 8002, general = 8000 }
  name            = "${local.name_prefix}-gpu-${each.key}-tunnel"
  document_type   = "Session"
  document_format = "JSON"
  content = jsonencode({ schemaVersion = "1.0", description = "Fixed local GPU inference port", sessionType = "Port",
    parameters = { localPortNumber = { type = "String", default = tostring(each.value), allowedPattern = "^[0-9]{4,5}$" } },
  properties = { portNumber = tostring(each.value), localPortNumber = "{{ localPortNumber }}", type = "LocalPortForwarding" } })
}
resource "aws_iam_group_policy" "team_gpu_tunnel" {
  group = aws_iam_group.team_gpu_tunnel.name
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["ec2:DescribeInstances", "ssm:DescribeInstanceInformation"], Resource = "*" },
    { Effect = "Allow", Action = ["ssm:GetParameter"], Resource = [aws_ssm_parameter.ai_vllm_endpoint_set.arn, aws_ssm_parameter.general_endpoint.arn] },
    { Effect = "Allow", Action = ["ssm:StartSession"], Resource = "arn:aws:ec2:${var.aws_region}:${var.target_account_id}:instance/*",
    Condition = { BoolIfExists = { "ssm:SessionDocumentAccessCheck" = "true" }, StringEquals = { "ssm:resourceTag/Project" = var.project_name, "ssm:resourceTag/Environment" = "dev", "ssm:resourceTag/ManagedBy" = "Terraform", "ssm:resourceTag/ServingWorkload" = ["f2", "general"] } } },
    { Effect = "Allow", Action = ["ssm:StartSession"], Resource = [for doc in aws_ssm_document.gpu_tunnel : doc.arn] },
    { Effect = "Allow", Action = ["ssmmessages:OpenDataChannel", "ssm:ResumeSession", "ssm:TerminateSession"], Resource = "arn:aws:ssm:${var.aws_region}:${var.target_account_id}:session/$${aws:userid}-*" }
  ] })
}
