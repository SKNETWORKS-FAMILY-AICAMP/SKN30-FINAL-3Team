terraform {
  backend "s3" {
    key          = "bootstrap/terraform.tfstate"
    region       = "ap-northeast-2"
    encrypt      = true
    use_lockfile = true
  }
}
