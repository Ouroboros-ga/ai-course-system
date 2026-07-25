"""Regression tests for TeachingAgent privacy-minimized persistence."""
from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlmodel import SQLModel, Session, select

from app.common.db_migrator import (
    AGENT_LOG_MIGRATION_BATCH,
    _minimize_agent_logs,
    agent_log_preflight,
    rollback_agent_log_minimization,
)
from app.models.agent_log import AgentConversationSession, AgentLearningEvent, AgentTraceRecord
from app.platform.agents.tools.conversation_context import SessionScopedConversationContextPort
from app.platform.agents.tools.learning_event import make_session_scoped_learning_event_port


def test_agent_log_port_strips_raw_message_answer_and_trace(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'agent.sqlite'}")
    SQLModel.metadata.create_all(engine)
    port = make_session_scoped_learning_event_port(lambda: Session(engine))
    asyncio.run(port.record_learning_event(event={
        "trace_id": "trace-1", "student_id": 1, "course_id": 2, "session_id": "s-1",
        "final_answer": "secret answer", "user_message": "secret question", "warnings": ["WARN"],
    }))
    asyncio.run(port.record_agent_trace(trace={
        "trace_id": "trace-1", "student_id": 1, "course_id": 2, "session_id": "s-1",
        "input": {"message": "secret question"}, "final_answer": "secret answer",
        "nodes": [{"node": "retrieve_evidence"}], "retrieved_evidence": [{"evidence_id": "ev-1", "text": "secret evidence"}],
    }))
    with Session(engine) as session:
        event = session.exec(select(AgentLearningEvent)).one()
        trace = session.exec(select(AgentTraceRecord)).one()
    assert "secret" not in event.event_data
    assert "secret" not in trace.trace_data
    assert json.loads(trace.trace_data)["evidence_ids"] == ["ev-1"]


def test_conversation_context_reuses_structured_state_and_expires(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'context.sqlite'}")
    SQLModel.metadata.create_all(engine)
    port = SessionScopedConversationContextPort(lambda: Session(engine))
    asyncio.run(port.save_context(student_id="1", course_id="2", session_id="s-1", context={
        "current_concept_id": "node-1", "last_intent": "course_question", "raw_answer": "must disappear",
    }))
    loaded = asyncio.run(port.load_context(student_id="1", course_id="2", session_id="s-1"))
    assert loaded == {"current_concept_id": "node-1", "last_intent": "course_question", "warnings": [], "reason_codes": []}
    with Session(engine) as session:
        record = session.exec(select(AgentConversationSession)).one()
        record.updated_at = datetime.utcnow() - timedelta(minutes=31)
        session.add(record)
        session.commit()
    assert asyncio.run(port.load_context(student_id="1", course_id="2", session_id="s-1")) is None


def test_agent_log_migration_redacts_existing_payload_once_and_rolls_back_marker(tmp_path):
    path = tmp_path / "migration.sqlite"
    engine = create_engine(f"sqlite:///{path}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(AgentLearningEvent(trace_id="t", student_id=1, course_id=2, session_id="s", event_data='{"final_answer":"raw"}'))
        session.add(AgentTraceRecord(trace_id="t", student_id=1, course_id=2, trace_data='{"message":"raw"}'))
        session.commit()
    assert agent_log_preflight(str(path))["ok"]
    conn = sqlite3.connect(path)
    try:
        events, traces = _minimize_agent_logs(conn.cursor())
        conn.commit()
        assert (events, traces) == (1, 1)
        assert _minimize_agent_logs(conn.cursor()) == (0, 0)
        conn.commit()
    finally:
        conn.close()
    assert rollback_agent_log_minimization(str(path)) == {"agent_log_migration_records": 1}
