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


def test_schema_forbids_arbitrary_markdown_shape():
    with pytest.raises(ValidationError):
        EvidenceReference(evidence_id="es_1", text="x", unexpected="nope")


def asyncio_run(awaitable):
    import asyncio
    return asyncio.run(awaitable)
