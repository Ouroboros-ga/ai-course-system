"""DK3 Resolver B 消歧验收测试（确定性规则，无模型调用）。"""

from __future__ import annotations

from app.services.discipline_knowledge.resolution import resolve_identity


def test_heap_data_structure_does_not_merge_with_memory():
    from app.services.discipline_knowledge.resolution import resolve_identity
    result = resolve_identity(
        {"name": "heap", "domain": "data_structures", "node_type": "concept", "definition": "heap-ordered tree"},
        [{"concept_id": "memory-heap", "name": "heap", "domain": "memory_management", "node_type": "concept", "definition": "dynamic memory allocation area"}],
    )
    assert result["decision"] != "resolved"


def test_heap_cross_domain_yields_new_concept():
    result = resolve_identity(
        {"name": "堆", "domain": "data_structures", "node_type": "concept",
         "definition": "满足堆序性质的完全二叉树"},
        [{"concept_id": "mem-heap", "name": "堆", "domain": "memory_management",
          "node_type": "concept", "definition": "动态内存分配区域"}],
    )
    # 领域互斥：同名异义必须并存为不同概念，不得静默合并
    assert result["decision"] == "new"
    assert result["concept_id"] is None
    assert "DOMAIN_FILTERED" in result["reason_codes"]


def test_hash_table_with_synonym_evidence_resolves():
    result = resolve_identity(
        {"name": "哈希表", "domain": "data_structures", "node_type": "concept",
         "definition": "用哈希函数把键映射到槽位的表"},
        [{"concept_id": "dkn_hash", "name": "哈希表", "domain": "data_structures",
          "node_type": "concept", "aliases": ["hash table"],
          "definition": "用哈希函数把键映射到槽位的表结构"}],
    )
    assert result["decision"] == "resolved"
    assert result["concept_id"] == "dkn_hash"


def test_cross_language_alias_resolves_with_domain():
    result = resolve_identity(
        {"name": "hash table", "domain": "data_structures", "node_type": "concept"},
        [{"concept_id": "dkn_hash", "name": "哈希表", "domain": "data_structures",
          "node_type": "concept", "aliases": ["Hash Table"]}],
    )
    assert result["decision"] == "resolved"


def test_unknown_type_never_force_merges():
    result = resolve_identity(
        {"name": "堆", "domain": "data_structures", "node_type": "",
         "definition": "满足堆序性质的完全二叉树"},
        [{"concept_id": "dkn_heap", "name": "堆", "domain": "data_structures",
          "node_type": "concept", "definition": "满足堆序性质的完全二叉树"}],
    )
    assert result["decision"] == "ambiguous"
    assert "TYPE_UNKNOWN" in result["reason_codes"]


def test_definition_context_breaks_tie():
    mention = {"name": "tree", "domain": "cs", "node_type": "concept",
               "definition": "用信息增益选择分裂属性的决策树模型"}
    candidates = [
        {"concept_id": "tree-ds", "name": "tree", "domain": "cs",
         "node_type": "concept", "definition": "由节点与边组成的非线性结构"},
        {"concept_id": "tree-decision", "name": "tree", "domain": "cs",
         "node_type": "concept", "definition": "用信息增益选择分裂属性的决策树"},
    ]
    result = resolve_identity(mention, candidates)
    assert result["decision"] == "resolved"
    assert result["concept_id"] == "tree-decision"


def test_tied_definitions_stay_ambiguous():
    mention = {"name": "冲突", "domain": "cs", "node_type": "concept",
               "definition": "需要处理的冲突问题"}
    candidates = [
        {"concept_id": "c1", "name": "冲突", "domain": "cs",
         "node_type": "concept", "definition": "需要处理的冲突问题甲"},
        {"concept_id": "c2", "name": "冲突", "domain": "cs",
         "node_type": "concept", "definition": "需要处理的冲突问题乙"},
    ]
    result = resolve_identity(mention, candidates)
    assert result["decision"] == "ambiguous"
    assert "MULTIPLE_CANDIDATES" in result["reason_codes"]


def test_empty_surface_is_ambiguous():
    result = resolve_identity({"name": "  ", "domain": "cs", "node_type": "concept"}, [])
    assert result["decision"] == "ambiguous"
    assert result["reason_codes"] == ["EMPTY_SURFACE"]
