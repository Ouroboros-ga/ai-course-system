"""Conversation Domain selection stays learner/course scoped and turn-complete."""
from __future__ import annotations

import asyncio
from datetime import timedelta

from sqlmodel import Session, SQLModel, create_engine

from app.core.time_utils import utcnow_aware
from app.models.conversation_model import ConversationMessage
from app.models.course_model import Course
from app.models.user_model import User
from app.platform.agents.providers.teaching.conversation_history import (
    SessionScopedConversationHistoryPort,
)


def test_history_provider_filters_foreign_expired_and_incomplete_turns(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'history.db'}")
    SQLModel.metadata.create_all(
        engine,
        tables=[User.__table__, Course.__table__, ConversationMessage.__table__],
    )
    now = utcnow_aware()
    with Session(engine) as session:
        teacher = User(username="history_teacher", hashed_password="test")
        learner = User(username="history_learner", hashed_password="test")
        foreign = User(username="history_foreign", hashed_password="test")
        session.add(teacher)
        session.add(learner)
        session.add(foreign)
        session.flush()
        course = Course(
            fanya_course_id="history-course",
            fanya_course_name="History",
            title="History",
            teacher_id=teacher.id,
        )
        other_course = Course(
            fanya_course_id="other-history-course",
            fanya_course_name="Other history",
            title="Other history",
            teacher_id=teacher.id,
        )
        session.add(course)
        session.add(other_course)
        session.flush()

        def add_turn(
            *,
            trace: str,
            student: int,
            target_course: int,
            user: str,
            assistant: str | None,
            retention_until=None,
        ) -> None:
            session.add(
                ConversationMessage(
                    student_id=student,
                    course_id=target_course,
                    session_id="session-current",
                    trace_id=trace,
                    role="user",
                    content=user,
                    concept_id="binary-search",
                    retention_until=retention_until or now + timedelta(days=1),
                )
            )
            if assistant is not None:
                session.add(
                    ConversationMessage(
                        student_id=student,
                        course_id=target_course,
                        session_id="session-current",
                        trace_id=trace,
                        role="assistant",
                        content=assistant,
                        concept_id="binary-search",
                        retention_until=retention_until or now + timedelta(days=1),
                    )
                )

        add_turn(
            trace="own-complete",
            student=learner.id,
            target_course=course.id,
            user="OWN QUESTION",
            assistant="OWN ANSWER",
        )
        add_turn(
            trace="foreign-student",
            student=foreign.id,
            target_course=course.id,
            user="FOREIGN STUDENT QUESTION",
            assistant="FOREIGN STUDENT ANSWER",
        )
        add_turn(
            trace="foreign-course",
            student=learner.id,
            target_course=other_course.id,
            user="FOREIGN COURSE QUESTION",
            assistant="FOREIGN COURSE ANSWER",
        )
        add_turn(
            trace="expired",
            student=learner.id,
            target_course=course.id,
            user="EXPIRED QUESTION",
            assistant="EXPIRED ANSWER",
            retention_until=now - timedelta(minutes=1),
        )
        add_turn(
            trace="incomplete",
            student=learner.id,
            target_course=course.id,
            user="INCOMPLETE QUESTION",
            assistant=None,
        )
        session.commit()
        learner_id = learner.id
        course_id = course.id

    port = SessionScopedConversationHistoryPort(lambda: Session(engine))
    turns = asyncio.run(
        port.select_relevant_turns(
            student_id=str(learner_id),
            course_id=str(course_id),
            session_id="session-current",
            message="current question",
            concept_id="binary-search",
            resource_id=None,
            max_chars=3_600,
        )
    )

    assert turns == [
        {
            "user": "OWN QUESTION",
            "assistant": "OWN ANSWER",
            "concept_id": "binary-search",
            "resource_id": None,
            "source_session_id": "session-current",
        }
    ]
    engine.dispose()
