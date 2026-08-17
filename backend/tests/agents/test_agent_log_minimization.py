"""Regression tests for TeachingAgent privacy-minimized persistence."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlmodel import Session, SQLModel, select

from app.models.agent_log import (
    AgentConversationSession,
    AgentLearningEvent,
    AgentLogMigrationRecord,
    AgentTraceRecord,
)
from app.platform.agents.tools.conversation_context import (
    SessionScopedConversationContextPort,
)
from app.platform.agents.tools.learning_event import (
    make_session_scoped_learning_event_port,
)


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


def test_agent_log_migration_redacts_existing_payload_once_and_rolls_back_marker(
    tmp_path, run_alembic
):
    """alembic revision 0003 redacts raw agent logs once and is irreversible.

    验证：
    - upgrade 0002 -> head：脱敏已有 raw payload，并写入 agent_log_migration_records 账本。
    - downgrade 0002：账本记录被删除，但原始内容不恢复（隐私脱敏不可逆）。
    - 再次 upgrade head：幂等，0 行被脱敏（已有 migration_batch_id），账本记录 (0, 0)。
    """
    path = tmp_path / "migration.sqlite"
    db_path = str(path)

    # 1. 用 alembic upgrade 0002 建库（跳过 0003 脱敏，确保后续可验证脱敏过程）。
    run_alembic(db_path, "upgrade", "0002")

    # 2. 插入原始未脱敏的 agent 日志（migration_batch_id 默认 None，符合 legacy 状态）。
    engine = create_engine(f"sqlite:///{path}")
    with Session(engine) as session:
        session.add(AgentLearningEvent(
            trace_id="t", student_id=1, course_id=2, session_id="s",
            event_data='{"final_answer":"raw"}',
        ))
        session.add(AgentTraceRecord(
            trace_id="t", student_id=1, course_id=2,
            trace_data='{"message":"raw"}',
        ))
        session.commit()
    engine.dispose()

    # 3. 执行 alembic upgrade 0003，应用脱敏（限定 0003：0062 数据归一化不可逆，
    #    全链 head 降级会跨 0062 失败；本测试只验证 0003 脱敏账本语义）。
    run_alembic(db_path, "upgrade", "0003")

    # 4. 验证脱敏生效 + 账本记录。
    engine = create_engine(f"sqlite:///{path}")
    with Session(engine) as session:
        event = session.exec(select(AgentLearningEvent)).one()
        trace = session.exec(select(AgentTraceRecord)).one()
        assert "raw" not in event.event_data
        assert "raw" not in trace.trace_data
        assert json.loads(event.event_data)["reason_codes"] == ["LEGACY_RAW_PAYLOAD_REDACTED"]
        assert json.loads(trace.trace_data)["reason_codes"] == ["LEGACY_RAW_PAYLOAD_REDACTED"]
        assert event.migration_batch_id == "agent-log-minimization-v1"
        assert trace.migration_batch_id == "agent-log-minimization-v1"

        ledger = session.exec(select(AgentLogMigrationRecord)).one()
        assert ledger.batch_id == "agent-log-minimization-v1"
        assert ledger.redacted_event_rows == 1
        assert ledger.redacted_trace_rows == 1
    engine.dispose()

    # 5. downgrade 回到 0002：删除账本记录，但内容保持脱敏（不可逆）。
    run_alembic(db_path, "downgrade", "0002")

    engine = create_engine(f"sqlite:///{path}")
    with Session(engine) as session:
        ledgers = session.exec(select(AgentLogMigrationRecord)).all()
        assert len(ledgers) == 0  # 账本被删除
        # 内容仍处于脱敏状态（隐私脱敏不可逆）
        event = session.exec(select(AgentLearningEvent)).one()
        trace = session.exec(select(AgentTraceRecord)).one()
        assert "raw" not in event.event_data
        assert "raw" not in trace.trace_data
    engine.dispose()

    # 6. 再次 upgrade 0003：幂等——已脱敏行不再被处理，账本记录 (0, 0)。
    run_alembic(db_path, "upgrade", "0003")

    engine = create_engine(f"sqlite:///{path}")
    with Session(engine) as session:
        ledger = session.exec(select(AgentLogMigrationRecord)).one()
        assert ledger.redacted_event_rows == 0
        assert ledger.redacted_trace_rows == 0
        # 内容仍处于脱敏状态
        event = session.exec(select(AgentLearningEvent)).one()
        assert "raw" not in event.event_data
    engine.dispose()
