# Copy these profiles into ignored infra/environments/dev/dev.tfvars after review.
# Placeholder digests intentionally fail validation. Never apply this example directly.
gpu_profiles = {
  f2 = {
    ami_id         = "ami-REVIEW_UBUNTU24_NVIDIA_DLAMI"
    image          = "ghcr.io/OWNER/REPO/f2-serving@sha256:REVIEW_PUBLISHED_DIGEST"
    root_volume_gb = 160
  }
  general = {
    ami_id         = "ami-REVIEW_UBUNTU24_NVIDIA_DLAMI"
    image          = "ghcr.io/OWNER/REPO/general-serving@sha256:REVIEW_PUBLISHED_DIGEST"
    root_volume_gb = 160
  }
}
# Do not set gpu_provisioned_workloads here: capacity-config owns its local auto.tfvars input.
