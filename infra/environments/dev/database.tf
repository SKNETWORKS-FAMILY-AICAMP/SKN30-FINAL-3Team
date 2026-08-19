locals {
  database_name            = "brokerage"
  database_master_username = "dbadmin"
}

resource "aws_db_subnet_group" "postgres" {
  name       = "${local.name_prefix}-postgres"
  subnet_ids = [for subnet in aws_subnet.database : subnet.id]

  tags = {
    Name = "${local.name_prefix}-postgres"
  }
}

resource "aws_db_instance" "postgres" {
  identifier = "${local.name_prefix}-postgres"

  engine         = "postgres"
  engine_version = "15.18"
  instance_class = "db.t4g.small"

  allocated_storage     = 20
  max_allocated_storage = 50
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name                             = local.database_name
  username                            = local.database_master_username
  manage_master_user_password         = true
  iam_database_authentication_enabled = true
  port                                = 5432

  db_subnet_group_name   = aws_db_subnet_group.postgres.name
  vpc_security_group_ids = [aws_security_group.database.id]
  publicly_accessible    = false
  multi_az               = false

  backup_retention_period = 7
  backup_window           = "18:00-19:00"
  maintenance_window      = "sun:19:00-sun:20:00"
  enabled_cloudwatch_logs_exports = [
    "postgresql",
    "upgrade",
  ]

  auto_minor_version_upgrade = true
  apply_immediately          = false

  performance_insights_enabled = false
  monitoring_interval          = 0

  deletion_protection       = true
  skip_final_snapshot       = false
  final_snapshot_identifier = "${local.name_prefix}-postgres-final-20260923"
  copy_tags_to_snapshot     = true
  delete_automated_backups  = true
  depends_on = [
    aws_cloudwatch_log_group.runtime["rds_postgresql"],
    aws_cloudwatch_log_group.runtime["rds_upgrade"],
  ]

  tags = {
    Name = "${local.name_prefix}-postgres"
  }
}

output "database_endpoint" {
  description = "애플리케이션 설정 조립에 사용할 RDS host와 port(자격 증명 미포함)"
  value = {
    address = aws_db_instance.postgres.address
    name    = aws_db_instance.postgres.db_name
    port    = aws_db_instance.postgres.port
  }
}

output "database_master_secret_arn" {
  description = "RDS가 관리하는 master user Secrets Manager secret ARN"
  value       = aws_db_instance.postgres.master_user_secret[0].secret_arn
}
