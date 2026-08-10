"""Regression tests for local, program-side Prep evidence attribution."""

import asyncio
import json

from types import SimpleNamespace

from app.platform.agents.prep.evidence_binding import (
    bind_evidence_refs,
    bind_outline_evidence_refs,
)
from app.platform.agents.contracts.llm import LLMResponse
from app.platform.agents.prep.llm_adapter import PrepLLMAdapter
from app.schemas.controlled_prep import ControlledPrepInput, EvidenceReference


def _evidence(evidence_id: str, text: str):
    return SimpleNamespace(evidence_id=evidence_id, text=text)


def _segment(segment_id: str, title: str, topic: str, evidence_ids: list[str]):
    return SimpleNamespace(
        segment_id=segment_id,
        title=title,
        topic=topic,
        evidence_ids=evidence_ids,
        examples=[],
        exercises=[],
    )


def _candidate(candidate_id: str, node_type: str, title: str, parent_candidate_id: str | None = None):
    return SimpleNamespace(
        candidate_id=candidate_id,
        node_type=node_type,
        title=title,
        topic=title,
        rationale="",
        parent_candidate_id=parent_candidate_id,
    )


def test_local_binding_keeps_distinct_topics_off_the_global_union():
    evidence = [
        _evidence("ev_engine", "发动机总体结构包括气缸体、曲轴和活塞。"),
        _evidence("ev_combustion", "四冲程汽油机包括进气、压缩、做功和排气。"),
        _evidence("ev_lubrication", "润滑系统由机油泵、油道和滤清器组成。"),
    ]
    outputs = [
        {"title": "发动机总体构造", "topic": "曲轴活塞机构"},
        {"title": "四冲程工作原理", "topic": "进气压缩做功排气"},
        {"title": "发动机润滑系统", "topic": "机油泵油道"},
    ]

    refs = bind_evidence_refs(
        outputs,
        evidence,
        max_source_items=2,
        max_evidence_refs=3,
    )

    assert refs[0] == ["ev_engine"]
    assert refs[1] == ["ev_combustion"]
    assert refs[2] == ["ev_lubrication"]
    assert len({tuple(item) for item in refs}) == len(refs)
    assert all(len(item) < len(evidence) for item in refs)


def test_zero_overlap_uses_stable_local_position_not_every_source():
    evidence = [
        _evidence("ev_1", "alpha"),
        _evidence("ev_2", "bravo"),
        _evidence("ev_3", "charlie"),
        _evidence("ev_4", "delta"),
    ]

    refs = bind_evidence_refs(
        ["主题甲", "主题乙"],
        evidence,
        max_source_items=1,
        max_evidence_refs=1,
    )

    assert refs == [["ev_1"], ["ev_3"]]


def test_outline_aggregates_only_its_own_descendants_with_bounds():
    segments = [
        _segment("s1", "发动机分类", "汽油机和柴油机", ["ev_type"]),
        _segment("s2", "四冲程", "进气压缩做功排气", ["ev_cycle"]),
        _segment("s3", "润滑系统", "机油泵油道", ["ev_lube"]),
    ]
    candidates = [
        _candidate("chapter", "chapter", "发动机总论"),
        _candidate("section_a", "section", "发动机工作", "chapter"),
        _candidate("kp_type", "knowledge_point", "发动机分类", "section_a"),
        _candidate("kp_cycle", "knowledge_point", "四冲程工作", "section_a"),
        _candidate("section_b", "section", "润滑系统", "chapter"),
        _candidate("kp_lube", "knowledge_point", "润滑系统组成", "section_b"),
    ]

    refs = bind_outline_evidence_refs(candidates, segments)

    assert refs["kp_type"] == ["ev_type"]
    assert refs["kp_cycle"] == ["ev_cycle"]
    assert refs["kp_lube"] == ["ev_lube"]
    assert set(refs["section_a"]) == {"ev_type", "ev_cycle"}
    assert refs["section_b"] == ["ev_lube"]
    assert set(refs["chapter"]) == {"ev_type", "ev_cycle", "ev_lube"}


def test_adapter_keeps_map_reduce_and_outline_evidence_local():
    """The real adapter must not reintroduce a union at a later stage."""
    payloads = [
        {
            "stage": "evidence_segmenter",
            "segments": [
                {"segment_id": "map_type", "title": "发动机分类", "topic": "汽油机柴油机"},
                {"segment_id": "map_cycle", "title": "四冲程", "topic": "进气压缩做功排气"},
                {"segment_id": "map_lube", "title": "润滑系统", "topic": "机油泵油道"},
            ],
        },
        {
            "stage": "evidence_segmenter",
            "segments": [
                {"segment_id": "reduce_type", "title": "发动机分类", "topic": "汽油机柴油机"},
                {"segment_id": "reduce_cycle", "title": "四冲程", "topic": "进气压缩做功排气"},
                {"segment_id": "reduce_lube", "title": "润滑系统", "topic": "机油泵油道"},
            ],
        },
        {
            "stage": "outline_planner",
            "candidates": [
                {"candidate_id": "ch", "node_type": "chapter", "title": "发动机总论", "parent_candidate_id": None, "rationale": ""},
                {"candidate_id": "sec_type", "node_type": "section", "title": "发动机分类", "parent_candidate_id": "ch", "rationale": ""},
                {"candidate_id": "kp_type", "node_type": "knowledge_point", "title": "发动机分类", "parent_candidate_id": "sec_type", "rationale": ""},
                {"candidate_id": "sec_cycle", "node_type": "section", "title": "四冲程", "parent_candidate_id": "ch", "rationale": ""},
                {"candidate_id": "kp_cycle", "node_type": "knowledge_point", "title": "四冲程工作原理", "parent_candidate_id": "sec_cycle", "rationale": ""},
                {"candidate_id": "sec_lube", "node_type": "section", "title": "润滑系统", "parent_candidate_id": "ch", "rationale": ""},
                {"candidate_id": "kp_lube", "node_type": "knowledge_point", "title": "润滑系统组成", "parent_candidate_id": "sec_lube", "rationale": ""},
            ],
            "prerequisites": [],
        },
    ]

    class SequencedPort:
        async def complete(self, *, output_schema, **_kwargs):
            payload = payloads.pop(0)
            return LLMResponse(
                content=json.dumps(payload, ensure_ascii=False),
                parsed=output_schema.model_validate(payload),
            )

    request = ControlledPrepInput(evidence=[
        EvidenceReference(evidence_id="ev_type", text="发动机的分类包括汽油机和柴油机。"),
        EvidenceReference(evidence_id="ev_cycle", text="四冲程工作过程包括进气压缩做功排气。"),
        EvidenceReference(evidence_id="ev_lube", text="润滑系统由机油泵和油道组成。"),
    ])
    adapter = PrepLLMAdapter(structured_llm=SequencedPort())

    mapped = asyncio.run(adapter.segment_evidence(request))
    reduced = asyncio.run(adapter.reduce_evidence(mapped.segments))
    outline = asyncio.run(adapter.plan_outline(request, reduced))
    refs_by_id = {candidate.candidate_id: candidate.evidence_ids for candidate in outline.candidates}

    assert [segment.evidence_ids for segment in mapped.segments] == [
        ["ev_type"], ["ev_cycle"], ["ev_lube"],
    ]
    assert [segment.evidence_ids for segment in reduced.segments] == [
        ["ev_type"], ["ev_cycle"], ["ev_lube"],
    ]
    assert refs_by_id["kp_type"] == ["ev_type"]
    assert refs_by_id["kp_cycle"] == ["ev_cycle"]
    assert refs_by_id["kp_lube"] == ["ev_lube"]
    assert set(refs_by_id["ch"]) == {"ev_type", "ev_cycle", "ev_lube"}
