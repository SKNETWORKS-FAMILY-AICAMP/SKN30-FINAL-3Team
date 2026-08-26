data "aws_ec2_managed_prefix_list" "cloudfront_origin_facing" {
  name = "com.amazonaws.global.cloudfront.origin-facing"
}

resource "aws_security_group" "alb" {
  name        = "${local.name_prefix}-alb"
  description = "CloudFront-only ingress for the development ALB"
  vpc_id      = aws_vpc.dev.id

  tags = {
    Name = "${local.name_prefix}-alb-sg"
  }
}

resource "aws_security_group" "app" {
  name        = "${local.name_prefix}-app"
  description = "Application host traffic for the development environment"
  vpc_id      = aws_vpc.dev.id

  tags = {
    Name = "${local.name_prefix}-app-sg"
  }
}

resource "aws_security_group" "database" {
  name        = "${local.name_prefix}-db"
  description = "PostgreSQL traffic from the development application only"
  vpc_id      = aws_vpc.dev.id

  tags = {
    Name = "${local.name_prefix}-db-sg"
  }
}

resource "aws_vpc_security_group_ingress_rule" "alb_http_from_cloudfront" {
  security_group_id = aws_security_group.alb.id
  description       = "HTTP from the CloudFront origin-facing managed prefix list"
  prefix_list_id    = data.aws_ec2_managed_prefix_list.cloudfront_origin_facing.id
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
}

resource "aws_vpc_security_group_egress_rule" "alb_to_app" {
  security_group_id            = aws_security_group.alb.id
  description                  = "Application traffic to the app security group"
  referenced_security_group_id = aws_security_group.app.id
  ip_protocol                  = "tcp"
  from_port                    = local.application_port
  to_port                      = local.application_port
}

resource "aws_vpc_security_group_ingress_rule" "app_from_alb" {
  security_group_id            = aws_security_group.app.id
  description                  = "Application traffic from the ALB security group"
  referenced_security_group_id = aws_security_group.alb.id
  ip_protocol                  = "tcp"
  from_port                    = local.application_port
  to_port                      = local.application_port
}

resource "aws_vpc_security_group_egress_rule" "app_https" {
  security_group_id = aws_security_group.app.id
  description       = "HTTPS to AWS public endpoints and approved external providers"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_vpc_security_group_egress_rule" "app_to_database" {
  security_group_id            = aws_security_group.app.id
  description                  = "PostgreSQL to the database security group"
  referenced_security_group_id = aws_security_group.database.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

resource "aws_vpc_security_group_ingress_rule" "database_from_app" {
  security_group_id            = aws_security_group.database.id
  description                  = "PostgreSQL from the app security group"
  referenced_security_group_id = aws_security_group.app.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}


resource "aws_vpc_security_group_rules_exclusive" "alb" {
  security_group_id = aws_security_group.alb.id
  ingress_rule_ids  = [aws_vpc_security_group_ingress_rule.alb_http_from_cloudfront.id]
  egress_rule_ids   = [aws_vpc_security_group_egress_rule.alb_to_app.id]
}

resource "aws_vpc_security_group_rules_exclusive" "app" {
  security_group_id = aws_security_group.app.id
  ingress_rule_ids  = [aws_vpc_security_group_ingress_rule.app_from_alb.id]
  egress_rule_ids = [
    aws_vpc_security_group_egress_rule.app_https.id,
    aws_vpc_security_group_egress_rule.app_to_database.id,
  ]
}

resource "aws_vpc_security_group_rules_exclusive" "database" {
  security_group_id = aws_security_group.database.id
  ingress_rule_ids  = [aws_vpc_security_group_ingress_rule.database_from_app.id]
  egress_rule_ids   = []
}
