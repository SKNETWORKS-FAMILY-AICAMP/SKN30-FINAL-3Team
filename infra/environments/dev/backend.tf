terraform {
  backend "s3" {
    key          = "environments/dev/terraform.tfstate"
    region       = "ap-northeast-2"
    encrypt      = true
    use_lockfile = true
  }
}
