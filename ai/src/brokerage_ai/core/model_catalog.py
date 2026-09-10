"""Project-supported selections; add models here with provenance and tests."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, model_validator

from brokerage_ai.core.types import ModelRoute, ProviderKind


class GeneralModel(StrEnum):
    OPENAI_LUNA = "gpt-5.6-luna"
    BEDROCK_LUNA = "global.openai.gpt-5.6-luna"
    QWEN_FP8 = "Qwen/Qwen3.8-27B-FP8"
    QWEN_14B = "Qwen/Qwen3-14B-AWQ"
    QWEN_32B = "Qwen/Qwen3-32B-AWQ"
    QWEN_GGUF = "unsloth/Qwen3.8-27B-GGUF:UD-Q4_K_M"
    QWEN_BNB = "unsloth/Qwen3.8-27B-unsloth-bnb-4bit"


REVISIONS = {
    GeneralModel.QWEN_GGUF: (
        "4ca720788d1e01f1bff70c033e0d0028fd02e502@sha256:"
        "322e194ff79741c7baa497c240f677f54b201b0efab44ca8e50f122b39123482"
    ),
    GeneralModel.QWEN_FP8: "017b9c7af6b5689d5dd426a76e0bc077eb5ca20a",
    GeneralModel.QWEN_14B: "31c69efc29464b6bb0aee1398b5a7b50a99340c3",
    GeneralModel.QWEN_32B: "0499c3ac83fdef8810b907a23894ba91e95eddd8",
    GeneralModel.QWEN_BNB: "8aa5f05d26b7205477066e1449e0af13f762a299",
}


class GeneralSelection(BaseModel):
    model_config = ConfigDict(frozen=True)
    provider: ProviderKind = ProviderKind.OPENAI
    model: GeneralModel = GeneralModel.OPENAI_LUNA

    @model_validator(mode="after")
    def compatible_model(self) -> GeneralSelection:
        allowed = {
            ProviderKind.OPENAI: {GeneralModel.OPENAI_LUNA},
            ProviderKind.BEDROCK: {GeneralModel.BEDROCK_LUNA},
            ProviderKind.VLLM: set(REVISIONS) - {GeneralModel.QWEN_GGUF},
            # Adapter retained. New GGUF deployment choices require a catalog entry first.
            ProviderKind.LLAMA_CPP: {GeneralModel.QWEN_GGUF},
        }[self.provider]
        if self.model not in allowed:
            raise ValueError("model is not supported by the selected provider")
        return self

    @property
    def route(self) -> ModelRoute:
        alias = {
            ProviderKind.OPENAI: None,
            ProviderKind.BEDROCK: "general-dev-bedrock",
            ProviderKind.VLLM: "general-dev-gpu",
            ProviderKind.LLAMA_CPP: "general-dev-gpu",
        }[self.provider]
        return ModelRoute(provider=self.provider, model=self.model.value, endpoint_alias=alias)

    @property
    def revision(self) -> str | None:
        return REVISIONS.get(self.model)


class F2SllmModel(StrEnum):
    SLLM = "sllm"


class F2SttModel(StrEnum):
    STT = "stt"


class SttLanguage(StrEnum):
    KOREAN = "ko"
