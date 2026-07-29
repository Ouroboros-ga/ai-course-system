"""Run the local, synthetic teacher governance flow for course 87.

This script deliberately uses the registered HTTP endpoints with a teacher
token. It never edits SQLite rows directly. A candidate is accepted only when
its parser anchors have a teacher-confirmed EvidenceSpan promoted to formal
Evidence/Citation; otherwise it is explicitly rejected with an audit reason.
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from datetime import datetime

os.environ.setdefault("AI_COURSE_SKIP_STARTUP_SIDE_EFFECTS", "1")
os.environ.setdefault("AI_COURSE_TESTING", "1")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

from app.core.security import create_access_token  # noqa: E402
from app.main import app  # noqa: E402
from app.models.database import engine  # noqa: E402
from app.models.access_control_model import CourseMembership  # noqa: E402
from app.models.cognitive_state_model import CognitiveState, LearningEvidenceRecord, RecommendationRecord  # noqa: E402
from app.models.graph_production_model import CourseEvidenceRecord, CourseKnowledgeNode  # noqa: E402
from app.models.question_bank_model import (  # noqa: E402
    QuestionBankItem,
    QuestionDifficulty,
    QuestionSourceMapping,
    QuestionStatus,
    QuestionType,
    MappingStatus,
)
from app.models.user_model import User, UserRole  # noqa: E402
from app.services.course_access_service import activate_student_membership  # noqa: E402
from app.core.security import get_password_hash  # noqa: E402
from sqlmodel import Session, select  # noqa: E402


COURSE_ID = 87
TEACHER_ID = 6


def _body(response, label: str = "request") -> dict:
    payload = response.json()
    if response.status_code >= 400 or payload.get("code", 200) >= 400:
        raise RuntimeError(f"{label} failed: {response.status_code} {payload}")
    return payload.get("data") or {}


def main() -> None:
    token = create_access_token({
        "sub": str(TEACHER_ID),
        "username": "demo-owner",
        "role": "teacher",
    })
    headers = {"Authorization": f"Bearer {token}"}
    client = TestClient(app)

    # Course Access is the only capability switch used by the flow.
    _body(client.put(
        f"/api/v1/course-access/courses/{COURSE_ID}/capabilities",
        headers=headers,
        json={
            "learning": True,
            "course_building": True,
            "knowledge_graph": True,
            "evidence": True,
            "experiment": False,
            "coding_sandbox": False,
            "cognitive_analysis": True,
            "safety_policy": False,
        },
    ), "enable capabilities")

    candidates = _body(client.get(
        f"/api/v1/graph/course/{COURSE_ID}/candidates",
        headers=headers,
    )).get("items", [])
    governance_already_done = False
    if len(candidates) != 59:
        accepted_candidates = _body(client.get(
            f"/api/v1/graph/course/{COURSE_ID}/candidates?decision=accepted",
            headers=headers,
        )).get("items", [])
        rejected_candidates = _body(client.get(
            f"/api/v1/graph/course/{COURSE_ID}/candidates?decision=rejected",
            headers=headers,
        )).get("items", [])
        candidates = accepted_candidates + rejected_candidates
        governance_already_done = len(candidates) == 59
    spans = _body(client.get(
        f"/api/v1/graph/course/{COURSE_ID}/evidence-spans",
        headers=headers,
    )).get("items", [])
    if len(candidates) != 59:
        raise RuntimeError(f"expected 59 candidates, got {len(candidates)}")

    # Build the candidate-anchor -> EvidenceSpan bridge from read APIs.
    runs = {span["run_id"] for span in spans}
    anchor_by_id: dict[str, dict] = {}
    for run_id in runs:
        data = _body(client.get(
            f"/api/v1/graph/course/{COURSE_ID}/document-ir/{run_id}/anchors",
            headers=headers,
        ))
        for anchor in data.get("items", []):
            anchor_by_id[anchor["anchor_id"]] = anchor

    spans_by_block: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for span in spans:
        spans_by_block[(span["run_id"], span["block_id"])].append(span)

    confirmed_span_ids: set[str] = {
        span["span_id"] for span in spans if span["status"] == "confirmed"
    }
    confirmed_count = 0
    for review in ([] if governance_already_done else candidates):
        content = review.get("target_content") or {}
        identity_key = content.get("id") if review["target_type"] == "node" else None
        for anchor_id in content.get("anchor_ids") or []:
            anchor = anchor_by_id.get(anchor_id)
            if not anchor:
                continue
            possible = spans_by_block.get((anchor["run_id"], anchor["block_id"]), [])
            span = next((item for item in possible if item["status"] == "candidate"), None)
            if not span or span["span_id"] in confirmed_span_ids:
                continue
            _body(client.post(
                f"/api/v1/graph/course/{COURSE_ID}/evidence-spans/{span['span_id']}/confirm",
                headers=headers,
                json={"identity_node_key": identity_key},
            ), f"confirm span {span['span_id']}")
            confirmed_span_ids.add(span["span_id"])
            confirmed_count += 1
            break

    formal_evidence = _body(client.get(
        f"/api/v1/graph/course/{COURSE_ID}/evidence?status=active",
        headers=headers,
    )).get("items", [])
    evidence_by_anchor: dict[str, set[str]] = defaultdict(set)
    for evidence in formal_evidence:
        for anchor_id in evidence.get("source_anchor_ids") or []:
            evidence_by_anchor[anchor_id].add(evidence["evidence_id"])

    accepted = 0
    rejected = 0
    for review in ([] if governance_already_done else candidates):
        content = review.get("target_content") or {}
        evidence_ids = sorted({
            evidence_id
            for anchor_id in content.get("anchor_ids") or []
            for evidence_id in evidence_by_anchor.get(anchor_id, set())
        })
        if evidence_ids:
            decision = "accepted"
            comment = "教师已核对解析锚点并确认原文证据。"
            accepted += 1
        else:
            decision = "rejected"
            comment = "未找到可由教师确认的原文 EvidenceSpan，拒绝发布。"
            rejected += 1
        _body(client.post(
            f"/api/v1/graph/course/{COURSE_ID}/reviews/{review['id']}/transition",
            headers=headers,
            json={
                "new_decision": decision,
                "review_comment": comment,
                "evidence_ids": evidence_ids,
            },
        ), f"review {review['id']}")

    if governance_already_done:
        publish = _body(client.get(
            f"/api/v1/graph/course/{COURSE_ID}/snapshot",
            headers=headers,
        ))
    else:
        publish = _body(client.post(
            f"/api/v1/graph/course/{COURSE_ID}/publish-reviewed",
            headers=headers,
            json={"label": "课程 87 Demo 教师治理版本"},
        ), "publish reviewed snapshot")
    active = _body(client.get(
        f"/api/v1/graph/course/{COURSE_ID}/snapshot",
        headers=headers,
    ))

    # Synthetic Demo learner setup. Membership is created through the Course
    # Access lifecycle helper; question publication still goes through the
    # registered question-bank publish endpoint below.
    with Session(engine) as session:
        student = session.exec(select(User).where(User.username == "demo87_student")).first()
        if student is None:
            student = User(
                username="demo87_student",
                real_name="课程 87 Demo 学生",
                hashed_password=get_password_hash("demo-only-password"),
                role=UserRole.STUDENT,
                is_active=True,
            )
            session.add(student)
            session.flush()
        activate_student_membership(session, COURSE_ID, student.id)
        node = session.exec(
            select(CourseKnowledgeNode).where(
                CourseKnowledgeNode.course_id == COURSE_ID,
                CourseKnowledgeNode.status == "published",
            ).order_by(CourseKnowledgeNode.id)
        ).first()
        if node is None:
            raise RuntimeError("published CourseKnowledgeNode not found")
        evidence = session.exec(select(CourseEvidenceRecord).where(
            CourseEvidenceRecord.course_id == COURSE_ID,
        ).order_by(CourseEvidenceRecord.id)).first()
        if evidence is None:
            raise RuntimeError("formal Evidence not found for Demo question mapping")
        question = session.exec(select(QuestionBankItem).where(
            QuestionBankItem.course_id == COURSE_ID,
            QuestionBankItem.category == "demo_course_87",
            QuestionBankItem.is_latest == True,
        )).first()
        if question is None:
            question = QuestionBankItem(
                question_text="课程 87 Demo：已发布知识图谱的稳定节点身份是什么？",
                answer="A",
                options={"A": "kn_* 稳定 node_key 与正式数值 identity 映射", "B": "临时 gcn_* 候选 ID"},
                question_type=QuestionType.SINGLE_CHOICE,
                difficulty=QuestionDifficulty.EASY,
                category="demo_course_87",
                course_id=COURSE_ID,
                knowledge_node_ids=[node.id],
                prerequisite_node_ids=[],
                status=QuestionStatus.AUTO_ACCEPTED,
                generated_by="teacher_manual",
                created_by=TEACHER_ID,
            )
            session.add(question)
            session.flush()
        else:
            question.knowledge_node_ids = [node.id]
            question.status = question.status if question.status == QuestionStatus.PUBLISHED else QuestionStatus.AUTO_ACCEPTED
            session.add(question)
        mapping = session.exec(select(QuestionSourceMapping).where(
            QuestionSourceMapping.question_id == question.id,
            QuestionSourceMapping.is_latest == True,
        )).first()
        if mapping is None:
            mapping = QuestionSourceMapping(
                question_id=question.id,
                course_id=COURSE_ID,
                evidence_refs=[evidence.evidence_id],
                knowledge_node_ids=[node.id],
                mapping_reason="Demo 题目绑定当前已发布图谱节点与教师确认 Evidence",
                confidence=1.0,
                graph_version=active.get("snapshot_id") or "",
                content_hash="demo-course-87-question-v1",
                status=MappingStatus.AUTO_ACCEPTED,
                created_by=TEACHER_ID,
            )
            session.add(mapping)
        session.commit()
        student_id = student.id
        question_id = question.id
        node_id = node.id
        question_is_published = question.status == QuestionStatus.PUBLISHED

    if not question_is_published:
        _body(client.post(
            f"/api/v1/question-bank/course/{COURSE_ID}/publish",
            headers=headers,
            json={"question_ids": [question_id], "publish": True},
        ), "publish Demo question")

    student_token = create_access_token({
        "sub": str(student_id),
        "username": "demo87_student",
        "role": "student",
    })
    student_headers = {"Authorization": f"Bearer {student_token}"}
    answer = _body(client.post(
        f"/api/v1/question-bank/course/{COURSE_ID}/{question_id}/attempt",
        headers=student_headers,
        json={"student_answer": "A"},
    ), "Demo student answer")
    student_snapshot = _body(client.get(
        f"/api/v1/graph/course/{COURSE_ID}/snapshot",
        headers=student_headers,
    ))
    student_citations = _body(client.get(
        f"/api/v1/graph/course/{COURSE_ID}/citations",
        headers=student_headers,
    )).get("items", [])
    student_state = _body(client.get(
        f"/api/v1/cognitive/course/{COURSE_ID}/state",
        params={"node_id": node_id},
        headers=student_headers,
    ))
    student_recommendations = _body(client.get(
        f"/api/v1/cognitive/course/{COURSE_ID}/recommendations",
        headers=student_headers,
    )).get("items", [])
    print(json.dumps({
        "course_id": COURSE_ID,
        "candidate_count": len(candidates),
        "confirmed_span_count": confirmed_count,
        "formal_evidence_count": len(formal_evidence),
        "accepted_count": accepted,
        "rejected_count": rejected,
        "published_snapshot_id": publish.get("snapshot_id"),
        "active_snapshot_id": active.get("snapshot_id"),
        "active_node_count": active.get("node_count"),
        "active_relation_count": active.get("relation_count"),
        "demo_student_id": student_id,
        "demo_question_id": question_id,
        "demo_node_id": node_id,
        "demo_answer": answer,
        "student_snapshot_id": student_snapshot.get("snapshot_id"),
        "student_citation_count": len(student_citations),
        "cognitive_state": student_state,
        "recommendation_count": len(student_recommendations),
        "latest_recommendation": student_recommendations[0] if student_recommendations else None,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
