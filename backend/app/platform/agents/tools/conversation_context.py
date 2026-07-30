"""Compatibility shim: conversation-context port now lives in providers/teaching/conversation_context."""

from __future__ import annotations

from ..providers.teaching.conversation_context import (
    CONTEXT_POLICY_VERSION,
    SESSION_TTL_MINUTES,
    SessionScopedConversationContextPort,
    make_session_scoped_conversation_context_port,
    normalize_context,
)
