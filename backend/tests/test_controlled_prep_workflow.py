import asyncio
import json
import math

import pytest
from pydantic import ValidationError

from app.common.llm_client import LLMError, LLMResponse
from app.platform.agents.prep.llm_adapter import PrepLLMAdapter
from app.platform.agents.providers.llm.structured import SharedLLMStructuredProvider
from app.platform.agents.shared.error_messages import safe_prep_error_message
from app.platform.agents.contracts.llm import LLMOptions, LLMTraceContext
from app.schemas.controlled_prep import (
    ControlledPrepInput,
    EvidenceMapSegment,
    EvidenceReference,
    EvidenceSegment,
    EvidenceSegmentMapResult,
    EvidenceSegmenterResult,
    EvidenceVerifierResult,
    OutlinePlannerResult,
    TeachingScriptBatchResult,
    TeachingScriptNodeDraft,
    TeachingStyleConfig,
)
from app.services.controlled_prep_workflow import ControlledPrepWorkflow, StructuredOutputError
from app.services.course_initial_prep_service import InitialCoursePrepService
from app.models.document_parse_model import DocumentBlock


class SequencedPrepStages:
    def __init__(self, payloads):
        self.payloads = iter(payloads)
        self.calls = []
        self.kwargs = []

    def _next(self, stage):
        self.calls.append(stage)
        return next(self.payloads)

    async def segment_evidence(self, _request):
        return EvidenceSegmenterResult.model_validate_json(self._next("segment_evidence"))

    async def plan_outline(self, _request, _segments):
        return OutlinePlannerResult.model_validate_json(self._next("plan_outline"))

    async def write_script(self, _request, _outline, _candidate_id, **_kwargs):
        self.kwargs.append(("write_script", _candidate_id, dict(_kwargs)))
        return TeachingScriptNodeDraft.model_validate_json(self._next("write_script"))

    async def write_scripts_batch(self, _request, _outline, _candidates, **_kwargs):
        self.kwargs.append((
            "write_scripts_batch",
            [candidate.candidate_id for candidate in _candidates],
            dict(_kwargs),
        ))
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
                content='{"stage":"evidence_segmenter","segments":[{"segment_id":"seg_1","title":"二分查找","topic":"有序序列查找","examples":[],"exercises":[]}]}',
                usage={}, model="gateway", finish_reason="stop", latency_ms=1,
            )

    gateway = SharedGatewayWithoutResponseFormat()
    adapter = PrepLLMAdapter(structured_llm=SharedLLMStructuredProvider(client=gateway))
    result = asyncio_run(ControlledPrepWorkflow(adapter, max_retries=0).segment_evidence(_request()))

    assert result.segments[0].evidence_ids == ["es_1"]
    assert gateway.calls[0]["kwargs"]["response_format"]["type"] == "json_object"
    assert gateway.calls[0]["kwargs"]["thinking"] == {"type": "disabled"}
    assert gateway.calls[0]["kwargs"]["max_tokens"] == 4096
    assert "JSON Schema" in gateway.calls[0]["messages"][-1].content
    assert "source_text" not in "\n".join(message.content for message in gateway.calls[0]["messages"])
    assert "response_format" not in gateway.calls[1]["kwargs"]
    assert "JSON Schema" in gateway.calls[1]["messages"][-1].content


def test_reduce_stably_deduplicates_and_caps_examples_and_exercises():
    class CapturingStructured:
        def __init__(self):
            self.schema = None
            self.messages = None

        async def complete(self, *, messages, output_schema, **_kwargs):
            self.schema = output_schema
            self.messages = messages
            payload = {
                "stage": "evidence_segmenter",
                "segments": [{
                    "segment_id": "seg_1",
                    "title": "bounded suggestions",
                    "topic": "bounded suggestions",
                    "examples": [
                        " example-0 ",
                        "example-0",
                        *[f"example-{index}" for index in range(1, 15)],
                    ],
                    "exercises": [f"exercise-{index}" for index in range(15)],
                }],
            }
            return type("Response", (), {
                "parsed": output_schema.model_validate(payload),
                "content": json.dumps(payload),
            })()

    port = CapturingStructured()
    adapter = PrepLLMAdapter(structured_llm=port)
    result = asyncio_run(adapter.reduce_evidence([EvidenceSegment(
        segment_id="local",
        title="local",
        topic="local",
        evidence_ids=["es_1"],
    )]))

    assert port.schema.__name__ == "EvidenceReduceResult"
    wire_schema = port.schema.model_json_schema()
    segment_schema = wire_schema["$defs"]["EvidenceReduceSegment"]
    assert segment_schema["properties"]["examples"]["maxItems"] == 10
    assert segment_schema["properties"]["exercises"]["maxItems"] == 10
    # The wire schema never exposes evidence identifiers to the model.
    assert "evidence_ids" not in segment_schema["properties"]
    assert result.segments[0].examples == [f"example-{index}" for index in range(10)]
    assert result.segments[0].exercises == [f"exercise-{index}" for index in range(10)]
    # The program backfills the input group's deterministic union.
    assert result.segments[0].evidence_ids == ["es_1"]
    constraints = json.loads(port.messages[1]["content"])["constraints"]
    assert constraints["max_examples_per_segment"] == 10
    assert constraints["max_exercises_per_segment"] == 10


def test_reduce_repair_response_with_fifteen_items_is_safely_normalized():
    """A repaired Reduce response may repeat the same bounded-list violation."""

    examples = [f"example-{index}" for index in range(15)]
    exercises = [f"exercise-{index}" for index in range(15)]

    class RepairingGateway:
        def __init__(self):
            self.calls = 0

        async def chat(self, _messages, **_kwargs):
            self.calls += 1
            segment = {
                "segment_id": "seg_1",
                "title": "repair result",
                "examples": examples,
                "exercises": exercises,
            }
            if self.calls == 2:
                segment["topic"] = "repair result"
            return LLMResponse(
                content=json.dumps({
                    "stage": "evidence_segmenter",
                    "segments": [segment],
                }),
                usage={},
                model="gateway",
                finish_reason="stop",
                latency_ms=1,
            )

    gateway = RepairingGateway()
    adapter = PrepLLMAdapter(
        structured_llm=SharedLLMStructuredProvider(client=gateway),
    )
    result = asyncio_run(adapter.reduce_evidence([EvidenceSegment(
        segment_id="local",
        title="local",
        topic="local",
        evidence_ids=["es_1"],
    )]))

    assert gateway.calls == 2
    assert result.segments[0].examples == examples[:10]
    assert result.segments[0].exercises == exercises[:10]
    assert result.segments[0].evidence_ids == ["es_1"]


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


def _script_json(candidate_id: str, evidence_id: str = "es_1") -> str:
    return (
        '{"stage":"script_writer","candidate_id":"%s","title":"概念",'
        '"evidence_ids":["%s"],"course_positioning":"算法课","prerequisites":[],'
        '"style":{"level":"beginner","tone":"conversational","language":"zh-CN",'
        '"include_examples":true,"include_practice_prompt":true},'
        '"content":"概念讲解。","claims":["概念"],"paragraph_evidence":[["%s"]]}'
    ) % (candidate_id, evidence_id, evidence_id)


def _verifier_json(evidence_id: str = "es_1") -> str:
    return (
        '{"stage":"evidence_verifier","verdict":"passed","findings":'
        '[{"claim":"概念","evidence_ids":["%s"],"supported":true,"reason":""}],'
        '"unsupported_paragraph_indexes":[]}'
    ) % evidence_id


def test_truncated_batch_splits_in_half_and_recovers():
    """P2: a batch truncated by the completion budget must split and retry
    instead of failing the whole first draft."""
    from app.platform.agents.contracts.llm import StructuredOutputError

    class TruncateOnceBatchStages:
        def __init__(self, payloads):
            self.payloads = iter(payloads)
            self.calls = []
            self.batch_attempts = 0

        def _next(self, stage):
            self.calls.append(stage)
            return next(self.payloads)

        async def segment_evidence(self, _request):
            return EvidenceSegmenterResult.model_validate_json(self._next("segment_evidence"))

        async def plan_outline(self, _request, _segments):
            return OutlinePlannerResult.model_validate_json(self._next("plan_outline"))

        async def write_script(self, _request, _outline, _candidate_id, **_kwargs):
            self.calls.append("write_script")
            return TeachingScriptNodeDraft.model_validate_json(self._next("write_script"))

        async def write_scripts_batch(self, _request, _outline, _candidates, **_kwargs):
            self.calls.append("write_scripts_batch")
            self.batch_attempts += 1
            if self.batch_attempts == 1:
                raise StructuredOutputError(
                    "truncated",
                    reason_code="MODEL_OUTPUT_TRUNCATED",
                    stage="write_scripts_batch",
                    attempts=1,
                    truncated=True,
                )
            return TeachingScriptBatchResult.model_validate_json(
                self._next("write_scripts_batch")
            ).scripts

        async def verify_script(self, _request, _script):
            return EvidenceVerifierResult.model_validate_json(self._next("verify_script"))

    kp_ids = [f"kp_{index}" for index in range(1, 4)]
    outline_payload = {
        "stage": "outline_planner",
        "candidates": [
            {
                "candidate_id": "sec",
                "node_type": "section",
                "title": "基础",
                "parent_candidate_id": None,
                "evidence_ids": ["es_1"],
                "rationale": "",
            },
            *[
                {
                    "candidate_id": kp_id,
                    "node_type": "knowledge_point",
                    "title": f"概念{index}",
                    "parent_candidate_id": "sec",
                    "evidence_ids": ["es_1"],
                    "rationale": "",
                }
                for index, kp_id in enumerate(kp_ids, start=1)
            ],
        ],
        "prerequisites": [],
    }
    llm = TruncateOnceBatchStages([
        '{"stage":"evidence_segmenter","segments":[{"segment_id":"seg_1","title":"基础","topic":"基础","evidence_ids":["es_1"],"examples":[],"exercises":[]}]}',
        json_dumps(outline_payload),
        # After the first truncated call, the 3-node group splits into
        # [kp_1] and [kp_2,kp_3] (midpoint = 3 // 2); each half succeeds.
        '{"stage":"script_writer_batch","scripts":[%s]}' % _script_json(kp_ids[0]),
        '{"stage":"script_writer_batch","scripts":[%s]}' % ",".join(_script_json(kp_id) for kp_id in kp_ids[1:]),
        *[_verifier_json() for _ in kp_ids],
    ])
    result = asyncio_run(ControlledPrepWorkflow(llm, max_retries=0).run(_request()))
    assert len(result["scripts"]) == 3
    assert llm.batch_attempts == 3  # 1 truncated + 2 successful halves
    assert llm.calls.count("write_script") == 0
    assert llm.calls.count("verify_script") == 3


def test_many_knowledge_points_split_into_bounded_batch_requests():
    """P0: more KPs than the configured batch size must use several requests."""
    kp_ids = [f"kp_{index}" for index in range(1, 5)]
    outline_payload = {
        "stage": "outline_planner",
        "candidates": [
            {
                "candidate_id": "sec",
                "node_type": "section",
                "title": "基础",
                "parent_candidate_id": None,
                "evidence_ids": ["es_1"],
                "rationale": "",
            },
            *[
                {
                    "candidate_id": kp_id,
                    "node_type": "knowledge_point",
                    "title": f"概念{index}",
                    "parent_candidate_id": "sec",
                    "evidence_ids": ["es_1"],
                    "rationale": "",
                }
                for index, kp_id in enumerate(kp_ids, start=1)
            ],
        ],
        "prerequisites": [],
    }
    batch_payloads = [
        '{"stage":"script_writer_batch","scripts":[%s]}' % ",".join(
            _script_json(kp_id) for kp_id in group
        )
        for group in (kp_ids[:3], kp_ids[3:])
    ]
    llm = SequencedPrepStages([
        '{"stage":"evidence_segmenter","segments":[{"segment_id":"seg_1","title":"基础","topic":"基础","evidence_ids":["es_1"],"examples":[],"exercises":[]}]}',
        json_dumps(outline_payload),
        *batch_payloads,
        *[_verifier_json() for _ in kp_ids],
    ])
    result = asyncio_run(ControlledPrepWorkflow(llm, max_retries=0).run(_request()))
    assert len(result["scripts"]) == 4
    assert llm.calls.count("write_scripts_batch") == 2
    assert llm.calls.count("write_script") == 0
    batch_groups = [item[1] for item in llm.kwargs if item[0] == "write_scripts_batch"]
    assert batch_groups == [kp_ids[:3], kp_ids[3:]]
    assert all(
        item[2]["max_tokens"] == 4096
        for item in llm.kwargs if item[0] == "write_scripts_batch"
    )


def test_oversized_single_knowledge_point_uses_larger_single_node_budget():
    """P2: a node whose estimated output exceeds the group budget must fall
    back to the single-node writer with a larger completion budget."""
    long_text = "内燃机工作原理" * 700  # ~4900 chars -> estimate > 4096
    request = ControlledPrepInput(
        source_text=long_text,
        evidence=[
            EvidenceReference(evidence_id="es_big", text=long_text, page=1),
            EvidenceReference(evidence_id="es_small", text="短证据", page=2),
        ],
        course_positioning="算法课",
        style=TeachingStyleConfig(level="beginner"),
    )
    outline_payload = {
        "stage": "outline_planner",
        "candidates": [
            {
                "candidate_id": "sec",
                "node_type": "section",
                "title": "基础",
                "parent_candidate_id": None,
                "evidence_ids": ["es_small"],
                "rationale": "",
            },
            {
                "candidate_id": "kp_big",
                "node_type": "knowledge_point",
                "title": "大知识点",
                "parent_candidate_id": "sec",
                "evidence_ids": ["es_big"],
                "rationale": "",
            },
            {
                "candidate_id": "kp_small",
                "node_type": "knowledge_point",
                "title": "小知识点",
                "parent_candidate_id": "sec",
                "evidence_ids": ["es_small"],
                "rationale": "",
            },
        ],
        "prerequisites": [],
    }
    llm = SequencedPrepStages([
        '{"stage":"evidence_segmenter","segments":[{"segment_id":"seg_1","title":"基础","topic":"基础","evidence_ids":["es_small"],"examples":[],"exercises":[]}]}',
        json_dumps(outline_payload),
        _script_json("kp_big", "es_big"),
        '{"stage":"script_writer_batch","scripts":[%s]}' % _script_json("kp_small", "es_small"),
        _verifier_json("es_big"),
        _verifier_json("es_small"),
    ])
    result = asyncio_run(ControlledPrepWorkflow(llm, max_retries=0).run(request))
    assert len(result["scripts"]) == 2
    assert llm.calls.count("write_script") == 1
    assert llm.calls.count("write_scripts_batch") == 1
    script_kwargs = [item[2] for item in llm.kwargs if item[0] == "write_script"]
    assert script_kwargs[0]["max_tokens"] == 12288
    batch_kwargs = [item[2] for item in llm.kwargs if item[0] == "write_scripts_batch"]
    assert batch_kwargs[0]["max_tokens"] == 4096


def test_initial_input_coalesces_tiny_blocks_and_preserves_source_ids():
    blocks = [
        DocumentBlock(
            course_id=1,
            run_id="run_1",
            block_id=f"blk_{index:03d}",
            page_number=index // 4 + 1,
            page_or_slide=index // 4 + 1,
            order_index=index,
            semantic_role="body",
            text=f"fragment {index:03d} " + ("x" * 30),
        )
        for index in range(120)
    ]
    evidence, stats = InitialCoursePrepService._build_agent_input(
        blocks,
        {"run_1": "textbook"},
        {"run_1": "material_1"},
    )
    repeated, repeated_stats = InitialCoursePrepService._build_agent_input(
        blocks,
        {"run_1": "textbook"},
        {"run_1": "material_1"},
    )

    assert stats.sampled is False
    assert stats == repeated_stats
    assert len(evidence) < len(blocks)
    assert all(len(item.text) <= 2400 for item in evidence)
    assert [item.evidence_id for item in evidence] == [item.evidence_id for item in repeated]
    assert {
        block_id
        for item in evidence
        for block_id in item.source_block_ids
    } == {block.block_id for block in blocks}


def test_large_fragmented_corpus_fits_bounded_map_requests():
    blocks = [
        DocumentBlock(
            course_id=1,
            run_id="run_large",
            block_id=f"blk_{page:03d}_{index:02d}",
            page_number=page,
            page_or_slide=page,
            order_index=index,
            semantic_role="body",
            text=f"{page:03d}-{index:02d}-" + ("x" * 20),
        )
        for page in range(1, 576)
        for index in range(37)
    ]
    evidence, stats = InitialCoursePrepService._build_agent_input(
        InitialCoursePrepService._ordered_blocks(blocks, {"run_large": "textbook"}),
        {"run_large": "textbook"},
        {"run_large": "material_large"},
    )
    request = ControlledPrepInput(evidence=evidence, course_positioning="large corpus")
    workflow = ControlledPrepWorkflow()
    chunks = workflow._chunk_evidence(request)

    assert len(blocks) == 21275
    assert stats.sampled is False
    assert len(evidence) == 575
    assert len(chunks) <= 25
    assert max(sum(len(item.text) for item in chunk) for chunk in chunks) <= 24000
    assert max(workflow._evidence_payload_chars(request, chunk) for chunk in chunks) <= 36000


def test_evidence_map_reduce_bounds_payload_and_concurrency(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "PREP_INITIAL_EVIDENCE_MAP_TEXT_CHARS", 1000)
    monkeypatch.setattr(settings, "PREP_INITIAL_EVIDENCE_MAP_PAYLOAD_CHARS", 10000)
    monkeypatch.setattr(settings, "PREP_INITIAL_EVIDENCE_MAP_MAX_CHUNKS", 10)
    monkeypatch.setattr(settings, "PREP_INITIAL_EVIDENCE_CONCURRENCY", 2)
    monkeypatch.setattr(settings, "PREP_INITIAL_EVIDENCE_MAX_ATTEMPTS", 20)

    class MapReduceStages:
        def __init__(self):
            self.map_sizes = []
            self.reduce_calls = 0
            self.active = 0
            self.max_active = 0

        async def segment_evidence(self, request, **_kwargs):
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.map_sizes.append(sum(len(item.text) for item in request.evidence))
            await asyncio.sleep(0.01)
            self.active -= 1
            return EvidenceSegmentMapResult(segments=[EvidenceSegment(
                segment_id="local",
                title="local",
                topic="local",
                evidence_ids=[item.evidence_id for item in request.evidence],
            )])

        async def reduce_evidence(self, segments, **_kwargs):
            self.reduce_calls += 1
            evidence_ids = []
            for segment in segments:
                evidence_ids.extend(segment.evidence_ids)
            return EvidenceSegmenterResult(segments=[EvidenceSegment(
                segment_id="final",
                title="final",
                topic="final",
                evidence_ids=list(dict.fromkeys(evidence_ids)),
            )])

    request = ControlledPrepInput(
        evidence=[
            EvidenceReference(evidence_id=f"evg_{index}", text="x" * 800, page=index + 1)
            for index in range(4)
        ],
        course_positioning="bounded map reduce",
    )
    stages = MapReduceStages()
    result = asyncio_run(ControlledPrepWorkflow(stages).segment_evidence(request))

    assert len(stages.map_sizes) == 4
    assert max(stages.map_sizes) <= 1000
    assert stages.max_active == 2
    assert stages.reduce_calls == 1
    assert set(result.segments[0].evidence_ids) == {f"evg_{index}" for index in range(4)}


def test_truncated_evidence_map_recursively_bisects():
    class TruncatingMapStages:
        def __init__(self):
            self.group_sizes = []

        async def segment_evidence(self, request, **_kwargs):
            self.group_sizes.append(len(request.evidence))
            if len(request.evidence) > 1:
                raise StructuredOutputError(
                    "truncated",
                    reason_code="MODEL_OUTPUT_TRUNCATED",
                    stage="segment_evidence",
                    truncated=True,
                )
            item = request.evidence[0]
            return EvidenceSegmentMapResult(segments=[EvidenceSegment(
                segment_id="local",
                title="local",
                topic="local",
                evidence_ids=[item.evidence_id],
            )])

    request = ControlledPrepInput(evidence=[
        EvidenceReference(evidence_id="evg_1", text="first evidence"),
        EvidenceReference(evidence_id="evg_2", text="second evidence"),
    ])
    stages = TruncatingMapStages()
    result = asyncio_run(ControlledPrepWorkflow(stages).segment_evidence(request))

    assert stages.group_sizes == [2, 1, 1]
    assert len(result.segments) == 2


def test_evidence_attempt_budget_has_safe_teacher_message():
    error = StructuredOutputError(
        "internal budget detail",
        reason_code="PREP_EVIDENCE_BUDGET_EXCEEDED",
        stage="segment_evidence",
        attempts=40,
    )
    message = safe_prep_error_message(error)

    assert "材料证据整理" in message
    assert "系统未写入课程草稿" in message
    assert "internal budget detail" not in message


def test_reduce_lean_mode_uses_lean_schema_without_suggestions():
    class CapturingStructured:
        def __init__(self):
            self.schema = None
            self.messages = None

        async def complete(self, *, messages, output_schema, **_kwargs):
            self.schema = output_schema
            self.messages = messages
            payload = {
                "stage": "evidence_segmenter",
                "segments": [{
                    "segment_id": "seg_1",
                    "title": "lean",
                    "topic": "lean",
                }],
            }
            return type("Response", (), {
                "parsed": output_schema.model_validate(payload),
                "content": json.dumps(payload),
            })()

    port = CapturingStructured()
    adapter = PrepLLMAdapter(structured_llm=port)
    result = asyncio_run(adapter.reduce_evidence(
        [EvidenceSegment(
            segment_id="local",
            title="local",
            topic="local",
            evidence_ids=["es_1"],
        )],
        lean=True,
    ))

    assert port.schema.__name__ == "LeanEvidenceReduceResult"
    constraints = json.loads(port.messages[1]["content"])["constraints"]
    assert constraints["max_examples_per_segment"] == 0
    assert constraints["max_exercises_per_segment"] == 0
    assert result.segments[0].examples == []
    assert result.segments[0].exercises == []
    assert result.segments[0].evidence_ids == ["es_1"]


def test_map_backfills_batch_ids_and_never_exposes_evidence_ids():
    class CapturingStructured:
        def __init__(self):
            self.schema = None
            self.messages = None

        async def complete(self, *, messages, output_schema, **_kwargs):
            self.schema = output_schema
            self.messages = messages
            payload = {
                "stage": "evidence_segmenter",
                "segments": [{
                    "segment_id": "seg_1",
                    "title": "topic one",
                    "topic": "topic one",
                }],
            }
            return type("Response", (), {
                "parsed": output_schema.model_validate(payload),
                "content": json.dumps(payload),
            })()

    port = CapturingStructured()
    adapter = PrepLLMAdapter(structured_llm=port)
    request = ControlledPrepInput(evidence=[
        EvidenceReference(evidence_id="es_1", text="first"),
        EvidenceReference(evidence_id="es_2", text="second"),
    ])
    result = asyncio_run(adapter.segment_evidence(request))

    assert port.schema.__name__ == "EvidenceSegmentMapWireResult"
    segment_schema = port.schema.model_json_schema()["$defs"]["EvidenceMapSegment"]
    assert "evidence_ids" not in segment_schema["properties"]
    # The model never even sees evidence ids inside the evidence items.
    request_payload = json.loads(port.messages[1]["content"])
    for item in request_payload["evidence"]:
        assert "evidence_id" not in item
    # The program attributes the whole input batch to every segment.
    assert result.segments[0].evidence_ids == ["es_1", "es_2"]


def test_map_stably_deduplicates_and_caps_examples_and_exercises():
    """An over-produced Map response is normalized like Reduce, not rejected."""

    class CapturingStructured:
        def __init__(self):
            self.schema = None

        async def complete(self, *, messages, output_schema, **_kwargs):
            self.schema = output_schema
            payload = {
                "stage": "evidence_segmenter",
                "segments": [{
                    "segment_id": "seg_1",
                    "title": "topic one",
                    "topic": "topic one",
                    "examples": [
                        " example-0 ",
                        "example-0",
                        *[f"example-{index}" for index in range(1, 15)],
                    ],
                    "exercises": [f"exercise-{index}" for index in range(15)],
                }],
            }
            return type("Response", (), {
                "parsed": output_schema.model_validate(payload),
                "content": json.dumps(payload),
            })()

    port = CapturingStructured()
    adapter = PrepLLMAdapter(structured_llm=port)
    request = ControlledPrepInput(evidence=[
        EvidenceReference(evidence_id="es_1", text="first"),
        EvidenceReference(evidence_id="es_2", text="second"),
    ])
    result = asyncio_run(adapter.segment_evidence(request))

    assert port.schema.__name__ == "EvidenceSegmentMapWireResult"
    assert result.segments[0].examples == [f"example-{index}" for index in range(10)]
    assert result.segments[0].exercises == [f"exercise-{index}" for index in range(10)]
    assert result.segments[0].evidence_ids == ["es_1", "es_2"]


def test_map_wire_drops_nested_stage_but_rejects_unknown_fields():
    """A nested per-segment ``stage`` is stripped; anything else stays strict."""

    class CapturingStructured:
        def __init__(self):
            self.schema = None

        async def complete(self, *, messages, output_schema, **_kwargs):
            self.schema = output_schema
            payload = {
                "stage": "evidence_segmenter",
                "segments": [{
                    "stage": "evidence_segmenter",
                    "segment_id": "seg_1",
                    "title": "topic one",
                    "topic": "topic one",
                }],
            }
            return type("Response", (), {
                "parsed": output_schema.model_validate(payload),
                "content": json.dumps(payload),
            })()

    port = CapturingStructured()
    adapter = PrepLLMAdapter(structured_llm=port)
    request = ControlledPrepInput(evidence=[
        EvidenceReference(evidence_id="es_1", text="first"),
    ])
    result = asyncio_run(adapter.segment_evidence(request))

    assert port.schema.__name__ == "EvidenceSegmentMapWireResult"
    assert result.segments[0].segment_id == "seg_1"
    assert result.segments[0].evidence_ids == ["es_1"]
    # Any other unknown field inside a segment is still strictly rejected.
    with pytest.raises(ValidationError):
        EvidenceMapSegment.model_validate({
            "segment_id": "seg_1",
            "title": "t",
            "topic": "t",
            "bogus": 1,
        })


def test_outline_and_script_and_verifier_backfill_from_input_scope():
    class SequencedStructured:
        def __init__(self, responses):
            self.responses = list(responses)
            self.calls = 0
            self.schemas = []

        async def complete(self, *, messages, output_schema, **_kwargs):
            self.schemas.append(output_schema.__name__)
            payload = self.responses[self.calls]
            self.calls += 1
            return type("Response", (), {
                "parsed": output_schema.model_validate(payload),
                "content": json.dumps(payload),
            })()

    outline_wire = {
        "stage": "outline_planner",
        "candidates": [{
            "candidate_id": "kp_1",
            "node_type": "knowledge_point",
            "title": "concept",
            "parent_candidate_id": None,
            "rationale": "",
        }],
        "prerequisites": [],
    }
    script_wire = {
        "stage": "script_writer",
        "candidate_id": "kp_1",
        "title": "concept",
        "course_positioning": "intro",
        "prerequisites": [],
        "style": {"level": "beginner", "tone": "calm", "language": "zh-CN"},
        "content": "第一段。\n\n第二段。",
        "claims": ["claim"],
    }
    verifier_wire = {
        "stage": "evidence_verifier",
        "verdict": "passed",
        "findings": [{"claim": "ok", "supported": True, "reason": ""}],
        "unsupported_paragraph_indexes": [],
    }

    port = SequencedStructured([outline_wire, script_wire, verifier_wire])
    adapter = PrepLLMAdapter(structured_llm=port)

    request = ControlledPrepInput(evidence=[
        EvidenceReference(evidence_id="es_1", text="first"),
        EvidenceReference(evidence_id="es_2", text="second"),
    ])
    segments = EvidenceSegmenterResult(segments=[
        EvidenceSegment(segment_id="s1", title="t", topic="t", evidence_ids=["es_1", "es_2"]),
    ])
    outline = asyncio_run(adapter.plan_outline(request, segments))
    script = asyncio_run(adapter.write_script(request, outline, "kp_1"))
    verification = asyncio_run(adapter.verify_script(request, script))

    assert port.schemas == [
        "OutlinePlannerWireResult",
        "ScriptWireDraft",
        "EvidenceVerifierWireResult",
    ]
    assert outline.candidates[0].evidence_ids == ["es_1", "es_2"]
    assert script.evidence_ids == ["es_1", "es_2"]
    assert script.paragraph_evidence == [["es_1", "es_2"], ["es_1", "es_2"]]
    assert verification.findings[0].evidence_ids == ["es_1", "es_2"]


def test_outline_backfill_caps_reference_set_to_proposal_limit():
    request = ControlledPrepInput(evidence=[
        EvidenceReference(evidence_id=f"es_{index}", text="x" * 8, page=index + 1)
        for index in range(120)
    ])
    segments = EvidenceSegmenterResult(segments=[EvidenceSegment(
        segment_id="s1",
        title="t",
        topic="t",
        evidence_ids=[f"es_{index}" for index in range(120)],
    )])

    class CapturingStructured:
        async def complete(self, *, messages, output_schema, **_kwargs):
            payload = {
                "stage": "outline_planner",
                "candidates": [{
                    "candidate_id": "kp_1",
                    "node_type": "knowledge_point",
                    "title": "concept",
                    "parent_candidate_id": None,
                    "rationale": "",
                }],
                "prerequisites": [],
            }
            return type("Response", (), {
                "parsed": output_schema.model_validate(payload),
                "content": json.dumps(payload),
            })()

    adapter = PrepLLMAdapter(structured_llm=CapturingStructured())
    outline = asyncio_run(adapter.plan_outline(request, segments))

    # PatchOperationDraft.evidence_refs caps at 100; the backfill must stay
    # within it while keeping a representative, deterministic subset.
    assert len(outline.candidates[0].evidence_ids) == 100
    assert set(outline.candidates[0].evidence_ids) <= {f"es_{index}" for index in range(120)}


def test_reduce_hierarchy_uses_lean_intermediate_and_full_final_level(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "PREP_INITIAL_EVIDENCE_MAP_TEXT_CHARS", 200)
    monkeypatch.setattr(settings, "PREP_INITIAL_EVIDENCE_MAP_PAYLOAD_CHARS", 1000)
    monkeypatch.setattr(settings, "PREP_INITIAL_EVIDENCE_MAP_MAX_CHUNKS", 10)
    monkeypatch.setattr(settings, "PREP_INITIAL_EVIDENCE_CONCURRENCY", 2)

    class HierarchyStages:
        def __init__(self):
            self.reduce_leans = []

        async def segment_evidence(self, request, **_kwargs):
            return EvidenceSegmentMapResult(segments=[
                EvidenceSegment(
                    segment_id=f"local_{index}_{half}",
                    title="local",
                    topic="local " + "x" * 60,
                    evidence_ids=[item.evidence_id for item in request.evidence],
                    examples=[f"example-{index}"],
                    exercises=[f"exercise-{index}"],
                )
                for index, item in enumerate(request.evidence)
                for half in range(2)
            ])

        async def reduce_evidence(self, segments, **_kwargs):
            self.reduce_leans.append(_kwargs.get("lean"))
            evidence_ids = []
            for segment in segments:
                evidence_ids.extend(segment.evidence_ids)
            return EvidenceSegmenterResult(segments=[EvidenceSegment(
                segment_id="merged",
                title="merged",
                topic="merged",
                evidence_ids=list(dict.fromkeys(evidence_ids)),
            )])

    request = ControlledPrepInput(evidence=[
        EvidenceReference(evidence_id=f"evg_{index}", text="x" * 150, page=index + 1)
        for index in range(4)
    ])
    stages = HierarchyStages()
    asyncio_run(ControlledPrepWorkflow(stages).segment_evidence(request))

    # Only the final single-group level re-adds examples/exercises; every
    # intermediate level merges on the lean summary to stay inside the
    # completion budget.
    assert len(stages.reduce_leans) >= 2
    assert stages.reduce_leans[-1] is False
    assert all(stages.reduce_leans[:-1])


def test_run_concurrent_cancels_in_flight_siblings_on_failure():
    outcomes: list[str] = []

    async def slow():
        try:
            await asyncio.sleep(0.2)
        except asyncio.CancelledError:
            outcomes.append("cancelled")
            raise
        outcomes.append("completed")

    async def boom():
        outcomes.append("boom")
        raise StructuredOutputError(
            "budget exhausted",
            reason_code="PREP_EVIDENCE_BUDGET_EXCEEDED",
            stage="segment_evidence_reduce",
        )

    async def scenario():
        with pytest.raises(StructuredOutputError):
            await ControlledPrepWorkflow._run_concurrent([
                slow(),
                boom(),
                slow(),
            ])
        # The failing sibling raises while the survivors are cancelled rather
        # than leaking in-flight LLM requests into the background.
        assert outcomes.count("cancelled") == 2
        assert outcomes.count("completed") == 0
        assert "boom" in outcomes

    asyncio_run(scenario())


def test_group_evidence_ids_expand_to_canonical_block_ids():
    evidence = [EvidenceReference(
        evidence_id="evg_1",
        text="grounded evidence",
        block_id="blk_1",
        source_block_ids=["blk_1", "blk_2"],
    )]
    outline = OutlinePlannerResult.model_validate({
        "stage": "outline_planner",
        "candidates": [{
            "candidate_id": "kp_1",
            "node_type": "knowledge_point",
            "title": "concept",
            "parent_candidate_id": None,
            "evidence_ids": ["evg_1"],
            "rationale": "",
        }],
        "prerequisites": [],
    })
    script = TeachingScriptNodeDraft.model_validate_json(_script_json("kp_1", "evg_1"))
    verification = EvidenceVerifierResult.model_validate_json(_verifier_json("evg_1"))
    expanded = InitialCoursePrepService._expand_prepared_evidence(
        {
            "outline": outline,
            "scripts": [script],
            "verifications": [verification],
            "proposal": None,
        },
        evidence,
    )

    assert expanded["outline"].candidates[0].evidence_ids == ["blk_1", "blk_2"]
    assert expanded["scripts"][0].evidence_ids == ["blk_1", "blk_2"]
    assert expanded["scripts"][0].paragraph_evidence == [["blk_1", "blk_2"]]
    assert expanded["verifications"][0].findings[0].evidence_ids == ["blk_1", "blk_2"]


def _multi_segment_map_stage() -> list[EvidenceReference]:
    return [
        EvidenceReference(evidence_id=f"evg_{i}", text="x" * 150, page=i + 1)
        for i in range(6)
    ]


def test_reduce_must_compress_target_reaches_intermediate_levels(monkeypatch):
    """Intermediate reduce groups receive both a preferred (ceil(n * ratio))
    and a hard ceiling (ceil(n * hard_ratio)) while the final single-group
    level stays exempt."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "PREP_INITIAL_EVIDENCE_MAP_TEXT_CHARS", 400)
    monkeypatch.setattr(settings, "PREP_INITIAL_EVIDENCE_MAP_PAYLOAD_CHARS", 1200)
    monkeypatch.setattr(settings, "PREP_INITIAL_EVIDENCE_MAP_MAX_CHUNKS", 10)
    monkeypatch.setattr(settings, "PREP_INITIAL_EVIDENCE_CONCURRENCY", 2)
    monkeypatch.setattr(settings, "PREP_INITIAL_EVIDENCE_REDUCE_RATIO", 0.25)
    monkeypatch.setattr(settings, "PREP_INITIAL_EVIDENCE_REDUCE_HARD_RATIO", 0.5)

    class CompressingReduce:
        def __init__(self):
            self.calls = []

        async def segment_evidence(self, request, **_kwargs):
            return EvidenceSegmentMapResult(segments=[
                EvidenceSegment(
                    segment_id=f"local_{index}",
                    title="local",
                    topic="t" + "x" * 120,
                    evidence_ids=[item.evidence_id],
                )
                for index, item in enumerate(request.evidence)
            ])

        async def reduce_evidence(self, segments, **_kwargs):
            self.calls.append((len(segments), _kwargs.get("preferred_target")))
            evidence_ids = []
            for segment in segments:
                evidence_ids.extend(segment.evidence_ids)
            return EvidenceSegmenterResult(segments=[EvidenceSegment(
                segment_id="merged",
                title="merged",
                topic="merged",
                evidence_ids=list(dict.fromkeys(evidence_ids)),
            )])

    request = ControlledPrepInput(evidence=_multi_segment_map_stage())
    stages = CompressingReduce()
    result = asyncio_run(ControlledPrepWorkflow(stages).segment_evidence(request))

    assert len(result.segments) == 1
    # Every intermediate group must receive its preferred contract
    # ceil(n * ratio); pass-through single-segment groups and the final level
    # stay exempt.  The parallel hard ceiling is validated by the group-level
    # progress tests below (it is workflow-internal and never sent to the LLM).
    intermediate = [call for call in stages.calls if call[1] is not None]
    assert intermediate, "expected at least one intermediate reduce group"
    for group_n, preferred in intermediate:
        assert preferred == max(1, min(32, math.ceil(group_n * 0.25)))
    assert any(call[1] is None for call in stages.calls)


def test_reduce_group_accepts_effective_progress_below_preferred_target(monkeypatch):
    """34 -> 10 style progress (shrunk but above the ideal target) is accepted:
    a 6-segment group with preferred 2 and hard 3 that returns 3 segments must
    pass without a retry, exactly as 34 -> 10 with preferred 9 and hard 17."""
    from app.core.config import settings
    from app.services.controlled_prep_workflow import EvidenceAttemptBudget

    monkeypatch.setattr(settings, "PREP_INITIAL_EVIDENCE_REDUCE_MAX_TOKENS", 16384)
    monkeypatch.setattr(settings, "COURSE_BUILD_STAGE_TIMEOUT_SECONDS", 60)

    class EffectiveProgressReduce:
        def __init__(self):
            self.reduce_calls = 0

        async def reduce_evidence(self, segments, **_kwargs):
            self.reduce_calls += 1
            evidence_ids = []
            for segment in segments:
                evidence_ids.extend(segment.evidence_ids)
            # Mirrors the real 34 -> 10 case: keeps 3 of 6 segments, which is
            # at the hard ceiling (3) but above the preferred target (2).
            return EvidenceSegmenterResult(segments=[
                EvidenceSegment(
                    segment_id="merged",
                    title="merged",
                    topic="merged",
                    evidence_ids=list(dict.fromkeys(evidence_ids)),
                )
                for _ in range(3)
            ])

    segments = [
        EvidenceSegment(
            segment_id=f"s_{index}",
            title="t",
            topic="x" * 120,
            evidence_ids=["evg_1"],
        )
        for index in range(6)
    ]
    request = ControlledPrepInput(evidence=[EvidenceReference(
        evidence_id="evg_1", text="evidence", page=1,
    )])
    stages = EffectiveProgressReduce()
    workflow = ControlledPrepWorkflow(stages)
    budget = EvidenceAttemptBudget(160)
    result = asyncio_run(workflow._reduce_evidence_group(
        request,
        segments,
        path="0_1",
        semaphore=asyncio.Semaphore(2),
        budget=budget,
        lean=True,
        preferred_target=2,
        hard_limit=3,
    ))

    assert len(result) == 3
    # Real progress below the ideal must not trigger a retry.
    assert stages.reduce_calls == 1


def test_reduce_group_rejects_no_shrinkage_with_full_metrics(monkeypatch):
    """Stagnation (no shrink at all) retries once and then fails with
    PREP_EVIDENCE_REDUCE_NON_CONVERGENT carrying full metrics.  20 -> 20 is
    used because the wire schema itself caps output at 32 segments, so a
    realistic worst case is "same count as input", not "34 -> 34"."""
    from app.core.config import settings
    from app.services.controlled_prep_workflow import EvidenceAttemptBudget

    monkeypatch.setattr(settings, "PREP_INITIAL_EVIDENCE_REDUCE_MAX_TOKENS", 16384)
    monkeypatch.setattr(settings, "COURSE_BUILD_STAGE_TIMEOUT_SECONDS", 60)

    class StubbornReduce:
        def __init__(self):
            self.reduce_calls = 0

        async def reduce_evidence(self, segments, **_kwargs):
            self.reduce_calls += 1
            return EvidenceSegmenterResult(segments=[
                segment.model_copy(update={"segment_id": f"m_{index}"})
                for index, segment in enumerate(segments)
            ])

    segments = [
        EvidenceSegment(
            segment_id=f"s_{index}",
            title="t",
            topic="x" * 120,
            evidence_ids=["evg_1"],
        )
        for index in range(20)
    ]
    request = ControlledPrepInput(evidence=[EvidenceReference(
        evidence_id="evg_1", text="evidence", page=1,
    )])
    stages = StubbornReduce()
    workflow = ControlledPrepWorkflow(stages)
    budget = EvidenceAttemptBudget(160)
    with pytest.raises(StructuredOutputError) as excinfo:
        asyncio_run(workflow._reduce_evidence_group(
            request,
            segments,
            path="0_1",
            semaphore=asyncio.Semaphore(2),
            budget=budget,
            lean=True,
            preferred_target=5,
            hard_limit=10,
        ))

    assert excinfo.value.reason_code == "PREP_EVIDENCE_REDUCE_NON_CONVERGENT"
    assert excinfo.value.stage == "segment_evidence_reduce"
    message = str(excinfo.value)
    # The message pinpoints the exact level/group and the safety metrics so a
    # teacher can diagnose from a single task number.
    assert "0_1" in message
    assert "input=20" in message
    assert "output=20" in message
    assert "retry_reason=no_shrinkage" in message
    assert stages.reduce_calls == 2


def test_initial_runtime_failure_preserves_reason_code():
    """The Initial Prep Runtime must carry the original failure classification
    (e.g. PREP_EVIDENCE_REDUCE_NON_CONVERGENT) so the outer handler can append
    the diagnostic id instead of falling back to a generic message."""
    from app.platform.tasks.handlers import _initial_runtime_failure

    failure = _initial_runtime_failure({
        "errors": [{
            "code": "INITIAL_BUILD_FAILED",
            "message": "材料已读取，但摘要没有在安全范围内收敛，系统未写入课程草稿；请重试，或减少材料数量后重新智能备课。",
            "reason_code": "PREP_EVIDENCE_REDUCE_NON_CONVERGENT",
            "stage": "segment_evidence_reduce",
            "error_type": "StructuredOutputError",
        }],
    })

    assert failure is not None
    assert failure.reason_code == "PREP_EVIDENCE_REDUCE_NON_CONVERGENT"
    # And the outer failure message now renders the accurate text with the
    # diagnostic id appended.
    from app.platform.tasks.handlers import _course_build_failure_message
    rendered = _course_build_failure_message(failure, run_id="prep_initial_cdbt_1")
    assert "没有在安全范围内收敛" in rendered
    assert "诊断编号：prep_initial_cdbt_1" in rendered
    assert "减少材料数量或拆分课程" not in rendered





def test_reduce_truncation_bisects_and_recovers(monkeypatch):
    """A truncated reduce response halves the group and recovers instead of
    failing the whole build or silently draining the budget."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "PREP_INITIAL_EVIDENCE_MAP_TEXT_CHARS", 400)
    monkeypatch.setattr(settings, "PREP_INITIAL_EVIDENCE_MAP_PAYLOAD_CHARS", 1200)
    monkeypatch.setattr(settings, "PREP_INITIAL_EVIDENCE_MAP_MAX_CHUNKS", 10)
    monkeypatch.setattr(settings, "PREP_INITIAL_EVIDENCE_CONCURRENCY", 2)

    class TruncatingThenCompressing:
        def __init__(self):
            self.reduce_calls = 0

        async def segment_evidence(self, request, **_kwargs):
            return EvidenceSegmentMapResult(segments=[
                EvidenceSegment(
                    segment_id=f"local_{index}",
                    title="local",
                    topic="t" + "x" * 120,
                    evidence_ids=[item.evidence_id],
                )
                for index, item in enumerate(request.evidence)
            ])

        async def reduce_evidence(self, segments, **_kwargs):
            self.reduce_calls += 1
            if self.reduce_calls == 1 and len(segments) > 1:
                raise StructuredOutputError(
                    "output truncated",
                    reason_code="MODEL_OUTPUT_TRUNCATED",
                    stage="segment_evidence_reduce",
                )
            evidence_ids = []
            for segment in segments:
                evidence_ids.extend(segment.evidence_ids)
            return EvidenceSegmenterResult(segments=[EvidenceSegment(
                segment_id="merged",
                title="merged",
                topic="merged",
                evidence_ids=list(dict.fromkeys(evidence_ids)),
            )])

    request = ControlledPrepInput(evidence=_multi_segment_map_stage())
    result = asyncio_run(
        ControlledPrepWorkflow(TruncatingThenCompressing()).segment_evidence(request)
    )
    assert len(result.segments) == 1


def test_reduce_non_convergence_fails_with_accurate_reason_code(monkeypatch):
    """A model that never compresses triggers PREP_EVIDENCE_REDUCE_NON_CONVERGENT
    after one targeted retry instead of a misleading budget-exceeded error."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "PREP_INITIAL_EVIDENCE_MAP_TEXT_CHARS", 400)
    monkeypatch.setattr(settings, "PREP_INITIAL_EVIDENCE_MAP_PAYLOAD_CHARS", 1200)
    monkeypatch.setattr(settings, "PREP_INITIAL_EVIDENCE_MAP_MAX_CHUNKS", 10)
    monkeypatch.setattr(settings, "PREP_INITIAL_EVIDENCE_CONCURRENCY", 2)

    class StubbornReduce:
        def __init__(self):
            self.reduce_calls = 0

        async def segment_evidence(self, request, **_kwargs):
            return EvidenceSegmentMapResult(segments=[
                EvidenceSegment(
                    segment_id=f"local_{index}",
                    title="local",
                    topic="t" + "x" * 120,
                    evidence_ids=[item.evidence_id],
                )
                for index, item in enumerate(request.evidence)
            ])

        async def reduce_evidence(self, segments, **_kwargs):
            self.reduce_calls += 1
            # Never compresses: mirrors every input segment unchanged.
            return EvidenceSegmenterResult(segments=[
                segment.model_copy(update={"segment_id": f"m_{self.reduce_calls}_{index}"})
                for index, segment in enumerate(segments)
            ])

    request = ControlledPrepInput(evidence=_multi_segment_map_stage())
    with pytest.raises(StructuredOutputError) as excinfo:
        asyncio_run(ControlledPrepWorkflow(StubbornReduce()).segment_evidence(request))

    assert excinfo.value.reason_code == "PREP_EVIDENCE_REDUCE_NON_CONVERGENT"
    assert excinfo.value.stage == "segment_evidence_reduce"


def test_prep_build_binds_diagnostic_context_to_run_and_trace():
    """A real build must persist LLM diagnostics under one run_id/trace_id so a
    failed build is traceable from its task number back to each LLM call."""
    from app.platform.agents.runtime.diagnostic_context import current_diagnostic_context
    from app.services.course_initial_prep_service import _run_prep_with_diagnostic_context

    seen: dict[str, str] = {}

    async def inner():
        context = current_diagnostic_context.get()
        seen["run_id"] = context.run_id
        seen["trace_id"] = context.trace_id
        seen["course_id"] = context.course_id
        return "ok"

    result = asyncio_run(_run_prep_with_diagnostic_context(
        course_id=7,
        build_task_id="bt_1",
        awaitable=inner(),
    ))

    assert result == "ok"
    assert seen["run_id"] == "prep_initial_bt_1"
    assert seen["course_id"] == "7"
    assert seen["trace_id"].startswith("trace_")
    # The context must be reset once the build finishes so later independent
    # LLM calls are not accidentally attributed to this build.
    assert current_diagnostic_context.get().run_id == ""


def json_dumps(value) -> str:
    import json
    return json.dumps(value, ensure_ascii=False)


def asyncio_run(awaitable):
    import asyncio
    return asyncio.run(awaitable)
