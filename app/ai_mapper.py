from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from app.models import PROFILE_FIELDS, FieldMetadata


LOGGER = logging.getLogger(__name__)
UNAUTHORIZED_FALLBACK_LOG = "AI provider unauthorized. Falling back to heuristic detection."


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


def merge_ai_mappings(
    mappings_list: list[dict[str, dict[str, Any]]], 
    strategy: str = "average"
) -> dict[str, dict[str, Any]]:
    """
    Merge multiple AI mappings from concurrent model calls.
    
    Parameters
    ----------
    mappings_list : list[dict]
        List of mappings from different AI models.
    strategy : str
        Merge strategy: "average" (avg confidence), "highest" (highest confidence), or "consensus" (agreement required)
    
    Returns
    -------
    dict
        Merged mappings with combined confidence scores.
    """
    if not mappings_list:
        return {}
    
    if len(mappings_list) == 1:
        return mappings_list[0]
    
    # Collect all selector-field pairs with their confidence scores
    field_votes: dict[str, dict[str, list[float]]] = {}
    
    for mapping in mappings_list:
        for selector, item in mapping.items():
            if selector not in field_votes:
                field_votes[selector] = {}
            profile_field = item["profile_field"]
            confidence = item["confidence"]
            if profile_field not in field_votes[selector]:
                field_votes[selector][profile_field] = []
            field_votes[selector][profile_field].append(confidence)
    
    # Merge results based on strategy
    merged = {}
    
    for selector, field_confidences in field_votes.items():
        if strategy == "consensus":
            # Only accept if all models agree on the same field
            if len(field_confidences) == 1:
                field = list(field_confidences.keys())[0]
                avg_confidence = sum(field_confidences[field]) / len(field_confidences[field])
                merged[selector] = {"profile_field": field, "confidence": avg_confidence}
        elif strategy == "highest":
            # Select field with highest average confidence across models
            best_field = max(field_confidences.keys(), key=lambda f: sum(field_confidences[f]) / len(field_confidences[f]))
            avg_confidence = sum(field_confidences[best_field]) / len(field_confidences[best_field])
            merged[selector] = {"profile_field": best_field, "confidence": avg_confidence}
        else:  # "average" - default
            # Select field with highest average confidence
            best_field = max(field_confidences.keys(), key=lambda f: sum(field_confidences[f]) / len(field_confidences[f]))
            avg_confidence = sum(field_confidences[best_field]) / len(field_confidences[best_field])
            merged[selector] = {"profile_field": best_field, "confidence": avg_confidence}
    
    return merged


class AIFormMapper:
    def __init__(self, config: dict[str, Any]) -> None:
        self.enabled = bool(config.get("enabled", False))
        self.concurrent_mode = bool(config.get("concurrent", False))
        self.merge_strategy = config.get("merge_strategy", "average")  # "average", "highest", "consensus"
        
        # Single model mode (backward compatible)
        self.provider = config.get("provider", "openai-compatible")
        self.base_url = config.get("base_url") or os.getenv("AI_BASE_URL", "")
        self.api_key = config.get("api_key") or os.getenv("AI_API_KEY", "")
        self.model = config.get("model") or os.getenv("AI_MODEL", "")
        
        # Concurrent mode: kimi and qwen
        self.kimi_base_url = config.get("kimi", {}).get("base_url") or os.getenv("KIMI_BASE_URL", "https://api.moonshot.ai/v1")
        self.kimi_api_key = config.get("kimi", {}).get("api_key") or os.getenv("MOONSHOT_API_KEY") or os.getenv("KIMI_API_KEY", "")
        self.kimi_model = config.get("kimi", {}).get("model") or os.getenv("KIMI_MODEL", "kimi-k2")
        
        self.qwen_base_url = config.get("qwen", {}).get("base_url") or os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        self.qwen_api_key = config.get("qwen", {}).get("api_key") or os.getenv("DASHSCOPE_API_KEY") or os.getenv("QWEN_API_KEY", "")
        self.qwen_model = config.get("qwen", {}).get("model") or os.getenv("QWEN_MODEL", "qwen-plus")
        
        self.confidence_threshold = float(config.get("confidence_threshold", 0.8))

    async def _call_ai_model(
        self,
        base_url: str,
        api_key: str,
        model: str,
        payload: list[dict[str, Any]],
        system_prompt: str,
        user_message: str,
    ) -> dict[str, dict[str, Any]]:
        """Call a single AI model and return parsed mappings."""
        import httpx

        if not base_url or not api_key or not model:
            LOGGER.warning(UNAUTHORIZED_FALLBACK_LOG)
            return {}

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    base_url.rstrip("/") + "/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={"model": model, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}], "temperature": 0},
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                LOGGER.warning(UNAUTHORIZED_FALLBACK_LOG)
                return {}
            raise

        content = response.json()["choices"][0]["message"]["content"]
        return parse_ai_mapping(content, {item["selector"] for item in payload})

    async def map_fields(self, fields: list[FieldMetadata]) -> dict[str, dict[str, Any]]:
        if not self.enabled:
            return {}

        payload = [field.to_ai_payload() for field in fields]
        system = (
            "Map website registration form fields to user profile fields. Return strict JSON only. "
            "Never invent data. Valid profile fields are: " + ", ".join(PROFILE_FIELDS) + "."
        )
        user = json.dumps({"fields": payload, "response_schema": {"mappings": {"<selector>": {"profile_field": "<field>", "confidence": 0.0}}}})

        if self.concurrent_mode:
            results = await asyncio.gather(
                self._call_ai_model(self.kimi_base_url, self.kimi_api_key, self.kimi_model, payload, system, user),
                self._call_ai_model(self.qwen_base_url, self.qwen_api_key, self.qwen_model, payload, system, user),
                return_exceptions=True,
            )

            mappings_list = []
            for i, result in enumerate(results):
                model_name = "Moonshot/Kimi" if i == 0 else "DashScope/Qwen"
                if isinstance(result, Exception):
                    LOGGER.warning("AI provider fallback after %s error: %s", model_name, result)
                    continue
                if result:
                    mappings_list.append(result)

            if not mappings_list:
                LOGGER.warning("AI provider fallback. Falling back to heuristic detection.")
                return {}
            return merge_ai_mappings(mappings_list, strategy=self.merge_strategy)

        try:
            return await self._call_ai_model(
                self.base_url, self.api_key, self.model, payload, system, user
            )
        except Exception as exc:
            LOGGER.warning("AI provider fallback. Falling back to heuristic detection: %s", exc)
            return {}

