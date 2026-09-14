"""Exercise SDK serialization and local validation without an external API call."""

import json
from typing import Any

import httpx2 as httpx
import pytest
from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict

from brokerage_ai.core.errors import (
    ProviderConfigurationError,
    ProviderOutputInvalidError,
    ProviderRefusalError,
)
from brokerage_ai.core.types import ProviderKind
from brokerage_ai.f3.contracts import InferenceEvidence, QuoteEvidence
from brokerage_ai.f3.judgment_model_output import BrokerageJudgmentModelOutput
from brokerage_ai.f3.model_output import PositionCardModelOutput
from brokerage_ai.providers.openai import OpenAIAdapter
from brokerage_ai.providers.openai_schema import structured_output_schema
from conftest import generation_request


def card_payload() -> dict[str, Any]:
    return {
        "intent": {
            "value": "PRESENT",
            "evidence": [{"kind": "QUOTE", "interaction_id": 12, "quote_text": "매도 의뢰"}],
        },
        "urgency": {
            "value": "RELAXED",
            "evidence": [{"kind": "INFERENCE", "note": "마감 기한을 언급하지 않음"}],
        },
        "price": {"sale": None, "jeonse": None, "monthly_rent": None, "budget": None},
        "timing": {"hard_deadline": None, "constraints": []},
        "flexible": [],
        "inflexible": [],
        "contactability": {
            "status": "GOOD",
            "evidence": [{"kind": "QUOTE", "interaction_id": 12, "quote_text": "매도 의뢰"}],
        },
    }


def assert_wire_schema(node: dict[str, Any]) -> None:
    assert "oneOf" not in node
    assert "discriminator" not in node
    assert "default" not in node
    if node.get("type") == "object":
        assert node["additionalProperties"] is False
        assert set(node["required"]) == set(node["properties"])
    for keyword in ("$defs", "properties"):
        for child in node.get(keyword, {}).values():
            assert_wire_schema(child)
    for child in node.get("anyOf", []):
        assert_wire_schema(child)
    if isinstance(node.get("items"), dict):
        assert_wire_schema(node["items"])


@pytest.mark.parametrize(
    "outcome", ["valid", "missing_quote", "mixed_evidence", "refusal", "cutoff"]
)
@pytest.mark.parametrize("output_schema", [PositionCardModelOutput, BrokerageJudgmentModelOutput])
async def test_actual_f3_schema_crosses_sdk_http_boundary_and_revalidates(
    outcome: str, output_schema: type[BaseModel]
) -> None:
    original_schema = output_schema.model_json_schema()
    calls = []
    payload = card_payload()
    if outcome == "missing_quote":
        del payload["intent"]["evidence"][0]["quote_text"]
    elif outcome == "mixed_evidence":
        payload["intent"]["evidence"][0]["note"] = "not allowed on quote"

    if output_schema is BrokerageJudgmentModelOutput:
        payload = {
            "candidates": [
                {
                    "card_id": 2,
                    "grade": "WEAK",
                    "rank": 1,
                    "comparison_reason": "OVERALL_FIT",
                    "comparison_detail": "조건 추가 확인 필요",
                    "obstacle_reason": "NONE",
                    "obstacle_detail": None,
                    "concession_reason": "ADDITIONAL_CONFIRMATION",
                    "concession_detail": None,
                    "recommended_action": None,
                    "rejection_reason": None,
                    "rejection_detail": None,
                    "evidence_refs": [1],
                }
            ]
        }
        if outcome == "missing_quote":
            del payload["candidates"][0]["evidence_refs"]
        elif outcome == "mixed_evidence":
            payload["candidates"][0]["evidence"] = [payload["candidates"][0]["evidence_refs"]]

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/responses"
        sent = json.loads(request.content)
        calls.append(sent)
        assert sent["store"] is False
        wire = sent["text"]["format"]
        assert wire["name"] == output_schema.__name__
        assert wire["strict"] is True
        assert_wire_schema(wire["schema"])
        definitions = wire["schema"]["$defs"]
        if output_schema is PositionCardModelOutput:
            evidence = definitions["IntentAssessment"]["properties"]["evidence"]["items"]
            assert evidence["anyOf"] == [
                {"$ref": "#/$defs/QuoteEvidence"},
                {"$ref": "#/$defs/InferenceEvidence"},
            ]
        else:
            candidate = definitions["ModelCandidateJudgment"]["properties"]
            assert "evidence_refs" in candidate
            assert "evidence" not in candidate
        content = (
            {"type": "refusal", "refusal": "synthetic refusal"}
            if outcome == "refusal"
            else {"type": "output_text", "text": json.dumps(payload), "annotations": []}
        )
        return httpx.Response(
            200,
            json={
                "id": "resp_synthetic",
                "object": "response",
                "created_at": 0,
                "model": "test-model",
                "status": "incomplete" if outcome == "cutoff" else "completed",
                "incomplete_details": {"reason": "max_output_tokens"}
                if outcome == "cutoff"
                else None,
                "output": [
                    {
                        "type": "message",
                        "id": "msg_synthetic",
                        "role": "assistant",
                        "status": "completed",
                        "content": [content],
                    }
                ],
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 20,
                    "total_tokens": 30,
                    "input_tokens_details": {"cached_tokens": 0},
                    "output_tokens_details": {"reasoning_tokens": 0},
                },
            },
        )

    async with AsyncOpenAI(
        api_key="synthetic-test-key",
        base_url="https://synthetic.invalid/v1",
        max_retries=0,
        timeout=2,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    ) as client:
        adapter = OpenAIAdapter(client)
        if outcome == "valid":
            result = await adapter.generate_structured(
                generation_request(ProviderKind.OPENAI), output_schema
            )
            if isinstance(result.output, PositionCardModelOutput):
                assert isinstance(result.output.intent.evidence[0], QuoteEvidence)
                assert isinstance(result.output.urgency.evidence[0], InferenceEvidence)
            else:
                assert isinstance(result.output, BrokerageJudgmentModelOutput)
                assert result.output.candidates[0].evidence_refs == (1,)
            assert result.diagnostics.usage is not None
            assert result.diagnostics.usage.total_tokens == 30
        else:
            error = ProviderRefusalError if outcome == "refusal" else ProviderOutputInvalidError
            with pytest.raises(error):
                await adapter.generate_structured(
                    generation_request(ProviderKind.OPENAI), output_schema
                )
    assert len(calls) == 1
    assert output_schema.model_json_schema() == original_schema


@pytest.mark.parametrize("tagged", [False, True])
def test_overlapping_oneof_is_not_silently_relaxed(tagged: bool) -> None:
    # An arbitrary custom schema is not a Pydantic tagged union. Two equal tags
    # must also fail closed instead of accepting values that violate oneOf.
    union: dict[str, Any] = {
        "oneOf": [
            {"type": "object", "properties": {"kind": {"const": "same"}}},
            {"type": "object", "properties": {"kind": {"const": "same"}}},
        ]
    }
    if tagged:
        union["discriminator"] = {"propertyName": "kind"}

    class CustomOutput(BaseModel):
        model_config = ConfigDict(json_schema_extra={"properties": {"value": union}})
        value: str

    with pytest.raises(ProviderConfigurationError, match="distinct discriminator"):
        structured_output_schema(CustomOutput)
