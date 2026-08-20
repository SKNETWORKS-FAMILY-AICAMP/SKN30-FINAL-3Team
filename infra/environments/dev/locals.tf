locals {
  environment = "dev"
  name_prefix = "${var.project_name}-${local.environment}"

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
