from __future__ import annotations

import json
import os
from typing import Any


from app.models import PROFILE_FIELDS, FieldMetadata


class AIMapperError(ValueError):
    pass


def parse_ai_mapping(raw: str, valid_selectors: set[str]) -> dict[str, dict[str, Any]]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AIMapperError("AI response must be valid JSON") from exc
    if not isinstance(parsed, dict) or "mappings" not in parsed:
        raise AIMapperError("AI response must contain a mappings object")
    mappings = parsed["mappings"]
    if not isinstance(mappings, dict):
        raise AIMapperError("mappings must be an object")
    validated: dict[str, dict[str, Any]] = {}
    for selector, item in mappings.items():
        if selector not in valid_selectors:
            raise AIMapperError(f"Unknown selector returned by AI: {selector}")
        if not isinstance(item, dict):
            raise AIMapperError("Each mapping value must be an object")
        profile_field = item.get("profile_field")
        confidence = item.get("confidence", 0)
        if profile_field not in PROFILE_FIELDS:
            raise AIMapperError(f"Invalid profile field: {profile_field}")
        if not isinstance(confidence, int | float) or not 0 <= float(confidence) <= 1:
            raise AIMapperError("confidence must be a number between 0 and 1")
        validated[selector] = {"profile_field": profile_field, "confidence": float(confidence)}
    return validated


class AIFormMapper:
    def __init__(self, config: dict[str, Any]) -> None:
        self.enabled = bool(config.get("enabled", False))
        self.provider = config.get("provider", "openai-compatible")
        self.base_url = config.get("base_url") or os.getenv("AI_BASE_URL", "")
        self.api_key = config.get("api_key") or os.getenv("AI_API_KEY", "")
        self.model = config.get("model") or os.getenv("AI_MODEL", "")
        self.confidence_threshold = float(config.get("confidence_threshold", 0.8))

    async def map_fields(self, fields: list[FieldMetadata]) -> dict[str, dict[str, Any]]:
        if not self.enabled:
            return {}
        if not self.base_url or not self.api_key or not self.model:
            raise AIMapperError("AI mapping enabled but base_url, api_key, or model is missing")
        payload = [field.to_ai_payload() for field in fields]
        system = (
            "Map website registration form fields to user profile fields. Return strict JSON only. "
            "Never invent data. Valid profile fields are: " + ", ".join(PROFILE_FIELDS) + "."
        )
        user = json.dumps({"fields": payload, "response_schema": {"mappings": {"<selector>": {"profile_field": "<field>", "confidence": 0.0}}}})
        import httpx

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                self.base_url.rstrip("/") + "/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}], "temperature": 0},
            )
            response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return parse_ai_mapping(content, {field.selector for field in fields})
