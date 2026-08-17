from pydantic import BaseModel

from brokerage_ai.core.types import (
    ChatMessage,
    EmbeddingRequest,
    MessageRole,
    ModelRoute,
    ProviderKind,
    StructuredGenerationRequest,
)


class Answer(BaseModel):
    value: str


def generation_request(provider: ProviderKind) -> StructuredGenerationRequest:
    return StructuredGenerationRequest(
        route=ModelRoute(provider=provider, model="test-model"),
        messages=(ChatMessage(role=MessageRole.USER, content="test input"),),
        temperature=0.2,
        max_output_tokens=64,
    )


def embedding_request(provider: ProviderKind) -> EmbeddingRequest:
    return EmbeddingRequest(
        route=ModelRoute(provider=provider, model="embedding-model"),
        inputs=("first", "second"),
        dimensions=2,
    )
