"""Pydantic model → JSON Schema in the form Groq's strict structured outputs accept.

Strict mode rules (Groq docs): every property listed in `required`, every object has
`additionalProperties: false`, optional values expressed as a union with null, and only
basic keywords (type, properties, items, enum, anyOf, $ref/$defs, description)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

_KEEP = {
    "type",
    "properties",
    "required",
    "additionalProperties",
    "items",
    "enum",
    "anyOf",
    "$ref",
    "$defs",
    "description",
}


def _strictify(node: Any) -> Any:
    if isinstance(node, list):
        return [_strictify(n) for n in node]
    if not isinstance(node, dict):
        return node
    out: dict[str, Any] = {}
    for key, value in node.items():
        if key not in _KEEP:
            continue
        if key in ("properties", "$defs"):
            out[key] = {k: _strictify(v) for k, v in value.items()}
        else:
            out[key] = _strictify(value)
    if out.get("type") == "object" or "properties" in out:
        out["type"] = "object"
        out.setdefault("properties", {})
        out["required"] = list(out["properties"].keys())
        out["additionalProperties"] = False
    if "enum" in out and "type" not in out:
        values = out["enum"]
        if all(isinstance(v, str) for v in values):
            out["type"] = "string"
    return out


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    schema: dict[str, Any] = _strictify(model.model_json_schema())
    return schema


def schema_name(model: type[BaseModel]) -> str:
    return model.__name__.lower()[:64]
