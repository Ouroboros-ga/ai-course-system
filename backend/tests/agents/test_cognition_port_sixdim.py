"""CognitionPort: six-dimension serialization + weak-prerequisite wiring tests.

回归目标（2026-08-16）：
- _serialize_recommendation 必须把 reason_codes 里的 weak_prerequisite_node={key}
  还原为 confirmed_weak_prerequisite_set，供 StudentModelingPort 消费；
- 课程级 get_recommendation（node_id=None）取该学生最近一条推荐（不限 node 作用域），
  否则挂在当前知识点 node 上的 prereq_review 推荐永远取不到，weak_concepts 恒为空；
- CognitionStudentModelingPort.get_weak_concepts 直接消费该结构化集合。
"""
from __future__ import annotations

import asyncio
import uuid

from sqlmodel import Session, select

from app.core.security import get_password_hash
from app.models.cognitive_state_model import RecommendationRecord
from app.models.course_model import Course, CourseStatus
from app.models.graph_production_model import CourseKnowledgeNode
from app.models.user_model import User, UserRole
from app.platform.agents.providers.cognition.cognition import (
    make_session_scoped_cognition_port,
)
from app.platform.agents.providers.cognition.student_model import (
    CognitionStudentModelingPort,
)
from app.platform.agents.providers.recommendation.recommendation import (
    make_session_scoped_recommendation_port,
)


def _student_and_course(session) -> tuple[User, Course]:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"cog-weak-{suffix}",
        hashed_password=get_password_hash("test-password"),
        role=UserRole.STUDENT,
        is_active=True,
    )
    session.add(user)
    session.flush()
    course = Course(
        fanya_course_id=f"cog-weak-{suffix}",
        fanya_course_name="认知端口回归课程",
        title="认知端口回归课程",
        teacher_id=user.id,
        status=CourseStatus.PUBLISHED,
    )
    session.add(course)
    session.flush()
    return user, course


def _port_session_factory(test_engine):
    def _factory() -> Session:
        return Session(test_engine)

    return _factory


def test_course_level_recommendation_exposes_confirmed_weak_prerequisite(
    session, test_engine
):
    user, course = _student_and_course(session)
    session.add(RecommendationRecord(
        recommendation_id="rec-weak-1",
        student_id=user.id,
        course_id=course.id,
        node_id=42,
        recommendation_type="prereq_review",
        priority="high",
        title="补学前置知识点",
        description="已确认薄弱前置",
        reason_codes=[
            "confirmed_weak_prerequisite",
            "prerequisite_review",
            "weak_prerequisite_node=ordered-array",
        ],
        evidence_refs=["ev-1"],
        knowledge_node_ids=[999],
        cognitive_snapshot={"mastery_score": 0.4, "evidence_confidence": 0.85},
    ))
    session.commit()

    port = make_session_scoped_cognition_port(_port_session_factory(test_engine))
    # node_id=None（课程级）：必须能取到挂在 node 上的最近一条推荐。
    rec = asyncio.run(port.get_recommendation(
        student_id=str(user.id), course_id=str(course.id), node_id=None,
    ))
    assert rec is not None
    assert rec["confirmed_weak_prerequisite_set"] == [
        {"concept_id": "ordered-array"}
    ]
    assert rec["cognitive_snapshot"]["evidence_confidence"] == 0.85

    adapter = CognitionStudentModelingPort(port)
    weak = asyncio.run(adapter.get_weak_concepts(
        student_id=str(user.id), course_id=str(course.id),
    ))
    assert weak == [{"concept_id": "ordered-array"}]


def test_node_scoped_recommendation_still_respects_node_filter(session, test_engine):
    user, course = _student_and_course(session)
    session.add(RecommendationRecord(
        recommendation_id="rec-weak-node-a",
        student_id=user.id,
        course_id=course.id,
        node_id=42,
        recommendation_type="prereq_review",
        priority="high",
        title="节点A补前置",
        reason_codes=["weak_prerequisite_node=node-a"],
    ))
    session.add(RecommendationRecord(
        recommendation_id="rec-weak-node-b",
        student_id=user.id,
        course_id=course.id,
        node_id=43,
        recommendation_type="prereq_review",
        priority="high",
        title="节点B补前置",
        reason_codes=["weak_prerequisite_node=node-b"],
    ))
    session.commit()

    port = make_session_scoped_cognition_port(_port_session_factory(test_engine))
    rec = asyncio.run(port.get_recommendation(
        student_id=str(user.id), course_id=str(course.id), node_id="43",
    ))
    assert rec is not None
    assert rec["recommendation_id"] == "rec-weak-node-b"
    assert rec["confirmed_weak_prerequisite_set"] == [{"concept_id": "node-b"}]


def test_recommendation_without_weak_codes_has_empty_set(session, test_engine):
    user, course = _student_and_course(session)
    session.add(RecommendationRecord(
        recommendation_id="rec-plain-1",
        student_id=user.id,
        course_id=course.id,
        node_id=None,
        recommendation_type="advance_next",
        priority="medium",
        title="继续学习",
        reason_codes=["advance_next"],
    ))
    session.commit()

    port = make_session_scoped_cognition_port(_port_session_factory(test_engine))
    rec = asyncio.run(port.get_recommendation(
        student_id=str(user.id), course_id=str(course.id), node_id=None,
    ))
    assert rec is not None
    assert rec["confirmed_weak_prerequisite_set"] == []
    assert rec["cognitive_snapshot"] == {}


def test_recommendation_port_resolves_node_key_to_course_local_node(
    session, test_engine
):
    """回归（2026-08-16）：问答链路推荐必须按节点作用域生成。

    工作流传入的 concept_id 是图节点 node_key（如 kn_xxx），端口必须经课程
    身份表解析为数字节点 id；否则 generate_recommendation 退化为课程级，
    _find_confirmed_weak_prerequisites 恒为空，prereq_review 推荐无法产生，
    prerequisite_review 教学动作与回顾提示框都不会触发。
    """
    user, course = _student_and_course(session)
    node = CourseKnowledgeNode(
        course_id=course.id,
        node_key="kn-demo",
        title="Demo Node",
    )
    session.add(node)
    session.commit()
    session.refresh(node)

    port = make_session_scoped_recommendation_port(_port_session_factory(test_engine))
    result = asyncio.run(port.recommend_next_action(
        student_id=str(user.id),
        course_id=str(course.id),
        concept_id="kn-demo",
        action="normal_answer",
        graph_context={},
        student_state={},
    ))
    assert result is not None
    with Session(test_engine) as check:
        record = check.exec(
            select(RecommendationRecord).order_by(
                RecommendationRecord.created_at.desc()
            )
        ).first()
        assert record is not None
        assert record.node_id == node.id
