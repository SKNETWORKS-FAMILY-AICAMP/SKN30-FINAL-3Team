# Shared dev's selected connection. Terraform owns these public settings; changing
# serving/SELECTION alone does not change the application provider or DB model versions.
variable "general_model_selection" {
  description = "Reviewed shared-dev provider/model selection; apply capability DB versions explicitly during maintenance"
  type = object({
    # Allowed: openai | vllm | bedrock. llama_cpp has no shared deployment contract.
    provider = string
    # Allowed per provider: openai=gpt-5.6-luna; bedrock=global.openai.gpt-5.6-luna;
    # vllm=Qwen/Qwen3.8-27B-FP8 | Qwen/Qwen3-14B-AWQ | Qwen/Qwen3-32B-AWQ |
    # unsloth/Qwen3.8-27B-unsloth-bnb-4bit. Must match the selected GPU profile.
    model = string
    # Allowed: ap-northeast-2 for bedrock, omitted/null otherwise. No key or URL in tfvars.
    aws_region = optional(string)
  })
  nullable = false
  default = {
    provider = "vllm"
    model    = "Qwen/Qwen3.8-27B-FP8"
  }

  validation {
    condition = contains(lookup({
      openai  = ["gpt-5.6-luna"]
      bedrock = ["global.openai.gpt-5.6-luna"]
      vllm = [
        "Qwen/Qwen3.8-27B-FP8", "Qwen/Qwen3-14B-AWQ", "Qwen/Qwen3-32B-AWQ",
        "unsloth/Qwen3.8-27B-unsloth-bnb-4bit",
      ]
    }, var.general_model_selection.provider, []), var.general_model_selection.model)
    error_message = "Select a supported provider/model pair listed in general-model.tf."
  }

  validation {
    condition = var.general_model_selection.provider == "bedrock" ? (
      var.general_model_selection.aws_region == "ap-northeast-2"
    ) : var.general_model_selection.aws_region == null
    error_message = "Bedrock requires aws_region=ap-northeast-2; other providers must omit aws_region."
  }
}
