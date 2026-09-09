"""Adapt provider wire syntax while keeping the original Pydantic contract local."""

from typing import Any

from openai.lib._pydantic import to_strict_json_schema
from pydantic import BaseModel

from brokerage_ai.core.errors import ProviderConfigurationError


def structured_output_schema(model: type[BaseModel]) -> dict[str, Any]:
    # Reuse the installed SDK's strict required/additionalProperties/ref handling.
    # Mock HTTP tests exercise this internal SDK seam with the actual F3 output DTO.
    schema = to_strict_json_schema(model)

    def visit(node: dict[str, Any]) -> None:
        variants = node.get("oneOf")
        if variants is not None:
            discriminator = node.get("discriminator", {}).get("propertyName")
            tags: set[str] = set()
            for variant in variants:
                target = variant
                if "$ref" in target:
                    target = schema
                    for key in variant["$ref"].removeprefix("#/").split("/"):
                        target = target[key]
                tag = target.get("properties", {}).get(discriminator, {}).get("const")
                if not isinstance(tag, str) or tag in tags:
                    raise ProviderConfigurationError(
                        "OpenAI oneOf conversion requires distinct discriminator constants"
                    )
                tags.add(tag)
            # Distinct literal tags make these branches mutually exclusive, so anyOf
            # preserves oneOf semantics. Arbitrary overlapping unions are not relaxed.
            node["anyOf"] = node.pop("oneOf")
            node.pop("discriminator", None)
        # Required fields have no wire defaults, including tuple/object model defaults.
        node.pop("default", None)
        for keyword in ("$defs", "definitions", "properties"):
            for child in node.get(keyword, {}).values():
                visit(child)
        for keyword in ("anyOf", "allOf", "prefixItems"):
            for child in node.get(keyword, []):
                visit(child)
        for keyword in ("items", "additionalProperties"):
            child = node.get(keyword)
            if isinstance(child, dict):
                visit(child)

    visit(schema)
    return schema
