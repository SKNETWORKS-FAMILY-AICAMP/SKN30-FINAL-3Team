locals {
  environment = "dev"
  name_prefix = "${var.project_name}-${local.environment}"

  application_port       = tonumber(local.application_environment.backend.APP_PORT)
  application_ready_path = "/health/ready"

  # Vite is served behind the same CloudFront origin. Keeping this relative means
  # a distribution domain change does not require a source-code configuration edit.
  frontend_api_base_path    = "/api/v1"
  frontend_api_path_pattern = "/${split("/", trimprefix(local.frontend_api_base_path, "/"))[0]}/*"

  vpc_cidr = "10.30.0.0/16"

  public_subnets = {
    a = {
      availability_zone_index = 0
      cidr_block              = "10.30.0.0/24"
    }
    b = {
      availability_zone_index = 1
      cidr_block              = "10.30.1.0/24"
    }
  }

  database_subnets = {
    a = {
      availability_zone_index = 0
      cidr_block              = "10.30.10.0/24"
    }
    b = {
      availability_zone_index = 1
      cidr_block              = "10.30.11.0/24"
    }
  }
}
