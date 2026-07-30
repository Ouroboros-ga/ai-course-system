"""Injectable OpenAI-compatible adapter; no node imports a vendor client."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Mapping

import httpx

from ...errors import LLMUnavailableError
from ...prompts.teaching import CONCEPT_SYSTEM, INTENT_SYSTEM, PROMPT_VERSION, RESPONSE_SYSTEM


@dataclass
class OpenAICompatibleTeachingLLM:
    base_url: str
    api_key: str
    model: str
    timeout_seconds: float = 20.0
    max_retries: int = 1
    client: httpx.AsyncClient | None = None

    async def _json_completion(self, *, system: str, user: str) -> Mapping[str, Any] | list[Any]:
        if not self.api_key:
            raise LLMUnavailableError("missing API key")
        own_client = self.client is None
        client = self.client or httpx.AsyncClient(timeout=self.timeout_seconds)
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }
        try:
            for attempt in range(self.max_retries + 1):
                try:
                    response = await client.post(f"{self.base_url.rstrip('/')}/chat/completions", headers={"Authorization": f"Bearer {self.api_key}"}, json=payload)
                    response.raise_for_status()
                    content = response.json()["choices"][0]["message"]["content"]
                    return json.loads(content)
                except (httpx.HTTPError, KeyError, ValueError, json.JSONDecodeError) as error:
                    if attempt >= self.max_retries:
                        raise LLMUnavailableError(f"structured completion failed: {type(error).__name__}") from error
                    await asyncio.sleep(0.1 * (attempt + 1))
        finally:
            if own_client:
                await client.aclose()
        raise LLMUnavailableError("unreachable completion state")

    async def detect_intent(self, *, message: str, course_id: str) -> Mapping[str, Any]:
        result = await self._json_completion(system=INTENT_SYSTEM, user=json.dumps({"course_id": course_id, "message": message, "prompt_version": PROMPT_VERSION}, ensure_ascii=False))
        return result if isinstance(result, Mapping) else {"intent": "other", "confidence": 0.0}

    async def extract_concept_candidates(self, *, message: str, course_id: str) -> list[Mapping[str, Any]]:
        result = await self._json_completion(system=CONCEPT_SYSTEM, user=json.dumps({"course_id": course_id, "message": message, "prompt_version": PROMPT_VERSION}, ensure_ascii=False))
        if isinstance(result, Mapping):
            result = result.get("candidates", [])
        return [item for item in result if isinstance(item, Mapping)] if isinstance(result, list) else []

    async def generate_teaching_response(self, *, context: Mapping[str, Any]) -> Mapping[str, Any]:
        result = await self._json_completion(system=RESPONSE_SYSTEM, user=json.dumps({"prompt_version": PROMPT_VERSION, **context}, ensure_ascii=False))
        return result if isinstance(result, Mapping) else {"answer": "", "citations": []}
