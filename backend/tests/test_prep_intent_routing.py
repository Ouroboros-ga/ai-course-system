import asyncio

from app.platform.agents.contracts.llm import LLMResponse
from app.platform.agents.prep.actions import PrepAction, PrepIntentDecision
from app.platform.agents.prep.llm_adapter import PrepLLMAdapter


class CapturingStructuredLLM:
    def __init__(self):
        self.calls = []

    async def complete(self, *, messages, output_schema, options, trace_context):
        self.calls.append({
            "messages": messages,
            "output_schema": output_schema,
            "options": options,
            "trace_context": trace_context,
        })
        return LLMResponse(
            content='{"action":"organize_structure","confidence":0.94,"apply_immediately":true,"needs_clarification":false,"clarification":""}',
            parsed=PrepIntentDecision(
                action=PrepAction.ORGANIZE_STRUCTURE,
                confidence=0.94,
                apply_immediately=True,
            ),
        )


def test_prep_intent_adapter_uses_small_structured_router_call():
    port = CapturingStructuredLLM()
    adapter = PrepLLMAdapter(structured_llm=port)

    decision = asyncio.run(adapter.classify_intent({
        "instruction": "把课程目录整理得更适合教学，并直接应用",
        "selected_node": None,
        "allowed_actions": [
            {"action": "organize_structure", "scope": "全课程未锁定目录/节点结构"},
        ],
    }))

    assert decision.action == PrepAction.ORGANIZE_STRUCTURE
    assert decision.confidence == 0.94
    assert decision.apply_immediately is True
    call = port.calls[0]
    assert call["output_schema"] is PrepIntentDecision
    assert call["options"].max_tokens == 512
    assert call["trace_context"].node == "intent_routing"
    assert "不要按单个关键词匹配" in call["messages"][0]["content"]
