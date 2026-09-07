import json
from collections.abc import Callable

import httpx
import pytest
from botocore.credentials import Credentials, ReadOnlyCredentials
from botocore.exceptions import NoCredentialsError

from brokerage_ai.core.errors import (
    ProviderConfigurationError,
    ProviderOutputInvalidError,
    ProviderRateLimitError,
    ProviderRefusalError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from brokerage_ai.core.types import (
    ChatMessage,
    MessageRole,
    ModelRoute,
    ProviderKind,
    StructuredGenerationRequest,
)
from brokerage_ai.providers.bedrock import BedrockAdapter
from brokerage_ai.providers.repair import generate_with_repair
from conftest import Answer

_BASE_URL = "https://bedrock-runtime.ap-northeast-2.amazonaws.com/openai/v1"


def _request() -> StructuredGenerationRequest:
    return StructuredGenerationRequest(
        route=ModelRoute(
            provider=ProviderKind.BEDROCK,
            model="global.openai.gpt-5.6-luna",
            endpoint_alias="general-dev-bedrock",
        ),
        messages=(ChatMessage(role=MessageRole.USER, content="test input"),),
        temperature=0.2,
        max_output_tokens=64,
    )


def _credentials(access_key: str = "test-access-key") -> ReadOnlyCredentials:
    return Credentials(access_key, "test-secret-key", "test-session-token").get_frozen_credentials()


def _payload(content: str = '{"value":"ok"}') -> dict[str, object]:
    return {
        "id": "resp_bedrock",
        "model": "global.openai.gpt-5.6-luna",
        "status": "completed",
        "output": [
            {
                "type": "reasoning",
                "summary": [],
            },
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": content}],
            },
        ],
        "usage": {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14},
    }


def _adapter(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    credential_loader: Callable[[], ReadOnlyCredentials] = _credentials,
) -> tuple[BedrockAdapter, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return (
        BedrockAdapter(
            client,
            base_url=_BASE_URL,
            aws_region="ap-northeast-2",
            credential_loader=credential_loader,
        ),
        client,
    )


@pytest.mark.asyncio
async def test_bedrock_signs_responses_request_and_locally_validates_output() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=_payload())

    adapter, client = _adapter(handler)
    async with client:
        result = await adapter.generate_structured(_request(), Answer)

    assert result.output == Answer(value="ok")
    assert result.diagnostics.provider is ProviderKind.BEDROCK
    assert result.diagnostics.model == "global.openai.gpt-5.6-luna"
    assert result.diagnostics.request_id == "resp_bedrock"
    assert result.diagnostics.usage is not None
    assert result.diagnostics.usage.total_tokens == 14

    sent = captured[0]
    assert str(sent.url) == f"{_BASE_URL}/responses"
    assert sent.headers["authorization"].startswith("AWS4-HMAC-SHA256 Credential=test-access-key/")
    assert sent.headers["x-amz-security-token"] == "test-session-token"
    body = json.loads(sent.content)
    assert body["model"] == "global.openai.gpt-5.6-luna"
    assert body["store"] is False
    assert body["stream"] is False
    assert body["temperature"] == 0.2
    assert body["max_output_tokens"] == 64
    assert body["input"] == [{"role": "user", "content": "test input"}]
    assert "JSON Schema" in body["instructions"]
    assert '"value"' in body["instructions"]
    assert "response_format" not in body


@pytest.mark.asyncio
async def test_bedrock_loads_fresh_credentials_for_every_request() -> None:
    access_keys = ["first-access-key", "second-access-key"]
    load_count = 0
    seen_authorization: list[str] = []

    def load_credentials() -> ReadOnlyCredentials:
        nonlocal load_count
        key = access_keys[load_count]
        load_count += 1
        return _credentials(key)

    def handler(request: httpx.Request) -> httpx.Response:
        seen_authorization.append(request.headers["authorization"])
        return httpx.Response(200, json=_payload())

    adapter, client = _adapter(handler, credential_loader=load_credentials)
    async with client:
        await adapter.generate_structured(_request(), Answer)
        await adapter.generate_structured(_request(), Answer)

    assert "Credential=first-access-key/" in seen_authorization[0]
    assert "Credential=second-access-key/" in seen_authorization[1]
    assert load_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["", "not-json", "{}"])
async def test_bedrock_invalid_output_is_retryable(content: str) -> None:
    adapter, client = _adapter(lambda _: httpx.Response(200, json=_payload(content)))

    async with client:
        with pytest.raises(ProviderOutputInvalidError) as caught:
            await adapter.generate_structured(_request(), Answer)

    assert caught.value.retryable is True


@pytest.mark.asyncio
async def test_bedrock_invalid_output_uses_existing_repair_limit() -> None:
    request_count = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(200, json=_payload("not-json"))

    adapter, client = _adapter(handler)
    async with client:
        with pytest.raises(ProviderOutputInvalidError):
            await generate_with_repair(
                provider=adapter,
                request=_request(),
                output_schema=Answer,
                finalize=lambda produced: produced.output,
            )

    assert request_count == 3


@pytest.mark.asyncio
async def test_bedrock_incomplete_response_is_retryable() -> None:
    payload = _payload()
    payload["status"] = "incomplete"
    adapter, client = _adapter(lambda _: httpx.Response(200, json=payload))

    async with client:
        with pytest.raises(ProviderOutputInvalidError, match="response is incomplete"):
            await adapter.generate_structured(_request(), Answer)


@pytest.mark.asyncio
async def test_bedrock_refusal_is_rejected_without_exposing_body() -> None:
    payload = _payload()
    payload["output"] = [
        {
            "type": "message",
            "content": [{"type": "refusal", "refusal": "sensitive refusal detail"}],
        }
    ]
    adapter, client = _adapter(lambda _: httpx.Response(200, json=payload))

    async with client:
        with pytest.raises(ProviderRefusalError) as caught:
            await adapter.generate_structured(_request(), Answer)

    assert "sensitive refusal detail" not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (408, ProviderTimeoutError),
        (401, ProviderConfigurationError),
        (403, ProviderConfigurationError),
        (429, ProviderRateLimitError),
        (424, ProviderUnavailableError),
        (500, ProviderUnavailableError),
        (400, ProviderResponseError),
    ],
)
async def test_bedrock_http_status_uses_safe_provider_errors(
    status: int,
    error_type: type[Exception],
) -> None:
    adapter, client = _adapter(lambda _: httpx.Response(status, text="sensitive provider response"))

    async with client:
        with pytest.raises(error_type) as caught:
            await adapter.generate_structured(_request(), Answer)

    assert "sensitive provider response" not in str(caught.value)


@pytest.mark.asyncio
async def test_bedrock_timeout_is_translated_without_request_details() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("sensitive timeout", request=request)

    adapter, client = _adapter(handler)
    async with client:
        with pytest.raises(ProviderTimeoutError) as caught:
            await adapter.generate_structured(_request(), Answer)

    assert "sensitive timeout" not in str(caught.value)


@pytest.mark.asyncio
async def test_bedrock_missing_aws_credentials_fails_before_network_call() -> None:
    called = False

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json=_payload())

    def missing_credentials() -> ReadOnlyCredentials:
        raise NoCredentialsError()

    adapter, client = _adapter(handler, credential_loader=missing_credentials)
    async with client:
        with pytest.raises(ProviderConfigurationError, match="credentials are not configured"):
            await adapter.generate_structured(_request(), Answer)

    assert called is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="not-json"),
        httpx.Response(200, json=[]),
        httpx.Response(200, json={"id": "x", "model": "m", "status": "completed"}),
        httpx.Response(
            200,
            json={
                **_payload(),
                "usage": {"input_tokens": 1, "output_tokens": "2", "total_tokens": 3},
            },
        ),
    ],
)
async def test_bedrock_malformed_response_structure_is_rejected(
    response: httpx.Response,
) -> None:
    adapter, client = _adapter(lambda _: response)

    async with client:
        with pytest.raises(ProviderResponseError):
            await adapter.generate_structured(_request(), Answer)


@pytest.mark.asyncio
async def test_bedrock_adapter_rejects_wrong_provider_route() -> None:
    adapter, client = _adapter(lambda _: httpx.Response(200, json=_payload()))
    wrong_route = _request().model_copy(
        update={
            "route": ModelRoute(provider=ProviderKind.VLLM, model="other-model"),
        }
    )

    async with client:
        with pytest.raises(ProviderConfigurationError, match="cannot handle vllm route"):
            await adapter.generate_structured(wrong_route, Answer)
