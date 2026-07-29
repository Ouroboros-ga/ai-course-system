import pytest
from pydantic import ValidationError

from app.common.llm_client import LLMResponse
from app.schemas.controlled_prep import ControlledPrepInput, EvidenceReference, TeachingStyleConfig
from app.services.controlled_prep_workflow import ControlledPrepWorkflow, StructuredOutputError


class SequencedLLM:
    def __init__(self, payloads):
        self.payloads = iter(payloads)
        self.calls = []

    async def chat(self, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        return LLMResponse(
            content=next(self.payloads), usage={}, model="fake", finish_reason="stop", latency_ms=1
        )


def _request():
    return ControlledPrepInput(
        source_text="二分查找要求序列有序。\n\n查找区间不断缩小。",
        evidence=[EvidenceReference(evidence_id="es_1", text="二分查找要求序列有序", page=1)],
        course_positioning="面向初学者的算法课",
        style=TeachingStyleConfig(level="beginner"),
    )


def test_each_stage_uses_strict_json_schema_and_generates_local_node():
    llm = SequencedLLM([
        '{"stage":"evidence_segmenter","segments":[{"segment_id":"seg_1","title":"二分查找","topic":"有序序列查找","evidence_ids":["es_1"],"examples":[],"exercises":[]}]}',
        '{"stage":"outline_planner","candidates":[{"candidate_id":"kp_1","node_type":"section","title":"查找基础","parent_candidate_id":null,"evidence_ids":["es_1"],"rationale":""},{"candidate_id":"kp_2","node_type":"knowledge_point","title":"二分查找","parent_candidate_id":"kp_1","evidence_ids":["es_1"],"rationale":""}],"prerequisites":[]}',
        '{"stage":"script_writer","candidate_id":"kp_2","title":"二分查找","evidence_ids":["es_1"],"course_positioning":"初学者算法课","prerequisites":[],"style":{"level":"beginner","tone":"conversational","language":"zh-CN","include_examples":true,"include_practice_prompt":true},"content":"二分查找用于有序序列。","claims":["二分查找要求序列有序"],"paragraph_evidence":[["es_1"]]}',
        '{"stage":"evidence_verifier","verdict":"passed","findings":[{"claim":"二分查找要求序列有序","evidence_ids":["es_1"],"supported":true,"reason":"原文直接说明"}],"unsupported_paragraph_indexes":[]}',
    ])
    result = asyncio_run(ControlledPrepWorkflow(llm, max_retries=0).run(_request(), candidate_id="kp_2"))
    proposal = result["proposal"]
    assert len(llm.calls) == 4
    assert all(call["kwargs"]["response_format"]["type"] == "json_schema" for call in llm.calls)
    assert {op.target for op in proposal.operations} == {"outline:new:title", "script:new:content"}
    assert all(op.evidence_refs == ["es_1"] for op in proposal.operations)


def test_unknown_evidence_is_rejected():
    llm = SequencedLLM([
        '{"stage":"evidence_segmenter","segments":[{"segment_id":"seg_1","title":"x","topic":"x","evidence_ids":["es_missing"],"examples":[],"exercises":[]}]}',
    ])
    with pytest.raises(StructuredOutputError):
        asyncio_run(ControlledPrepWorkflow(llm, max_retries=0).segment_evidence(_request()))


def test_multiple_knowledge_points_use_one_batch_script_request():
    llm = SequencedLLM([
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
    assert [call["messages"][0].content for call in llm.calls].count("你是 ScriptWriter。一次为给定的全部知识点生成 TeachingScriptNode。每个脚本必须绑定输入 Evidence；不要生成候选列表之外的知识点。") == 1
    assert len(llm.calls) == 5
    assert stages[0] == ("evidence", 0)
    assert ("evidence", 10) in stages
    assert ("outline", 30) in stages
    assert ("scripts", 80) in stages
    assert stages[-1] == ("verification", 95)


def test_response_format_rejection_falls_back_to_prompt_constrained_json():
    class GatewayWithoutResponseFormat:
        def __init__(self):
            self.calls = []

        async def chat(self, messages, **kwargs):
            self.calls.append({"messages": messages, "kwargs": kwargs})
            if "response_format" in kwargs:
                raise RuntimeError("400 response_format type is unavailable now")
            return LLMResponse(
                content='{"stage":"evidence_segmenter","segments":[{"segment_id":"seg_1","title":"二分查找","topic":"有序序列查找","evidence_ids":["es_1"],"examples":[],"exercises":[]}]}',
                usage={}, model="gateway", finish_reason="stop", latency_ms=1,
            )

    llm = GatewayWithoutResponseFormat()
    result = asyncio_run(ControlledPrepWorkflow(llm, max_retries=0).segment_evidence(_request()))
    assert result.segments[0].evidence_ids == ["es_1"]
    assert "response_format" in llm.calls[0]["kwargs"]
    assert "response_format" not in llm.calls[1]["kwargs"]
    assert "JSON Schema" in llm.calls[1]["messages"][1].content


def test_schema_forbids_arbitrary_markdown_shape():
    with pytest.raises(ValidationError):
        EvidenceReference(evidence_id="es_1", text="x", unexpected="nope")


def asyncio_run(awaitable):
    import asyncio
    return asyncio.run(awaitable)
