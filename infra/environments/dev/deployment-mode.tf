# Infrastructure transition mode; never injected into Backend or AI environments.
variable "app_deployment_mode" {
  description = "automatic attaches CodeDeploy to ASG; maintenance targets only app tags to install a new revision without restoring the old launch revision"
  type        = string
  default     = "automatic"
  nullable    = false

  # Allowed: automatic | maintenance. Use maintenance only for reviewed first-deploy
  # transition, then restore automatic after the current revision deploys successfully.
  validation {
    condition     = contains(["automatic", "maintenance"], var.app_deployment_mode)
    error_message = "app_deployment_mode must be automatic or maintenance."
  }
}
