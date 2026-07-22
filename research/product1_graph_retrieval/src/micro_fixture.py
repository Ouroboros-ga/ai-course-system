"""Generate the synthetic Level-A micro-contract fixture.

The labels are deterministic contract oracles.  They are deliberately marked
ineligible for comparing retrieval or mapping algorithms.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .canonical import sha256_file, sha256_text, write_json, write_jsonl
from .fixture_io import (
    FIXTURE_SCHEMA_VERSION,
    GOLD_ONLY_FILES,
    PUBLIC_INPUT_FILES,
    REQUIRED_FILES,
    RESEARCH_SIDECAR_SCHEMA_VERSION,
    compute_fixture_content_hash,
    validate_fixture,
)
from .identities import (
    production_compatible_citation_key,
    research_chunk_id,
    research_evidence_id,
    research_knowledge_point_id,
    research_query_id,
    research_slide_id,
)


COURSES: dict[str, dict[str, Any]] = {
    "course_algorithms": {
        "artifact_id": "art_fixture_algorithms",
        "document_id": "doc_fixture_algorithms",
        "slides": [
            ("a1", "chapter_search", "section_binary", "二分查找", "二分查找要求序列有序，每次比较后排除一半搜索区间。"),
            ("a2", "chapter_search", "section_binary", "复杂度", "二分查找的时间复杂度是 O(log n)，空间复杂度可以是 O(1)。"),
            ("a3", "chapter_search", "section_binary", "边界代码", "安全中点写法是 mid = left + (right - left) // 2，并根据比较更新 mid - 1 或 mid + 1。"),
            ("a4", "chapter_sort", "section_stable", "稳定排序", "稳定排序保持相等关键字元素的原相对次序。"),
            ("a5", "chapter_sort", "section_quick", "快速排序", "快速排序围绕 pivot 分区，平均时间复杂度为 O(n log n)。"),
            ("a6", "chapter_graph", "section_bfs", "广度优先搜索", "BFS 使用队列逐层访问图节点，可求无权图最短路径。"),
            ("a7", "chapter_graph", "section_dijkstra", "Dijkstra", "Dijkstra 在非负边权图上反复选择当前距离最小的未确定节点。"),
            ("a8", "chapter_dp", "section_intro", "动态规划", "动态规划把具有重叠子问题和最优子结构的问题分解并保存中间结果。"),
            ("a9", "chapter_search", "section_index", "算法索引", "索引用于加速查找；算法课程中的索引可以表示数组位置或检索结构。"),
            ("a10", "chapter_review", "section_summary", "算法复习", "复习页汇总二分查找、稳定排序、图搜索和动态规划的适用条件。"),
        ],
        "stale": ("as", "chapter_graph", "section_heap", "旧版 Fibonacci 堆", "旧版材料声称 Fibonacci 堆是本课程必考内容。"),
    },
    "course_databases": {
        "artifact_id": "art_fixture_databases",
        "document_id": "doc_fixture_databases",
        "slides": [
            ("b1", "chapter_index", "section_btree", "B+ 树索引", "B+ 树索引用于加速查找，叶子节点按键值有序并保存数据入口。"),
            ("b2", "chapter_index", "section_cost", "索引代价", "数据库索引降低查询扫描量，但会增加写入维护与存储成本。"),
            ("b3", "chapter_sql", "section_select", "SQL 查询", "示例：SELECT id FROM student WHERE score >= 90 ORDER BY id;"),
            ("b4", "chapter_tx", "section_acid", "事务 ACID", "事务具有原子性、一致性、隔离性和持久性。"),
            ("b5", "chapter_tx", "section_mvcc", "MVCC", "MVCC 通过多版本并发控制减少读写阻塞，并依赖可见性规则。"),
            ("b6", "chapter_relational", "section_join", "连接", "连接按照条件组合多张关系表，常见实现包括嵌套循环、哈希连接和排序合并。"),
            ("b7", "chapter_relational", "section_normalization", "规范化", "第三范式要求非主属性不传递依赖于候选键。"),
            ("b8", "chapter_optimizer", "section_plan", "查询计划", "优化器依据统计信息估算代价并选择访问路径与连接顺序。"),
            ("b9", "chapter_recovery", "section_binlog", "二进制日志", "二进制日志记录数据库变更，可用于复制与恢复。"),
            ("b10", "chapter_review", "section_summary", "数据库复习", "复习页串联 B+ 树索引、事务、连接、规范化和查询优化。"),
        ],
        "stale": ("bs", "chapter_storage", "section_raid", "旧版 RAID", "旧版材料把 RAID 级别细节列为当前考核重点。"),
    },
}


QUERY_SPECS = [
    ("course_algorithms", "二分查找", "definition", "exact_term", "answerable", "a1", "a10", "b1"),
    ("course_algorithms", "O(log n) 与 mid - 1 出现在哪个算法？", "formula", "formula_or_code", "answerable", "a2", "a3", None),
    ("course_algorithms", "怎样通过一次比较丢掉一半候选范围？", "explanation", "paraphrase", "answerable", "a1", "a10", None),
    ("course_algorithms", "Binary Search 的前提是什么？", "definition", "cross_language_alias", "answerable", "a1", "a2", None),
    ("course_algorithms", "为什么二分查找依赖有序序列？", "prerequisite", "multi_hop_relation", "answerable", "a1", "a2", None),
    ("course_algorithms", "什么是稳定排序？", "definition", "definition", "answerable", "a4", "a10", None),
    ("course_algorithms", "神经网络反向传播如何计算梯度？", "no_evidence", "no_answer", "unanswerable_in_course", None, None, None),
    ("course_algorithms", "Fibonacci 堆是不是当前考核内容？", "no_evidence", "no_answer", "evidence_stale_only", None, None, "as"),
    ("course_algorithms", "索引用于加速查找是什么意思？", "definition", "exact_term", "answerable", "a9", None, "b1"),
    ("course_databases", "B+ 树索引", "definition", "exact_term", "answerable", "b1", "b2", "a9"),
    ("course_databases", "SELECT id FROM student WHERE score >= 90", "formula", "formula_or_code", "answerable", "b3", None, None),
    ("course_databases", "系统怎样依据统计信息选择访问路径？", "explanation", "paraphrase", "answerable", "b8", "b2", None),
    ("course_databases", "B-tree index 有什么作用？", "definition", "cross_language_alias", "answerable", "b1", "b2", None),
    ("course_databases", "事务隔离与多版本并发控制有什么关系？", "prerequisite", "multi_hop_relation", "answerable", "b5", "b4", None),
    ("course_databases", "第三范式限制了什么依赖？", "definition", "definition", "answerable", "b7", "b6", None),
    ("course_databases", "卷积神经网络如何做池化？", "no_evidence", "no_answer", "unanswerable_in_course", None, None, None),
    ("course_databases", "RAID 级别是否仍是当前考核重点？", "no_evidence", "no_answer", "evidence_stale_only", None, None, "bs"),
    ("course_missing", "这门不存在的课程讲什么？", "no_evidence", "no_answer", "scope_not_available", None, None, None),
]


KP_SPECS = {
    "course_algorithms": [
        ("二分查找", ["折半查找", "Binary Search"], "a1", ["a2", "a3"], "a5"),
        ("稳定排序", ["Stable Sort"], "a4", ["a10"], "a7"),
        ("快速排序", ["Quick Sort"], "a5", ["a10"], "a4"),
        ("广度优先搜索", ["BFS"], "a6", ["a7"], "a8"),
        ("动态规划", ["Dynamic Programming", "DP"], "a8", ["a10"], "a3"),
    ],
    "course_databases": [
        ("B+ 树索引", ["B-tree index", "B+ Tree"], "b1", ["b2", "b10"], "b4"),
        ("事务", ["Transaction", "ACID"], "b4", ["b5"], "b7"),
        ("连接", ["Join"], "b6", ["b8"], "b9"),
        ("规范化", ["Normalization", "第三范式"], "b7", ["b6"], "b3"),
        ("查询优化", ["Query Optimization"], "b8", ["b2"], "b5"),
    ],
}


def _sidecar() -> dict[str, bool]:
    return {"research_sidecar": True, "not_a_production_contract_field": True}


def build_records() -> dict[str, Any]:
    source_blocks: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    corpus: list[dict[str, Any]] = []
    slides: list[dict[str, Any]] = []
    by_key: dict[str, dict[str, Any]] = {}

    for course_id, course in COURSES.items():
        all_rows = [(row, "active") for row in course["slides"]] + [(course["stale"], "stale")]
        for position, (row, status) in enumerate(all_rows, 1):
            key, chapter, section, title, text = row
            page = position
            unit_id = f"unit_{course_id}_slide_{page:04d}"
            block_id = f"blk_{course_id}_{key}"
            block = {
                "course_id": course_id,
                "artifact_id": course["artifact_id"],
                "document_id": course["document_id"],
                "unit_id": unit_id,
                "unit_type": "slide",
                "unit_index": page,
                "block_id": block_id,
                "block_type": "paragraph",
                "page_or_slide": page,
                "chapter_id": chapter,
                "chapter_path": [course_id, chapter, section],
                "title": title,
                "text": text,
                "text_sha256": sha256_text(text),
            }
            source_blocks.append(block)
            research_ev = research_evidence_id(
                course_id=course_id,
                artifact_id=course["artifact_id"],
                document_id=course["document_id"],
                unit_id=unit_id,
                block_id=block_id,
                version_ref="synthetic-document-v1",
                char_start=0,
                char_end=len(text),
            )
            ev = {
                **_sidecar(),
                "research_evidence_id": research_ev,
                "course_id": course_id,
                "artifact_id": course["artifact_id"],
                "document_id": course["document_id"],
                "unit_id": unit_id,
                "block_id": block_id,
                "version_ref": "synthetic-document-v1",
                "page_or_slide": page,
                "char_start": 0,
                "char_end": len(text),
                "text_snippet": text,
                "status": status,
                "citation_key": production_compatible_citation_key(
                    artifact_id=course["artifact_id"],
                    block_id=block_id,
                    char_start=0,
                    char_end=len(text),
                ),
                "metadata": {"unit_type": "slide", "synthetic": True},
            }
            evidence.append(ev)
            by_key[key] = {"block": block, "evidence": ev}
            if status == "active":
                research_chunk = research_chunk_id(
                    course_id=course_id,
                    document_id=course["document_id"],
                    unit_id=unit_id,
                    block_id=block_id,
                    research_evidence_ids=[research_ev],
                    text_sha256=block["text_sha256"],
                )
                corpus.append(
                    {
                        **_sidecar(),
                        "research_chunk_id": research_chunk,
                        "course_id": course_id,
                        "artifact_id": course["artifact_id"],
                        "document_id": course["document_id"],
                        "unit_id": unit_id,
                        "unit_type": "slide",
                        "unit_index": page,
                        "block_id": block_id,
                        "block_type": "paragraph",
                        "research_evidence_ids": [research_ev],
                        "page_or_slide": page,
                        "chapter_id": chapter,
                        "chapter_path": block["chapter_path"],
                        "title": title,
                        "text": text,
                        "text_sha256": block["text_sha256"],
                        "language": "zh-CN",
                    }
                )
                slide_id = research_slide_id(course_id=course_id, document_id=course["document_id"], unit_id=unit_id)
                slide = {
                    **_sidecar(),
                    "research_slide_id": slide_id,
                    "course_id": course_id,
                    "document_id": course["document_id"],
                    "unit_id": unit_id,
                    "slide_number": page,
                    "chapter_id": chapter,
                    "chapter_path": block["chapter_path"],
                    "title": title,
                    "body_text": text,
                    "block_ids": [block_id],
                    "research_evidence_ids": [research_ev],
                }
                slides.append(slide)
                by_key[key]["slide"] = slide
                by_key[key]["chunk"] = corpus[-1]

    queries: list[dict[str, Any]] = []
    query_labels: list[dict[str, Any]] = []
    retrieval_qrels: list[dict[str, Any]] = []
    query_ids: list[str] = []
    for course_id, text, query_type, stratum, answerability, direct, partial, negative in QUERY_SPECS:
        query_id = research_query_id(course_id=course_id, text=text)
        query_ids.append(query_id)
        queries.append(
            {
                **_sidecar(),
                "research_query_id": query_id,
                "course_id": course_id,
                "text": text,
                "query_type": query_type,
                "query_stratum": stratum,
                "tags": [stratum, "synthetic_contract_case"],
            }
        )
        query_labels.append({"research_query_id": query_id, "answerability": answerability})
        for key, relevance, judgment in (
            (direct, 2, "direct_support"),
            (partial, 1, "partial_support"),
            (negative, 0, "not_relevant"),
        ):
            if key:
                retrieval_qrels.append(
                    {
                        "research_query_id": query_id,
                        "research_evidence_id": by_key[key]["evidence"]["research_evidence_id"],
                        "relevance": relevance,
                        "judgment": judgment,
                        "annotation_note": "synthetic contract oracle; not human gold",
                    }
                )

    knowledge_points: list[dict[str, Any]] = []
    mapping_qrels: list[dict[str, Any]] = []
    kp_ids: list[str] = []
    for course_id, specs in KP_SPECS.items():
        for label, aliases, primary, supporting, negative in specs:
            kp_id = research_knowledge_point_id(course_id=course_id, canonical_label=label)
            kp_ids.append(kp_id)
            positive_keys = [primary, *supporting]
            knowledge_points.append(
                {
                    **_sidecar(),
                    "research_knowledge_point_id": kp_id,
                    "course_id": course_id,
                    "canonical_label": label,
                    "aliases": aliases,
                    "alias_provenance": {"source": "synthetic_contract_fixture", "frozen_before_split": True, "synthetic_fixture": True},
                    "chapter_id": by_key[primary]["block"]["chapter_id"],
                    "chapter_path": by_key[primary]["block"]["chapter_path"],
                    "research_evidence_ids": [by_key[key]["evidence"]["research_evidence_id"] for key in positive_keys],
                    "review_status": "accepted",
                }
            )
            for key, relevance, judgment in [
                (primary, 2, "primary_slide"),
                *[(key, 1, "supporting_slide") for key in supporting],
                (negative, 0, "irrelevant_hard_negative"),
            ]:
                mapping_qrels.append(
                    {
                        "research_knowledge_point_id": kp_id,
                        "research_slide_id": by_key[key]["slide"]["research_slide_id"],
                        "relevance": relevance,
                        "judgment": judgment,
                        "research_evidence_ids": [by_key[key]["evidence"]["research_evidence_id"]],
                        "annotation_note": "synthetic contract oracle; not human gold",
                    }
                )

    validation_queries = query_ids[::2]
    test_queries = query_ids[1::2]
    validation_kps = kp_ids[::2]
    test_kps = kp_ids[1::2]
    splits = {
        "split_version": "1.1",
        "train_query_ids": [],
        "validation_query_ids": validation_queries,
        "test_query_ids": test_queries,
        "validation_knowledge_point_ids": validation_kps,
        "test_knowledge_point_ids": test_kps,
        "policy": "thresholds_and_weights_use_validation_only",
        "test_gold_access": "evaluation_only_after_run_freeze",
    }
    return {
        "source_blocks.jsonl": sorted(source_blocks, key=lambda row: row["block_id"]),
        "evidence.jsonl": sorted(evidence, key=lambda row: row["research_evidence_id"]),
        "corpus.jsonl": sorted(corpus, key=lambda row: row["research_chunk_id"]),
        "queries.jsonl": sorted(queries, key=lambda row: row["research_query_id"]),
        "retrieval_query_labels.jsonl": sorted(query_labels, key=lambda row: row["research_query_id"]),
        "retrieval_qrels.jsonl": sorted(retrieval_qrels, key=lambda row: (row["research_query_id"], row["research_evidence_id"])),
        "knowledge_points.jsonl": sorted(knowledge_points, key=lambda row: row["research_knowledge_point_id"]),
        "slides.jsonl": sorted(slides, key=lambda row: row["research_slide_id"]),
        "mapping_qrels.jsonl": sorted(mapping_qrels, key=lambda row: (row["research_knowledge_point_id"], row["research_slide_id"])),
        "splits.json": splits,
    }


def generate_micro_fixture(output_dir: Path, *, overwrite: bool = False) -> dict[str, Any]:
    output_dir = Path(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()) and not overwrite:
        raise FileExistsError(f"refusing to overwrite non-empty fixture: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    records = build_records()
    for name in REQUIRED_FILES:
        if name.endswith(".jsonl"):
            write_jsonl(output_dir / name, records[name])
        else:
            write_json(output_dir / name, records[name])
    file_hashes = {name: f"sha256:{sha256_file(output_dir / name)}" for name in REQUIRED_FILES}
    manifest = {
        "fixture_schema_version": FIXTURE_SCHEMA_VERSION,
        "research_sidecar_schema_version": RESEARCH_SIDECAR_SCHEMA_VERSION,
        "fixture_id": "micro_contract_v1",
        "dataset_level": "micro_contract",
        "created_at": "2026-07-16T00:00:00Z",
        "source_contracts": {
            "document_ir": "document-ir/1.0",
            "evidence": "evidence/1.0",
            "citation": "citation/1.0",
            "education_graph": "edu-graph/1.0"
        },
        "course_ids": sorted(COURSES),
        "files": file_hashes,
        "fixture_content_sha256": compute_fixture_content_hash(file_hashes),
        "access_policy": {
            "index_inputs": sorted(PUBLIC_INPUT_FILES),
            "gold_only": sorted(GOLD_ONLY_FILES),
            "test_qrels_forbidden_before_run": True,
        },
        "identity_fields": {
            "evidence": "research_evidence_id",
            "chunk": "research_chunk_id",
            "query": "research_query_id",
            "slide": "research_slide_id",
            "knowledge_point": "research_knowledge_point_id",
            "all_are_research_sidecars": True,
            "not_production_contract_fields": True,
        },
        "normalization": {"unicode": "source-preserved", "source_text_mutated": False, "ppt_page_base": 1},
        "gold": {"status": "synthetic_contract_oracle", "eligible_for_algorithm_comparison": False},
        "annotation": {
            "independent_human_annotator_count": 0,
            "adjudicated": False,
            "note": "generated expectations test contract mechanics only"
        },
        "governance": {
            "p1_00": {"status": "pending", "confirmed_by": None},
            "p1_10": {"status": "pending", "reviewed_by": None},
            "b_r1_release": "blocked_until_both_approved"
        },
        "contains_production_data": False,
        "contains_personal_data": False,
    }
    write_json(output_dir / "manifest.json", manifest)
    return validate_fixture(output_dir)
