# 이 파일을 secrets.auto.tfvars로 복사한 뒤 실제 값으로 교체한다.
# secrets.auto.tfvars는 Git에서 제외되며 Terraform이 plan/apply 때 자동으로 읽는다.

ai_provider_api_keys = {
  AI_OPENAI_API_KEY   = ""
  AI_VLLM_LLM_API_KEY = ""
  AI_VLLM_STT_API_KEY = ""
  # AI_VLLM_EMBEDDING_API_KEY = ""
  # AI_VLLM_STT_API_KEY       = ""
}
ai_provider_secret_version = 1

discord_webhook_url            = ""
discord_webhook_secret_version = 1
