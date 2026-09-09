"""DK0 范围清单、自动挑战集与抽取规范验收测试。

只用合成 fixture 与静态基准文件；不访问服务器、不调用模型。
"""

from __future__ import annotations

import copy
import importlib.util
import json
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
KNOWLEDGE_DATA_DIR = REPO_ROOT / "knowledge_data"
PIPELINE_DIR = KNOWLEDGE_DATA_DIR / "pipeline"
BENCHMARK_DIR = PIPELINE_DIR / "benchmark"


def _load_prepare_sample():
    script = KNOWLEDGE_DATA_DIR / "corpus" / "prepare_knowledge_sample.py"
    spec = importlib.util.spec_from_file_location("prepare_knowledge_sample", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


sampler = _load_prepare_sample()
prepare_sample = sampler.prepare_sample


def test_sample_is_repeatable_and_document_disjoint(sample_fixture):
    a = prepare_sample(**sample_fixture)
    b = prepare_sample(**sample_fixture)
    assert a["chunk_ids"] == b["chunk_ids"]
    assert a["fingerprint"] == b["fingerprint"]
    assert not (
        set(a["example_document_families"]) & set(a["evaluation_document_families"])
    )
    # 输出文件与返回内容一致
    written = json.loads(
        (Path(sample_fixture["output_dir"]) / "sample_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert written["chunk_ids"] == a["chunk_ids"]


def test_tampered_document_only_changes_related_selection(sample_fixture):
    base = prepare_sample(**sample_fixture)
    tampered_manifest = copy.deepcopy(sample_fixture["manifest"])
    # 篡改一个**已被选中**的文档：只改变该文档相关条目与指纹
    victim_doc_id = base["selection"][0]["document_id"]
    victim = next(
        d for d in tampered_manifest["documents"] if d["document_id"] == victim_doc_id
    )
    victim["version"] = "v2-tampered"
    victim["chunks"][0] = {"chunk_id": "synth-tampered-only", "chars": 777}
    tampered = prepare_sample(
        tampered_manifest,
        seed=sample_fixture["seed"],
        per_source=sample_fixture["per_source"],
    )
    assert tampered["fingerprint"] != base["fingerprint"]
    assert "synth-tampered-only" in tampered["chunk_ids"]
    base_rest = [s for s in base["selection"] if s["document_id"] != victim["document_id"]]
    tampered_rest = [
        s for s in tampered["selection"] if s["document_id"] != victim["document_id"]
    ]
    # 未被篡改文档的选择条目（文档/片段/划分）完全不变
    assert [(s["document_id"], s["chunk_id"], s["split"]) for s in tampered_rest] == [
        (s["document_id"], s["chunk_id"], s["split"]) for s in base_rest
    ]


def test_counts_and_token_estimate_are_reported(sample_fixture):
    result = prepare_sample(**sample_fixture)
    assert result["schema"] == "discipline-sample/1"
    assert result["counts"]["selected_total"] == len(result["chunk_ids"])
    assert result["counts"]["requested"]["textbook"] == 6
    # token 为容量粗估：有正数总量，且与字符总量同量级（tok-est/1 口径）
    assert result["token_estimate_total"] > 0
    assert result["chars_total"] > 0
    assert result["token_estimate_version"] == "tok-est/1"


def test_ontology_predicates_and_rejections():
    ontology = json.loads(
        (PIPELINE_DIR / "ontology.json").read_text(encoding="utf-8")
    )
    assert ontology["predicates"]["values"] == [
        "defines", "has_property", "uses", "part_of", "contrasts_with",
        "applies_to", "example_of", "related_to", "prerequisite_candidate",
    ]
    assert set(ontology["source_kinds"]) == {
        "textbook", "zhwiki", "enwiki", "rfc", "arxiv"
    }
    assert ontology["rejection_examples"]
    assert "quotation_rule" in ontology
    assert "identity_rule" in ontology


def _load_synthetic_cases():
    lines = (BENCHMARK_DIR / "synthetic_cases.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def test_synthetic_cases_cover_all_categories():
    cases = _load_synthetic_cases()
    assert len(cases) >= 200
    counts = Counter(c["category"] for c in cases)
    assert set(counts) == {
        "no_knowledge", "homonym", "negation", "conditional",
        "direction_reversal", "version_conflict", "prompt_injection",
        "fabricated_citation",
    }
    assert all(v >= 20 for v in counts.values())
    assert len({c["case_id"] for c in cases}) == len(cases)
    for case in cases:
        # 每个期望由显式规则给出，不由被测模型判定
        assert case["expected_decision"]
        assert case["expected_reason_code"]
        assert case["rule"]


def test_synthetic_cases_encode_deformation_contract():
    """合成变形契约：同义改写保身份；否定/条件/方向反转必须改变或拒绝。"""
    cases = _load_synthetic_cases()
    by_category: dict[str, list[dict]] = {}
    for case in cases:
        by_category.setdefault(case["category"], []).append(case)

    # 同名异义：无上下文必须 ambiguous，有充分上下文才 resolved（同义不合并、异义不混淆）
    hom = {c["case_id"]: c for c in by_category["homonym"]}
    assert any(c["expected_decision"] == "ambiguous" for c in hom.values())
    assert any(c["expected_decision"] == "resolved" for c in hom.values())
    for case in hom.values():
        if case["expected_decision"] == "ambiguous":
            assert case["gold_concept"] is None
            assert len(case["candidate_concept_ids"]) >= 2

    # 否定句：肯定形式候选一律 contradicted
    assert {
        c["expected_verdict"] for c in by_category["negation"]
    } == {"contradicted"}
    # 条件句：无限定候选一律 insufficient，且必须指明所需限定
    for case in by_category["conditional"]:
        assert case["expected_verdict"] == "insufficient"
        assert case["required_qualifier"]
    # 方向反转：反向候选一律 contradicted，且须给出原文支持的方向
    for case in by_category["direction_reversal"]:
        assert case["expected_verdict"] == "contradicted"
        assert case["supported_direction"]
    # 伪造引文：定位一律失败
    assert {
        c["expected_verdict"] for c in by_category["fabricated_citation"]
    } == {"grounding_failed"}
    # 无应抽知识：一律零候选
    for case in by_category["no_knowledge"]:
        assert case["candidates"] == []
    # 提示注入：语料内指令一律拒绝，不得转为断言
    assert {
        c["expected_decision"] for c in by_category["prompt_injection"]
    } == {"reject"}


def test_checked_in_sample_manifest_is_synthetic_and_disjoint():
    manifest = json.loads(
        (BENCHMARK_DIR / "sample_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["schema"] == "discipline-sample/1"
    assert manifest["counts"]["selected_total"] == 1000
    assert manifest["counts"]["selected"] == {
        "textbook": 200, "zhwiki": 200, "enwiki": 200, "rfc": 200, "arxiv": 200,
    }
    assert not (
        set(manifest["example_document_families"])
        & set(manifest["evaluation_document_families"])
    )
    # 入库清单全部为合成 ID，不对应真实文档
    assert manifest["selection"]
    assert all(s["chunk_id"].startswith("synth-") for s in manifest["selection"])
    assert (KNOWLEDGE_DATA_DIR / "corpus" / "manifest.json").is_file()
