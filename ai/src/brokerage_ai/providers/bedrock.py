from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from time import perf_counter
from typing import Protocol, TypeVar

import httpx
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import ReadOnlyCredentials
from botocore.exceptions import BotoCoreError, NoCredentialsError
from botocore.session import Session, get_session
from pydantic import BaseModel, ValidationError

from brokerage_ai.core.errors import (
    ProviderConfigurationError,
    ProviderOutputInvalidError,
    ProviderRateLimitError,
    ProviderRefusalError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    describe_validation_error,
)
from brokerage_ai.core.types import (
    ProviderDiagnostics,
    ProviderKind,
    StructuredGenerationRequest,
    StructuredGenerationResult,
    TokenUsage,
)

OutputT = TypeVar("OutputT", bound=BaseModel)

_BEDROCK_SIGNING_SERVICE = "bedrock"
_SCHEMA_INSTRUCTION = """Return exactly one JSON object and no Markdown or explanatory text.
The JSON object must satisfy this JSON Schema:
{schema}"""


class AwsCredentialLoader(Protocol):
    def __call__(self) -> ReadOnlyCredentials: ...


def create_default_aws_credential_loader(
    session: Session | None = None,
) -> AwsCredentialLoader:
    """Create a reusable loader backed by botocore's standard credential chain."""

    resolved_session = session or get_session()

    def load() -> ReadOnlyCredentials:
        credentials = resolved_session.get_credentials()
        if credentials is None:
            raise NoCredentialsError()
        return credentials.get_frozen_credentials()

    return load


class BedrockAdapter:
    """OpenAI-compatible Bedrock Responses adapter using AWS SigV4."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        base_url: str,
        aws_region: str,
        credential_loader: AwsCredentialLoader,
    ) -> None:
        self._client = client
        self._responses_url = f"{base_url.rstrip('/')}/responses"
        self._aws_region = aws_region
        self._credential_loader = credential_loader

    @property
    def kind(self) -> ProviderKind:
        return ProviderKind.BEDROCK

    async def generate_structured(
        self,
        request: StructuredGenerationRequest,
        output_schema: type[OutputT],
    ) -> StructuredGenerationResult[OutputT]:
        if request.route.provider is not self.kind:
            raise ProviderConfigurationError(
                f"{self.kind.value} adapter cannot handle {request.route.provider.value} route"
            )

        body = _request_body(request, output_schema)
        started_at = perf_counter()
        credentials = await self._load_credentials()
        headers = self._signed_headers(body, credentials)
        try:
            response = await self._client.post(
                self._responses_url,
                content=body,
                headers=headers,
            )
        except httpx.TimeoutException:
            raise ProviderTimeoutError() from None
        except httpx.RequestError:
            raise ProviderUnavailableError() from None
        latency_ms = (perf_counter() - started_at) * 1000

        _raise_for_status(response.status_code)
        payload = _response_payload(response)
        output = _validated_output(payload, output_schema)
        diagnostics = _diagnostics(payload, latency_ms)
        return StructuredGenerationResult[OutputT](output=output, diagnostics=diagnostics)

    async def _load_credentials(self) -> ReadOnlyCredentials:
        try:
            return await asyncio.to_thread(self._credential_loader)
        except NoCredentialsError:
            raise ProviderConfigurationError("bedrock AWS credentials are not configured") from None
        except BotoCoreError:
            raise ProviderUnavailableError() from None

    def _signed_headers(
        self,
        body: bytes,
        credentials: ReadOnlyCredentials,
    ) -> dict[str, str]:
        aws_request = AWSRequest(
            method="POST",
            url=self._responses_url,
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            SigV4Auth(credentials, _BEDROCK_SIGNING_SERVICE, self._aws_region).add_auth(aws_request)
        except BotoCoreError:
            raise ProviderUnavailableError() from None
        return {str(name): str(value) for name, value in aws_request.headers.items()}


def _request_body(
    request: StructuredGenerationRequest,
    output_schema: type[BaseModel],
) -> bytes:
    schema = json.dumps(
        output_schema.model_json_schema(),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    parameters: dict[str, object] = {
        "model": request.route.model,
        "input": [
            {"role": message.role.value, "content": message.content} for message in request.messages
        ],
        "instructions": _SCHEMA_INSTRUCTION.format(schema=schema),
        "store": False,
        "stream": False,
    }
    if request.temperature is not None:
        parameters["temperature"] = request.temperature
    if request.max_output_tokens is not None:
        parameters["max_output_tokens"] = request.max_output_tokens
    return json.dumps(
        parameters,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _raise_for_status(status_code: int) -> None:
    if 200 <= status_code < 300:
        return
    if status_code == 408:
        raise ProviderTimeoutError()
    if status_code == 429:
        raise ProviderRateLimitError()
    if status_code in {409, 424} or status_code >= 500:
        raise ProviderUnavailableError()
    if status_code in {401, 403}:
        raise ProviderConfigurationError("bedrock request authentication or authorization failed")
    raise ProviderResponseError()


def _response_payload(response: httpx.Response) -> Mapping[str, object]:
    try:
        payload = response.json()
    except (TypeError, ValueError):
        raise ProviderResponseError() from None
    if not isinstance(payload, dict):
        raise ProviderResponseError()
    return payload


def _validated_output[SchemaT: BaseModel](
    payload: Mapping[str, object],
    output_schema: type[SchemaT],
) -> SchemaT:
    status = payload.get("status")
    if status == "incomplete":
        raise ProviderOutputInvalidError("response is incomplete")
    if status != "completed":
        raise ProviderResponseError()

    outputs = payload.get("output")
    if not isinstance(outputs, list):
        raise ProviderResponseError()

    texts: list[str] = []
    found_message = False
    for output in outputs:
        if not isinstance(output, dict):
            raise ProviderResponseError()
        if output.get("type") != "message":
            continue
        found_message = True
        content = output.get("content")
        if not isinstance(content, list):
            raise ProviderResponseError()
        for part in content:
            if not isinstance(part, dict):
                raise ProviderResponseError()
            part_type = part.get("type")
            if part_type == "refusal":
                raise ProviderRefusalError()
            if part_type != "output_text":
                continue
            text = part.get("text")
            if not isinstance(text, str):
                raise ProviderResponseError()
            texts.append(text)

    if not found_message:
        raise ProviderResponseError()
    content = "".join(texts)
    if not content.strip():
        raise ProviderOutputInvalidError("response has no JSON content")
    try:
        return output_schema.model_validate_json(content)
    except ValidationError as exc:
        raise ProviderOutputInvalidError(describe_validation_error(exc)) from exc


def _diagnostics(
    payload: Mapping[str, object],
    latency_ms: float,
) -> ProviderDiagnostics:
    model = payload.get("model")
    request_id = payload.get("id")
    if not isinstance(model, str) or not model or not isinstance(request_id, str) or not request_id:
        raise ProviderResponseError()

    usage_payload = payload.get("usage")
    usage: TokenUsage | None = None
    if usage_payload is not None:
        if not isinstance(usage_payload, dict):
            raise ProviderResponseError()
        input_tokens = _token_count(usage_payload.get("input_tokens"))
        output_tokens = _token_count(usage_payload.get("output_tokens"))
        total_tokens = _token_count(usage_payload.get("total_tokens"))
        usage = TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
        )

    return ProviderDiagnostics(
        provider=ProviderKind.BEDROCK,
        model=model,
        request_id=request_id,
        latency_ms=latency_ms,
        usage=usage,
    )


def _token_count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProviderResponseError()
    return value
