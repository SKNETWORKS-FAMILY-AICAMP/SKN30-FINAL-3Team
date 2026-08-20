data "aws_iam_policy_document" "operator_trust" {
  statement {
    sid     = "AllowApprovedAwsLoginUsers"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "AWS"
      identifiers = var.operator_user_arns
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SignInSessionArn"
      values   = ["arn:${data.aws_partition.current.partition}:signin:*:${var.target_account_id}:session/*"]
    }

    condition {
      test     = "DateLessThan"
      variable = "aws:CurrentTime"
      values   = ["${var.expires_at}T23:59:59Z"]
    }
  }
}

resource "aws_iam_role" "terraform_operator" {
  name                 = "TerraformOperatorRole"
  description          = "Temporary Terraform deployment role; replace with Identity Center before production"
  assume_role_policy   = data.aws_iam_policy_document.operator_trust.json
  max_session_duration = 3600
}

resource "aws_iam_role_policy_attachment" "terraform_operator_admin" {
  role       = aws_iam_role.terraform_operator.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/AdministratorAccess"
}

data "aws_iam_policy_document" "assume_operator" {
  statement {
    sid       = "AssumeTerraformOperatorWithMFA"
    effect    = "Allow"
    actions   = ["sts:AssumeRole"]
    resources = [aws_iam_role.terraform_operator.arn]
  }
}

resource "aws_iam_user_policy" "assume_operator" {
  for_each = local.operator_user_names

  name   = "AssumeTerraformOperatorRole"
  user   = each.value
  policy = data.aws_iam_policy_document.assume_operator.json
}

resource "aws_iam_user_policy_attachment" "aws_login" {
  for_each = local.operator_user_names

  user       = each.value
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/SignInLocalDevelopmentAccess"
}
