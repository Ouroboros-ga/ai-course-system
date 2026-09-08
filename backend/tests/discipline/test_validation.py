"""DK3 Verifier C 盲核验验收测试（不传入 Extractor confidence）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.discipline_knowledge.validation import verify_assertion

ONTOLOGY_PATH = (
    Path(__file__).resolve().parents[3]
    / "knowledge_data" / "pipeline" / "ontology.json"
)


def test_verbatim_definition_is_supported():
    source = "栈是只允许在一端进行插入与删除操作的线性表。"
    result = verify_assertion(
        {"subject": "栈", "predicate": "defines",
         "literal": "栈是只允许在一端进行插入与删除操作的线性表。",
         "qualifiers": {}},
        source,
        {},
    )
    assert result["verdict"] == "supported"
    assert result["reason_codes"] == ["VERBATIM_SUPPORT"]


def test_qualified_complexity_is_supported_separately():
    source = "平均情况下，快速排序的时间复杂度为 O(n log n)。"
    good = verify_assertion(
        {"subject": "快速排序", "predicate": "has_property",
         "literal": "时间复杂度为 O(n log n)", "qualifiers": {"scope": "平均情况"}},
        source,
        {},
    )
    assert good["verdict"] == "supported"
    # “平均”与“最坏”分别保存：丢掉限定即拒绝
    bad = verify_assertion(
        {"subject": "快速排序", "predicate": "has_property",
         "literal": "时间复杂度为 O(n log n)", "qualifiers": {}},
        source,
        {},
    )
    assert bad["verdict"] == "insufficient"
    assert bad["reason_codes"] == ["QUALIFIER_MISSING"]


def test_negation_contradicts_positive_claim():
    result = verify_assertion(
        {"subject": "栈", "predicate": "has_property",
         "literal": "栈支持随机访问", "qualifiers": {}},
        "栈不支持随机访问，只能在栈顶操作。",
        {},
    )
    assert result["verdict"] == "contradicted"
    assert result["reason_codes"] == ["NEGATION_CONTRADICTED"]


def test_conditional_source_requires_qualifier():
    source = "当数组有序时，二分查找的时间复杂度为 O(log n)。"
    qualified = verify_assertion(
        {"subject": "二分查找", "predicate": "has_property",
         "literal": "时间复杂度为 O(log n)", "qualifiers": {"condition": "数组有序"}},
        source,
        {},
    )
    assert qualified["verdict"] == "supported"
    unqualified = verify_assertion(
        {"subject": "二分查找", "predicate": "has_property",
         "literal": "时间复杂度为 O(log n)", "qualifiers": {}},
        source,
        {},
    )
    assert unqualified["verdict"] == "insufficient"
    assert unqualified["reason_codes"] == ["QUALIFIER_MISSING"]


def test_cooccurrence_cannot_publish_relation():
    result = verify_assertion(
        {"subject": "堆排序", "predicate": "uses", "object": "二叉堆",
         "qualifiers": {}},
        "堆排序使用二叉堆维护待排序列。",
        {},
    )
    assert result["verdict"] == "insufficient"
    assert "RELATION_UNSUPPORTED" in result["reason_codes"]


def test_missing_endpoint_is_insufficient():
    result = verify_assertion(
        {"subject": "堆排序", "predicate": "uses", "object": "斐波那契堆",
         "qualifiers": {}},
        "堆排序使用二叉堆维护待排序列。",
        {},
    )
    assert result["verdict"] == "insufficient"
    assert "RELATION_UNSUPPORTED" in result["reason_codes"]


def test_fabricated_quote_cannot_be_grounded():
    from app.services.discipline_knowledge.validation import verify_assertion as verify

    grounded = verify(
        {"subject": "栈", "predicate": "defines", "literal": "栈是后进先出表。",
         "qualifiers": {},
         "span": {"start": 0, "end": 8, "quote": "栈是后进先出表。"}},
        "栈是后进先出表。",
        {},
    )
    assert grounded["verdict"] == "supported"

    fabricated = verify(
        {"subject": "栈", "predicate": "defines", "literal": "栈是先进先出表。",
         "qualifiers": {},
         "span": {"start": 0, "end": 8, "quote": "栈是先进先出表。"}},
        "栈是后进先出表。",
        {},
    )
    assert fabricated["verdict"] == "insufficient"
    assert fabricated["reason_codes"] == ["GROUNDING_FAILED"]

    empty_span = verify(
        {"subject": "栈", "predicate": "defines", "literal": "栈表。",
         "qualifiers": {}, "span": {"start": 5, "end": 5, "quote": ""}},
        "栈是后进先出表。",
        {},
    )
    assert empty_span["verdict"] == "insufficient"
    assert empty_span["reason_codes"] == ["GROUNDING_FAILED"]


def test_schema_invalid_without_endpoint():
    result = verify_assertion(
        {"subject": "栈", "predicate": "defines", "qualifiers": {}},
        "栈是后进先出表。",
        {},
    )
    assert result["verdict"] == "insufficient"
    assert result["reason_codes"] == ["SCHEMA_INVALID"]


def test_lenient_policy_ignores_missing_qualifier_probe():
    result = verify_assertion(
        {"subject": "栈", "predicate": "defines",
         "literal": "栈是后进先出表。", "qualifiers": {}},
        "栈是后进先出表。",
        {"qualifier_policy": "lenient"},
    )
    assert result["verdict"] == "supported"


def test_reason_codes_are_ontology_closed():
    ontology = json.loads(ONTOLOGY_PATH.read_text(encoding="utf-8"))
    allowed = set(ontology["reason_codes"])
    assert {"VERBATIM_SUPPORT", "NEGATION_CONTRADICTED", "QUALIFIER_MISSING",
            "GROUNDING_FAILED", "RELATION_UNSUPPORTED", "SCHEMA_INVALID"} <= allowed
    # 本文件所有期望码必须在本体词表内
    for codes in (["VERBATIM_SUPPORT"], ["QUALIFIER_MISSING"],
                  ["NEGATION_CONTRADICTED"], ["RELATION_UNSUPPORTED"],
                  ["GROUNDING_FAILED"], ["SCHEMA_INVALID"]):
        assert set(codes) <= allowed


def test_invalid_policy_rejected():
    with pytest.raises(ValueError):
        verify_assertion({"subject": "x", "predicate": "defines", "literal": "x"},
                         "x", {"qualifier_policy": "whatever"})
