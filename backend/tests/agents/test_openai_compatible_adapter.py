from __future__ import annotations

import asyncio
import json
import unittest

import httpx

from app.platform.agents.tools.openai_compatible import OpenAICompatibleTeachingLLM


class OpenAICompatibleAdapterTests(unittest.TestCase):
    def test_structured_intent_uses_configured_model_without_network(self):
        seen = {}

        async def handler(request):
            seen.update(json.loads(request.content))
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"intent":"concept_question","confidence":0.8}'}}]})

        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                adapter = OpenAICompatibleTeachingLLM(base_url="https://fake.example/v1", api_key="test", model="model-test", client=client)
                return await adapter.detect_intent(message="什么是二分查找", course_id="c-1")

        result = asyncio.run(run())
        self.assertEqual("concept_question", result["intent"])
        self.assertEqual("model-test", seen["model"])
