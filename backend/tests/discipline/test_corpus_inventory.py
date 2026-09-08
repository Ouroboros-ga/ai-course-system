"""CR0 语料盘点与检索基准验收测试（合成 fixture，不读生产数据）。"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CORPUS_DIR = REPO_ROOT / "knowledge_data" / "corpus"
RAG_DIR = CORPUS_DIR / "rag"


def _load_benchmark_module():
    script = CORPUS_DIR / "benchmark_corpus_retrieval.py"
    spec = importlib.util.spec_from_file_location(
        "benchmark_corpus_retrieval", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_inventory_keeps_all_sources_without_fabricating_counts(tmp_path):
    mod = _load_benchmark_module()
    report = mod.inventory_sources(tmp_path, [])
    assert report["document_count"] == 0
    assert report["status"] == "empty"


def test_inventory_reports_bad_records_with_source_ids(tmp_path):
    mod = _load_benchmark_module()
    corpus = tmp_path / "corpus_textbooks.jsonl"
    corpus.write_text(
        '{"id": "ostep-a", "title": "A", "text": "正文甲乙丙丁戊己庚辛壬癸。", '
        '"source": "s", "license": "CC BY-SA 4.0"}\n'
        '{"id": "ostep-a", "title": "A dup", "text": "重复正文甲乙丙丁戊己庚辛壬癸。", '
        '"source": "s", "license": "CC BY-SA 4.0"}\n'
        '{"id": "bad-1", "title": "", "text": "", "source": "s"}\n'
        'not json at all\n',
        encoding="utf-8",
    )
    report = mod.inventory_sources(tmp_path, [{
        "source_kind": "textbook", "file": "corpus_textbooks.jsonl",
        "format": "textbooks",
    }])
    assert report["document_count"] == 1
    assert report["status"] == "partial"
    reasons = {e["reason"] for e in report["files"][0]["errors"]}
    assert {"duplicate_id", "empty_text", "bad_json"} <= reasons
    assert report["files"][0]["duplicate_ids"] == ["ostep-a"]


def test_inventory_requires_text_not_size(tmp_path):
    mod = _load_benchmark_module()
    corpus = tmp_path / "corpus_rfc.jsonl"
    corpus.write_text(
        '{"id": "rfc-1", "title": "T", "text": "   ", "source": "s", '
        '"license": "x"}\n',
        encoding="utf-8",
    )
    report = mod.inventory_sources(tmp_path, [{
        "source_kind": "rfc", "file": "corpus_rfc.jsonl", "format": "rfc",
    }])
    assert report["document_count"] == 0
    assert report["status"] == "empty"
    assert report["files"][0]["errors"][0]["reason"] == "empty_text"


def test_rag_fixtures_are_present_and_synthetic():
    sources = json.loads((RAG_DIR / "sources.json").read_text(encoding="utf-8"))
    assert set(s["source_kind"] for s in sources["sources"]) == {
        "textbook", "zhwiki", "enwiki", "rfc", "arxiv"}
    assert "cs-public" in sources["sets"]
    config = json.loads((RAG_DIR / "config.json").read_text(encoding="utf-8"))
    assert config["model"]["id"] == "intfloat/multilingual-e5-small"
    assert config["model"]["dimension"] == 384
    assert config["chunking"]["target_tokens"] == 320
    lines = (RAG_DIR / "queries.jsonl").read_text(encoding="utf-8").splitlines()
    lines = [line for line in lines if line.strip()]
    assert len(lines) == 120
    by_kind = {}
    for line in lines:
        case = json.loads(line)
        assert case["query_id"].startswith("synth-")
        by_kind[case["kind"]] = by_kind.get(case["kind"], 0) + 1
    assert by_kind.get("zh", 0) + by_kind.get("en", 0) == 100
    assert by_kind.get("no_answer", 0) == 20


def test_shipped_queries_are_not_whole_passage_copies():
    """题目不得整段复制正文（CR0 声明属性，此前无生成器/断言强制）。

    对随仓题集逐条断言：答案题长度远小于其相关段落，且相关 ID 可解析。
    """
    queries = [json.loads(line) for line in
               (RAG_DIR / "queries.jsonl").read_text(encoding="utf-8").splitlines()
               if line.strip()]
    passages = {row["passage_id"]: row for row in
                (json.loads(line) for line in
                 (RAG_DIR / "sample_passages.jsonl").read_text(
                     encoding="utf-8").splitlines() if line.strip())}
    answerable = [q for q in queries if q.get("relevant_passage_ids")]
    assert len(answerable) == 100
    for case in answerable:
        for passage_id in case["relevant_passage_ids"]:
            assert passage_id in passages, passage_id
            assert len(case["text"]) * 2 < len(passages[passage_id]["text"])


def test_benchmark_harness_scores_fake_encoder():
    mod = _load_benchmark_module()
    passages = [
        {"passage_id": "p-os", "text": "页表记录虚拟页与物理页的映射。"},
        {"passage_id": "p-net", "text": "TCP 通过三次握手建立连接。"},
    ]
    queries = [
        {"query_id": "q1", "kind": "zh", "text": "页表",
         "relevant_passage_ids": ["p-os"]},
        {"query_id": "q2", "kind": "no_answer", "text": "不存在的内容",
         "relevant_passage_ids": []},
    ]

    def fake_encode(texts, kind):
        # 关键词 presence 的确定性伪向量（仅测 harness 计分，不测语义）；
        # 无关文本得零向量（harness 按相似度 0 处理，不 NaN）。
        vectors = []
        for text in texts:
            vectors.append([1.0 if "页表" in text else 0.0,
                            1.0 if "三次握手" in text else 0.0])
        return vectors

    report = mod.benchmark_model(
        {"model": {"id": "fake", "dimension": 2}}, passages, queries,
        fake_encode, top_k=2)
    assert report["hit_at_2"] == 1.0
    assert report["no_answer_empty_rate"] == 1.0
    assert report["query_count"] == 1
