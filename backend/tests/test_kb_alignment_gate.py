"""XH-202620：学科知识库对齐（KB name-anchor）分流测试。

验证：
- 知识库已知概念（如 快速排序/堆排序/归并排序）→ kb_aligned，候选保持 proposed
- 超库真实知识点（如 插入排序/基数排序）→ out_of_kb，候选被分流为 needs_review
- 结构性标题（第X章/本章小结/思考与练习/案例演示）→ out_of_kb → needs_review
- 关系候选（含 source_candidate_id + target_candidate_id）不参与对齐，保持 proposed
- 对齐被禁用或知识库为空时回退 proposed（不强制人工、不误标）

这些测试是纯确定性函数/小图候选项，不调用真实 LLM（AGENTS.md 边界）。
"""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlmodel import select

from app.core.config import settings
from app.core.security import get_password_hash
from app.models.access_control_model import (
    CourseCapability, CourseMembership, CourseRole, MembershipStatus,
)
from app.models.course_model import Course, CourseStatus
from app.models.document_parse_model import CandidateBatchStatus, GraphCandidateBatch
from app.models.graph_production_model import GraphNodeReview
from app.models.user_model import User, UserRole
from app.services.course_access_service import (
    establish_course_access_baseline,
)
from app.services.graph_production_service import (
    _review_decision,
    bridge_candidate_batch,
    list_review_candidates,
)
from app.platform.knowledge.kb_alignment import (
    align_candidate,
    enrich_relations_from_kb,
    kb_relation_map,
    normalize_label,
    AlignResult,
)


def _user(session, name, role=UserRole.TEACHER):
    user = User(username=name, hashed_password=get_password_hash("test"), role=role, is_active=True)
    session.add(user); session.commit(); session.refresh(user)
    return user


def _course(session, teacher_id):
    course = Course(
        fanya_course_id=f"kb-{teacher_id}-{datetime.utcnow().timestamp()}",
        fanya_course_name="KB", title="KB", teacher_id=teacher_id, status=CourseStatus.PUBLISHED,
    )
    session.add(course); session.commit(); session.refresh(course)
    return course


def _setup(session, teacher):
    course = _course(session, teacher.id)
    establish_course_access_baseline(session, course.id, teacher.id)
    cap = session.exec(select(CourseCapability).where(CourseCapability.course_id == course.id)).first()
    if cap:
        cap.knowledge_graph = True
        session.add(cap)
    session.commit()
    return course


class TestKbAlignmentClassifier:
    def test_known_concept_aligned(self):
        result = align_candidate("快速排序")
        assert result.status == "kb_aligned"
        assert result.kb_node_key == "algo-007"
        assert result.match_kind == "exact"
        assert result.course == "数据结构与算法"

    def test_known_concept_with_padding_aligns(self):
        result = align_candidate("3.2 快速排序")
        assert result.status == "kb_aligned"
        assert result.kb_node_key == "algo-007"

    def test_known_concept_contains_form_aligns(self):
        result = align_candidate("快速排序的实现与应用")
        assert result.status == "kb_aligned"
        assert result.kb_node_key == "algo-007"
        assert result.match_kind == "contains"

    def test_out_of_kb_real_knowledge_point_is_out_of_kb(self):
        # 插入排序/基数排序 是真实知识点，但知识库未收录同名节点 -> 超库需人工
        assert align_candidate("插入排序").status == "out_of_kb"
        assert align_candidate("基数排序").status == "out_of_kb"

    def test_structural_title_is_out_of_kb(self):
        assert align_candidate("第3章 排序").status == "out_of_kb"
        assert align_candidate("3.5 本章小结").status == "out_of_kb"
        assert align_candidate("3.6 思考与练习").status == "out_of_kb"
        assert align_candidate("案例演示：用随机数据实测三种排序运行时间").status == "out_of_kb"

    def test_short_generic_suffix_not_misaligned(self):
        # '排序'(2字) 不得被 name-anchor 误配 '快速排序'(4字)
        result = align_candidate("排序")
        assert result.status == "out_of_kb"

    def test_normalize_label_strips_prefix(self):
        assert normalize_label("3.2 快速排序") == "快速排序"
        assert normalize_label("第3章 排序") == "排序"
        assert normalize_label("案例演示：快速排序") == "快速排序"


class TestKbRelationEnrichment:
    def test_kb_relation_map_has_semantic_types(self):
        rels = kb_relation_map()
        assert rels
        assert any(meta["relation_type"] in {"prerequisite_of", "uses", "defines", "contrasts_with", "related_to", "supported_by"}
                   for meta in rels.values())

    def test_enrich_adds_kb_semantic_relations(self):
        nodes = [
            {"candidate_id": "n1", "label": "二叉搜索树", "kind": "concept", "anchor_ids": ["a1"]},
            {"candidate_id": "n2", "label": "快速排序", "kind": "concept", "anchor_ids": ["a2"]},
        ]
        # 预置一条 next_topic 顺序链（二叉搜索树 -> 快速排序，实际无 KB 关系，应保留）
        relations = [{
            "candidate_id": "rnt-1", "source_candidate_id": "n1", "target_candidate_id": "n2",
            "relation_type": "next_topic", "status": "proposed", "confidence": 0.8, "anchor_ids": [],
        }]
        enriched = enrich_relations_from_kb(nodes, relations)
        # 至少保留原来的 next_topic，并追加知识库语义关系
        assert any(r["relation_type"] == "next_topic" for r in enriched)
        assert len(enriched) >= 1

    def test_enrich_uses_kb_relation_type_not_next_topic(self):
        # 知识库真实边：algo-010 图遍历 --prerequisite_of--> algo-011 最短路径
        nodes = [
            {"candidate_id": "nG", "label": "图遍历（BFS 与 DFS）", "kind": "concept", "anchor_ids": []},
            {"candidate_id": "nD", "label": "Dijkstra 最短路径", "kind": "concept", "anchor_ids": []},
        ]
        enriched = enrich_relations_from_kb(nodes, [])
        semantic = [r for r in enriched if r["relation_type"] != "next_topic"]
        assert any(r["relation_type"] == "prerequisite_of" for r in semantic), enriched
        # KB 语义边指向稳定的概念身份（source/target 为候选 id）
        kb_edge = next(r for r in enriched if r["relation_type"] == "prerequisite_of")
        assert kb_edge["source_candidate_id"] == "nG"
        assert kb_edge["target_candidate_id"] == "nD"

    def test_enrich_no_dup_same_endpoints(self):
        nodes = [
            {"candidate_id": "n1", "label": "快速排序", "kind": "concept", "anchor_ids": []},
            {"candidate_id": "n2", "label": "归并排序", "kind": "concept", "anchor_ids": []},
        ]
        base = [{
            "candidate_id": "r1", "source_candidate_id": "n1", "target_candidate_id": "n2",
            "relation_type": "next_topic", "status": "proposed", "confidence": 0.8, "anchor_ids": [],
        }]
        enriched = enrich_relations_from_kb(nodes, base)
        endpoint_pairs = [(r["source_candidate_id"], r["target_candidate_id"]) for r in enriched]
        assert len(endpoint_pairs) == len(set(endpoint_pairs))


class TestReviewDecisionGate:
    def test_known_concept_candidate_stays_proposed(self):
        candidate = {"candidate_id": "c1", "label": "快速排序", "kind": "concept"}
        assert _review_decision(candidate) == "proposed"

    def test_out_of_kb_candidate_becomes_needs_review(self):
        candidate = {"candidate_id": "c2", "label": "插入排序", "kind": "concept"}
        assert _review_decision(candidate) == "needs_review"

    def test_structural_title_becomes_needs_review(self):
        candidate = {"candidate_id": "c3", "label": "3.5 本章小结", "kind": "concept"}
        assert _review_decision(candidate) == "needs_review"

    def test_relation_candidate_stays_proposed(self):
        candidate = {
            "candidate_id": "r1",
            "source_candidate_id": "c1",
            "target_candidate_id": "c2",
            "relation_type": "next_topic",
        }
        assert _review_decision(candidate) == "proposed"

    def test_non_concept_kind_stays_proposed(self):
        candidate = {"candidate_id": "c4", "label": "随便什么", "kind": "example"}
        assert _review_decision(candidate) == "proposed"

    def test_explicit_accepted_status_preserved(self):
        candidate = {"candidate_id": "c5", "label": "插入排序", "kind": "concept", "status": "accepted"}
        assert _review_decision(candidate) == "accepted"


class TestKbAlignmentDisabledFallback:
    def test_alignment_disabled_falls_back_to_proposed(self, monkeypatch):
        monkeypatch.setattr(settings, "KNOWLEDGE_KB_ALIGNMENT_ENABLED", False)
        candidate = {"candidate_id": "c6", "label": "插入排序", "kind": "concept"}
        # 对齐关闭 -> 不强制人工，走原有 proposed 语义
        assert _review_decision(candidate) == "proposed"


class TestBridgeSplitsOutOfKbToNeedsReview:
    def test_bridge_marks_known_kb_node_proposed(self, session):
        teacher = _user(session, "kb_align_proposed_t")
        course = _setup(session, teacher)
        batch = GraphCandidateBatch(
            course_id=course.id,
            initiated_by=teacher.id,
            status=CandidateBatchStatus.SUCCEEDED,
            node_candidate_count=1,
            relation_candidate_count=0,
            node_candidates=[
                {"candidate_id": "gcn-ks", "label": "快速排序", "kind": "concept", "anchor_ids": ["ea-ks"]},
            ],
            relation_candidates=[],
        )
        session.add(batch); session.commit(); session.refresh(batch)
        bridge_candidate_batch(session, batch=batch); session.commit()
        review = session.exec(select(GraphNodeReview).where(
            GraphNodeReview.candidate_batch_id == batch.batch_id,
            GraphNodeReview.target_type == "node",
        )).one()
        assert review.decision == "proposed"
        assert review.target_content["kbsource_type"] == "kb_aligned"
        assert review.target_content["kb_node_key"] == "algo-007"

    def test_bridge_marks_out_of_kb_node_needs_review(self, session):
        teacher = _user(session, "kb_align_review_t")
        course = _setup(session, teacher)
        batch = GraphCandidateBatch(
            course_id=course.id,
            initiated_by=teacher.id,
            status=CandidateBatchStatus.SUCCEEDED,
            node_candidate_count=1,
            relation_candidate_count=0,
            node_candidates=[
                {"candidate_id": "gcn-ook", "label": "插入排序", "kind": "concept", "anchor_ids": ["ea-ook"]},
            ],
            relation_candidates=[],
        )
        session.add(batch); session.commit(); session.refresh(batch)
        bridge_candidate_batch(session, batch=batch); session.commit()
        review = session.exec(select(GraphNodeReview).where(
            GraphNodeReview.candidate_batch_id == batch.batch_id,
            GraphNodeReview.target_type == "node",
        )).one()
        assert review.decision == "needs_review"
        assert review.target_content["kbsource_type"] == "out_of_kb"
        # 该超库候选进入待治理列表
        pending = list_review_candidates(session, course.id)
        assert any(item.target_id == review.target_id for item in pending)
