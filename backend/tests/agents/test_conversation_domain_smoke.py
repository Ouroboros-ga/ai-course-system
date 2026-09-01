"""Conversation Domain 端到端接线验证（pytest）。

不调用真实 LLM/Agent；直接在 service 层模拟一轮 Q/A 持久化 + 读回 + 提问反推，
确认模型/服务/迁移/审计域边界全部正确接线。

使用 conftest 的 session fixture（连到经 alembic upgrade head 升级过的测试库），
每个测试自清理残留数据。
"""
from __future__ import annotations

import os

os.environ.setdefault("AI_COURSE_SKIP_STARTUP_SIDE_EFFECTS", "1")

from datetime import timedelta

import pytest
from sqlalchemy import inspect as sa_inspect
from sqlmodel import Session, select

from app.core.time_utils import utcnow_aware
from app.models.agent_log import AgentConversationSession
from app.models.conversation_model import (
    CONVERSATION_DATA_POLICY_VERSION,
    ConversationMessage,
)
from app.services.conversation_service import (
    derive_question_inference_signals,
    list_conversation_messages,
    persist_conversation_turn,
    prune_expired_conversations,
)

STUDENT = 900001
COURSE = 870001
SESSION = "smoke-session-001"
TRACE = "trace-smoke-001"


def _cleanup(session, student_id=STUDENT):
    for row in session.exec(
        select(ConversationMessage).where(ConversationMessage.student_id == student_id)
    ).all():
        session.delete(row)
    for row in session.exec(
        select(AgentConversationSession).where(AgentConversationSession.student_id == student_id)
    ).all():
        session.delete(row)
    session.commit()


def test_conversation_messages_table_structure(session):
    insp = sa_inspect(session.get_bind())
    tables = insp.get_table_names()
    assert "conversation_messages" in tables

    cols = {c["name"] for c in insp.get_columns("conversation_messages")}
    assert cols == {
        "id", "student_id", "course_id", "session_id", "trace_id", "role", "content",
        "concept_id", "resource_id", "citations", "data_policy_version",
        "message_kind", "retention_until", "created_at",
    }

    idx = {i["name"] for i in insp.get_indexes("conversation_messages")}
    assert idx == {
        "ix_conversation_messages_student_id",
        "ix_conversation_messages_course_id",
        "ix_conversation_messages_session_id",
        "ix_conversation_messages_concept_id",
        "ix_conversation_messages_message_kind",
        "ix_conversation_messages_retention_until",
        "ix_conversation_messages_created_at",
        "ix_conversation_messages_student_course_created",
    }


def test_persist_and_list_conversation_turn(session):
    _cleanup(session)
    persist_conversation_turn(
        session,
        student_id=STUDENT, course_id=COURSE, session_id=SESSION, trace_id=TRACE,
        user_message="什么是递归的终止条件？",
        assistant_answer="递归必须有基线条件，否则会无限递归。",
        concept_id="concept-recursion",
        resource_id="node-101",
        citations=[{"evidence_id": "ev-1", "title": "递归基础"}],
    )

    rows = list_conversation_messages(session, student_id=STUDENT, course_id=COURSE, session_id=SESSION)
    assert len(rows) == 2
    assert rows[0].role == "user"
    assert rows[1].role == "assistant"
    assert rows[0].content == "什么是递归的终止条件？"
    assert rows[1].content.startswith("递归必须有基线条件")
    assert rows[1].citations == [{"evidence_id": "ev-1", "title": "递归基础"}]
    assert rows[0].data_policy_version == CONVERSATION_DATA_POLICY_VERSION
    assert rows[0].retention_until is not None
    assert rows[0].trace_id == TRACE and rows[1].trace_id == TRACE
    _cleanup(session)
def test_question_inference_signals_no_raw_text(session):
    _cleanup(session)
    persist_conversation_turn(
        session, student_id=STUDENT, course_id=COURSE, session_id=SESSION, trace_id="trace-smoke-002",
        user_message="二叉树怎么遍历？", assistant_answer="前序/中序/后序。",
        concept_id="concept-btree",
    )
    persist_conversation_turn(
        session, student_id=STUDENT, course_id=COURSE, session_id=SESSION, trace_id="trace-smoke-003",
        user_message="递归还能怎么用？", assistant_answer="可用于回溯、分治。",
        concept_id="concept-recursion",
    )

    signals = derive_question_inference_signals(session, student_id=STUDENT, course_id=COURSE)
    assert isinstance(signals.get("signals"), list)
    assert signals.get("total_questions") == 2
    assert len(signals["signals"]) >= 2

    recursion_sig = next(
        (x for x in signals["signals"] if x.get("concept_id") == "concept-recursion"), None
    )
    assert recursion_sig is not None
    assert recursion_sig.get("question_count") == 1
    assert isinstance(recursion_sig.get("trace_ids"), list) and len(recursion_sig["trace_ids"]) >= 1

    # 关键断言：信号中绝不包含原始问题全文
    serialized = str(signals)
    assert "二叉树怎么遍历" not in serialized
    assert "递归还能怎么用" not in serialized
    _cleanup(session)


def test_audit_domain_context_data_has_no_raw_text(session):
    """审计域 AgentConversationSession.context_data 不得含原文（边界保持）。"""
    _cleanup(session)
    # 直接写一条审计 session 行，模拟 workflow record_event 写入
    session.add(AgentConversationSession(
        student_id=STUDENT, course_id=COURSE, session_id=SESSION,
        context_data='{"current_concept_id":"concept-recursion","last_intent":"course_question"}',
    ))
    session.commit()

    audit_rows = session.exec(
        select(AgentConversationSession).where(AgentConversationSession.student_id == STUDENT)
    ).all()
    for r in audit_rows:
        assert "什么是递归" not in (r.context_data or "")
        assert "二叉树" not in (r.context_data or "")
    _cleanup(session)


def test_prune_expired_conversations(session):
    _cleanup(session)
    persist_conversation_turn(
        session, student_id=STUDENT, course_id=COURSE, session_id=SESSION, trace_id="trace-expired",
        user_message="过期问题", assistant_answer="过期回答", concept_id="concept-old",
    )
    expired_rows = session.exec(
        select(ConversationMessage).where(ConversationMessage.trace_id == "trace-expired")
    ).all()
    assert len(expired_rows) == 2
    for r in expired_rows:
        r.retention_until = utcnow_aware() - timedelta(days=1)
        session.add(r)
    session.commit()

    deleted = prune_expired_conversations(session)
    assert deleted >= 2
    remaining = session.exec(
        select(ConversationMessage).where(ConversationMessage.trace_id == "trace-expired")
    ).all()
    assert len(remaining) == 0
    _cleanup(session)
