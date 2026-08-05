import pytest
from pydantic import ValidationError

from app.common.llm_client import LLMError, LLMResponse
from app.platform.agents.prep.llm_adapter import PrepLLMAdapter
from app.platform.agents.providers.llm.structured import SharedLLMStructuredProvider
from app.platform.agents.contracts.llm import LLMOptions, LLMTraceContext
from app.schemas.controlled_prep import (
    ControlledPrepInput,
    EvidenceReference,
    EvidenceSegmenterResult,
    EvidenceVerifierResult,
    OutlinePlannerResult,
    TeachingScriptBatchResult,
    TeachingScriptNodeDraft,
    TeachingStyleConfig,
)
from app.services.controlled_prep_workflow import ControlledPrepWorkflow, StructuredOutputError


class SequencedPrepStages:
    def __init__(self, payloads):
        self.payloads = iter(payloads)
        self.calls = []

    def _next(self, stage):
        self.calls.append(stage)
        return next(self.payloads)

    async def segment_evidence(self, _request):
        return EvidenceSegmenterResult.model_validate_json(self._next("segment_evidence"))

    async def plan_outline(self, _request, _segments):
        return OutlinePlannerResult.model_validate_json(self._next("plan_outline"))

    async def write_script(self, _request, _outline, _candidate_id):
        return TeachingScriptNodeDraft.model_validate_json(self._next("write_script"))

    async def write_scripts_batch(self, _request, _outline, _candidates):
        return TeachingScriptBatchResult.model_validate_json(
            self._next("write_scripts_batch")
        ).scripts

    async def verify_script(self, _request, _script):
        return EvidenceVerifierResult.model_validate_json(self._next("verify_script"))


def _request():
    return ControlledPrepInput(
        source_text="二分查找要求序列有序。\n\n查找区间不断缩小。",
        evidence=[EvidenceReference(evidence_id="es_1", text="二分查找要求序列有序", page=1)],
        course_positioning="面向初学者的算法课",
        style=TeachingStyleConfig(level="beginner"),
    )


def test_each_stage_uses_registered_prep_port_and_generates_local_node():
    llm = SequencedPrepStages([
        '{"stage":"evidence_segmenter","segments":[{"segment_id":"seg_1","title":"二分查找","topic":"有序序列查找","evidence_ids":["es_1"],"examples":[],"exercises":[]}]}',
        '{"stage":"outline_planner","candidates":[{"candidate_id":"kp_1","node_type":"section","title":"查找基础","parent_candidate_id":null,"evidence_ids":["es_1"],"rationale":""},{"candidate_id":"kp_2","node_type":"knowledge_point","title":"二分查找","parent_candidate_id":"kp_1","evidence_ids":["es_1"],"rationale":""}],"prerequisites":[]}',
        '{"stage":"script_writer","candidate_id":"kp_2","title":"二分查找","evidence_ids":["es_1"],"course_positioning":"初学者算法课","prerequisites":[],"style":{"level":"beginner","tone":"conversational","language":"zh-CN","include_examples":true,"include_practice_prompt":true},"content":"二分查找用于有序序列。","claims":["二分查找要求序列有序"],"paragraph_evidence":[["es_1"]]}',
        '{"stage":"evidence_verifier","verdict":"passed","findings":[{"claim":"二分查找要求序列有序","evidence_ids":["es_1"],"supported":true,"reason":"原文直接说明"}],"unsupported_paragraph_indexes":[]}',
    ])
    result = asyncio_run(ControlledPrepWorkflow(llm, max_retries=0).run(_request(), candidate_id="kp_2"))
    proposal = result["proposal"]
    assert llm.calls == ["segment_evidence", "plan_outline", "write_script", "verify_script"]
    assert {op.target for op in proposal.operations} == {"outline:new:title", "script:new:content"}
    assert all(op.evidence_refs == ["es_1"] for op in proposal.operations)


def test_unknown_evidence_is_rejected():
    llm = SequencedPrepStages([
        '{"stage":"evidence_segmenter","segments":[{"segment_id":"seg_1","title":"x","topic":"x","evidence_ids":["es_missing"],"examples":[],"exercises":[]}]}',
    ])
    with pytest.raises(StructuredOutputError):
        asyncio_run(ControlledPrepWorkflow(llm, max_retries=0).segment_evidence(_request()))


def test_requires_registered_prep_stage_port_instead_of_generic_chat():
    class GenericChatOnlyClient:
        async def chat(self, *_args, **_kwargs):
            raise AssertionError("legacy chat must not be called")

    with pytest.raises(StructuredOutputError, match="PREP_STRUCTURED_PORT_UNAVAILABLE"):
        asyncio_run(ControlledPrepWorkflow(GenericChatOnlyClient()).segment_evidence(_request()))


def test_multiple_knowledge_points_use_one_batch_script_request():
    llm = SequencedPrepStages([
        '{"stage":"evidence_segmenter","segments":[{"segment_id":"seg_1","title":"基础","topic":"基础","evidence_ids":["es_1"],"examples":[],"exercises":[]}]}',
        '{"stage":"outline_planner","candidates":[{"candidate_id":"sec","node_type":"section","title":"基础","parent_candidate_id":null,"evidence_ids":["es_1"],"rationale":""},{"candidate_id":"kp_1","node_type":"knowledge_point","title":"概念一","parent_candidate_id":"sec","evidence_ids":["es_1"],"rationale":""},{"candidate_id":"kp_2","node_type":"knowledge_point","title":"概念二","parent_candidate_id":"sec","evidence_ids":["es_1"],"rationale":""}],"prerequisites":[]}',
        '{"stage":"script_writer_batch","scripts":['
        '{"stage":"script_writer","candidate_id":"kp_1","title":"概念一","evidence_ids":["es_1"],"course_positioning":"算法课","prerequisites":[],"style":{"level":"beginner","tone":"conversational","language":"zh-CN","include_examples":true,"include_practice_prompt":true},"content":"概念一。","claims":["概念一"],"paragraph_evidence":[["es_1"]]},'
        '{"stage":"script_writer","candidate_id":"kp_2","title":"概念二","evidence_ids":["es_1"],"course_positioning":"算法课","prerequisites":[],"style":{"level":"beginner","tone":"conversational","language":"zh-CN","include_examples":true,"include_practice_prompt":true},"content":"概念二。","claims":["概念二"],"paragraph_evidence":[["es_1"]]}]}',
        '{"stage":"evidence_verifier","verdict":"passed","findings":[{"claim":"概念一","evidence_ids":["es_1"],"supported":true,"reason":""}],"unsupported_paragraph_indexes":[]}',
        '{"stage":"evidence_verifier","verdict":"passed","findings":[{"claim":"概念二","evidence_ids":["es_1"],"supported":true,"reason":""}],"unsupported_paragraph_indexes":[]}',
    ])
    stages = []
    result = asyncio_run(ControlledPrepWorkflow(llm, max_retries=0).run(
        _request(), on_stage=lambda stage, progress, _value: stages.append((stage, progress)),
    ))
    assert len(result["scripts"]) == 2
    assert llm.calls.count("write_scripts_batch") == 1
    assert len(llm.calls) == 5
    assert stages[0] == ("evidence", 0)
    assert ("evidence", 10) in stages
    assert ("outline", 30) in stages
    assert ("scripts", 80) in stages
    assert stages[-1] == ("verification", 95)


def test_wrapped_response_format_rejection_uses_adapter_fallback_without_format():
    """The real prep adapter must not restore a rejected response format."""
    class SharedGatewayWithoutResponseFormat:
        def __init__(self):
            self.calls = []

        async def chat(self, messages, **kwargs):
            self.calls.append({"messages": messages, "kwargs": kwargs})
            if "response_format" in kwargs:
                raise LLMError(
                    "LLM API请求失败: 400",
                    status_code=400,
                    reason_code="response_format_unsupported",
                )
            return LLMResponse(
                content='{"stage":"evidence_segmenter","segments":[{"segment_id":"seg_1","title":"二分查找","topic":"有序序列查找","evidence_ids":["es_1"],"examples":[],"exercises":[]}]}',
                usage={}, model="gateway", finish_reason="stop", latency_ms=1,
            )

    gateway = SharedGatewayWithoutResponseFormat()
    adapter = PrepLLMAdapter(structured_llm=SharedLLMStructuredProvider(client=gateway))
    result = asyncio_run(ControlledPrepWorkflow(adapter, max_retries=0).segment_evidence(_request()))

    assert result.segments[0].evidence_ids == ["es_1"]
    assert gateway.calls[0]["kwargs"]["response_format"]["type"] == "json_object"
    assert "response_format" not in gateway.calls[1]["kwargs"]
    assert "JSON Schema" in gateway.calls[1]["messages"][-1].content


def test_structure_planner_uses_sparse_schema_and_disables_reasoning_budget():
    class CapturingStructured:
        def __init__(self):
            self.options = None
            self.schema = None

        async def complete(self, *, options, output_schema, **_kwargs):
            self.options = options
            self.schema = output_schema
            return type("Response", (), {
                "parsed": output_schema.model_validate({"summary": "no change", "operations": []}),
                "content": '{"summary":"no change","operations":[]}',
            })()

    port = CapturingStructured()
    adapter = PrepLLMAdapter(structured_llm=port)
    result = asyncio_run(adapter.plan_incremental({
        "batch_action": "organize_structure",
        "structure_mode": True,
        "editable_outline": [],
        "course_context": {},
    }))

    assert result.operations == []
    assert port.schema.__name__ == "StructurePlan"
    assert port.options.max_tokens == 12000
    assert port.options.provider_options == {"thinking": {"type": "disabled"}}


def test_structure_planner_passes_deepseek_thinking_disabled_to_shared_gateway():
    """The raw provider request must retain the vendor switch, not just the Port option."""
    class CapturingGateway:
        def __init__(self):
            self.kwargs = None

        async def chat(self, _messages, **kwargs):
            self.kwargs = kwargs
            return LLMResponse(
                content='{"summary":"no change","operations":[]}',
                usage={}, model="gateway", finish_reason="stop", latency_ms=1,
            )

    gateway = CapturingGateway()
    adapter = PrepLLMAdapter(
        structured_llm=SharedLLMStructuredProvider(client=gateway),
    )
    result = asyncio_run(adapter.plan_incremental({
        "batch_action": "organize_structure",
        "structure_mode": True,
        "editable_outline": [],
        "course_context": {},
    }))

    assert result.operations == []
    assert gateway.kwargs["thinking"] == {"type": "disabled"}
    assert gateway.kwargs["max_tokens"] == 12000


def test_sparse_structure_schema_accepts_minimal_title_and_rejects_audit_fields():
    from app.services.course_prep_agent_service import StructurePlan

    plan = StructurePlan.model_validate({
        "summary": "clean titles",
        "operations": [{"node_id": "node_1", "title": "发动机结构"}],
    })
    assert plan.operations[0].title == "发动机结构"
    with pytest.raises(ValidationError):
        StructurePlan.model_validate({
            "summary": "invalid",
            "operations": [{
                "node_id": "node_1", "title": "发动机结构", "reason": "should be server owned",
            }],
        })
    with pytest.raises(ValidationError):
        StructurePlan.model_validate({
            "summary": "invalid root metadata",
            "operations": [],
            "reason": "root-level audit metadata is not allowed",
        })


def test_structured_repair_merges_nested_usage_without_type_error():
    """Repair success must not fail when the gateway returns usage details."""

    class GatewayWithUsageDetails:
        def __init__(self):
            self.calls = 0

        async def chat(self, _messages, **_kwargs):
            self.calls += 1
            usage = {
                "prompt_tokens": self.calls,
                "completion_tokens": self.calls,
                "prompt_tokens_details": {"cached_tokens": self.calls},
                "completion_tokens_details": {"reasoning_tokens": self.calls},
            }
            if self.calls == 1:
                return LLMResponse(
                    content='{"invalid":true}',
                    usage=usage,
                    model="gateway",
                    finish_reason="stop",
                    latency_ms=1,
                )
            return LLMResponse(
                content='{"stage":"evidence_segmenter","segments":[{"segment_id":"seg_1","title":"二分查找","topic":"有序序列查找","evidence_ids":["es_1"],"examples":[],"exercises":[]}]}',
                usage=usage,
                model="gateway",
                finish_reason="stop",
                latency_ms=1,
            )

    gateway = GatewayWithUsageDetails()
    provider = SharedLLMStructuredProvider(client=gateway)
    response = asyncio_run(provider.complete(
        messages=[{"role": "user", "content": "请返回 JSON"}],
        output_schema=EvidenceSegmenterResult,
        options=LLMOptions(response_format={"type": "json_object"}),
        trace_context=LLMTraceContext(purpose="test repair usage merge"),
    ))

    assert gateway.calls == 2
    assert response.repaired is True
    assert response.parsed is not None
    assert response.usage["prompt_tokens"] == 3
    assert response.usage["prompt_tokens_details"]["cached_tokens"] == 3
    assert response.usage["completion_tokens_details"]["reasoning_tokens"] == 3


def test_structured_repair_prompt_contains_schema_and_field_errors():
    """A repair attempt must explain the exact contract violation."""

    class GatewayWithInvalidRepair:
        def __init__(self):
            self.calls = []

        async def chat(self, messages, **_kwargs):
            self.calls.append(messages)
            return LLMResponse(
                content='{"invalid":true}',
                usage={},
                model="gateway",
                finish_reason="stop",
                latency_ms=1,
            )

    gateway = GatewayWithInvalidRepair()
    provider = SharedLLMStructuredProvider(client=gateway)
    with pytest.raises(StructuredOutputError) as captured:
        asyncio_run(provider.complete(
            messages=[{"role": "user", "content": "请返回 JSON"}],
            output_schema=EvidenceSegmenterResult,
            options=LLMOptions(response_format={"type": "json_object"}),
            trace_context=LLMTraceContext(node="segment_evidence"),
        ))

    assert len(gateway.calls) == 2
    repair_prompt = gateway.calls[1][-1].content
    assert "JSON Schema" in repair_prompt
    assert "Validation errors" in repair_prompt
    assert "segment_evidence" in repair_prompt
    assert captured.value.reason_code == "structured_output_invalid"
    assert captured.value.stage == "segment_evidence"
    assert captured.value.attempts == 2
    assert captured.value.validation_errors


def test_schema_forbids_arbitrary_markdown_shape():
    with pytest.raises(ValidationError):
        EvidenceReference(evidence_id="es_1", text="x", unexpected="nope")


def asyncio_run(awaitable):
    import asyncio
    return asyncio.run(awaitable)
