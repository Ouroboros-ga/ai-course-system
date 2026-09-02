"""课程学情诊断报告服务（助教场景，挑战杯 XH-202620）。

确定性规则聚合（非模型预测）：遍历课程活跃学生的最新六维认知状态，按 M3 判弱条件
（表现分有值、样本量达标、衰减后置信度达标、表现分 < 0.5，与 learning_path_service
判弱口径一致）标记薄弱知识节点，并按薄弱学生人数汇总为课程级诊断报告。

数据最小化：报告只返回学生/节点 id 与聚合数值，不含个人敏感内容；只读不写库、不调 LLM。
"""
from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from app.core.time_utils import utcnow_aware
from app.models.access_control_model import CourseMembership, CourseRole, MembershipStatus
from app.models.cognitive_state_model import COGNITIVE_POLICY_VERSION, CognitiveState
from app.models.course_outline_model import CourseOutlineNode, OutlineNodeType
from app.services.cognitive_decay_service import decayed_confidence
from app.services.cognitive_service import MIN_SAMPLE_FOR_PERFORMANCE
from app.services.recommendation_service import PREREQ_WEAK_CONFIDENCE, PREREQ_WEAK_PERF

REPORT_TYPE = "course_diagnosis/rule-baseline-v1"
MAX_WEAK_NODES = 20
MAX_SAMPLE_IDS = 20
SUGGESTED_ACTION = "安排针对性复习与前置知识补学"


def _student_node_is_weak(state: CognitiveState | None) -> bool:
    """M3 判弱条件（与 learning_path_service._node_is_weak 口径一致）。"""
    if state is None or state.observed_performance_score is None:
        return False
    if (state.sample_size or 0) < MIN_SAMPLE_FOR_PERFORMANCE:
        return False
    decayed = decayed_confidence(state.evidence_confidence, computed_at=state.computed_at)
    if decayed is None or decayed < PREREQ_WEAK_CONFIDENCE:
        return False
    return state.observed_performance_score < PREREQ_WEAK_PERF


def build_course_diagnosis(
    session: Session,
    *,
    course_id: int,
    max_weak_nodes: int = MAX_WEAK_NODES,
) -> dict[str, Any]:
    """生成课程级学情诊断报告（只读，不落库、不调 LLM）。"""
    memberships = session.exec(
        select(CourseMembership).where(
            CourseMembership.course_id == course_id,
            CourseMembership.role == CourseRole.STUDENT,
            CourseMembership.status == MembershipStatus.ACTIVE,
        )
    ).all()
    student_ids = [m.user_id for m in memberships]

    titles: dict[int, str] = {}
    nodes = session.exec(
        select(CourseOutlineNode).where(CourseOutlineNode.course_id == course_id)
    ).all()
    for node in nodes:
        if node.node_type == OutlineNodeType.KNOWLEDGE_POINT:
            titles[node.id] = node.title

    weak_by_node: dict[int, dict[str, Any]] = {}
    for student_id in student_ids:
        latest_states = session.exec(
            select(CognitiveState).where(
                CognitiveState.student_id == student_id,
                CognitiveState.course_id == course_id,
                CognitiveState.node_id.is_not(None),
                CognitiveState.is_latest == True,  # noqa: E712
            )
        ).all()
        for state in latest_states:
            if not _student_node_is_weak(state):
                continue
            node_id = int(state.node_id)
            entry = weak_by_node.setdefault(
                node_id,
                {"weak_student_ids": [], "perf_sum": 0.0, "perf_count": 0},
            )
            entry["weak_student_ids"].append(student_id)
            entry["perf_sum"] += state.observed_performance_score or 0.0
            entry["perf_count"] += 1

    weak_nodes: list[dict[str, Any]] = []
    for node_id, entry in weak_by_node.items():
        ids = entry["weak_student_ids"]
        weak_nodes.append({
            "node_id": node_id,
            "title": titles.get(node_id) or f"知识点#{node_id}",
            "weak_student_count": len(ids),
            "weak_students_sample": ids[:MAX_SAMPLE_IDS],
            "avg_observed_performance": round(
                entry["perf_sum"] / max(entry["perf_count"], 1), 3
            ),
            "suggested_action": SUGGESTED_ACTION,
        })
    weak_nodes.sort(key=lambda row: (-row["weak_student_count"], row["node_id"]))
    weak_nodes = weak_nodes[:max_weak_nodes]

    return {
        "report_type": REPORT_TYPE,
        "policy_version": COGNITIVE_POLICY_VERSION,
        "course_id": course_id,
        "generated_at": utcnow_aware().isoformat(),
        "student_count": len(student_ids),
        "weak_node_count": len(weak_nodes),
        "weak_nodes": weak_nodes,
        "caveats": [
            "规则基线确定性聚合，非模型预测；不写入掌握度/推荐/正式证据/课程图谱",
            "判弱条件：表现分有值、样本量≥3、衰减后置信度≥0.6、表现分<0.5",
            "报告仅返回学生/节点 id 与聚合值，不含个人敏感内容",
        ],
    }
