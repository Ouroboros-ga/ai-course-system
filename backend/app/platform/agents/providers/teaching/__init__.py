"""Teaching-domain providers: learning events, conversation context, LLM."""

from .conversation_context import (
    CONTEXT_POLICY_VERSION,
    SESSION_TTL_MINUTES,
    SessionScopedConversationContextPort,
    make_session_scoped_conversation_context_port,
    normalize_context,
)
from .learning_event import (
    CallableLearningEventPort,
    make_session_scoped_learning_event_port,
)
from .llm import OpenAICompatibleTeachingLLM
from .conversation_history import (
    SessionScopedConversationHistoryPort,
    make_session_scoped_conversation_history_port,
    select_bounded_turns,
)
from .learning_adjustment import (
    SessionScopedLearningAdjustmentPort,
    make_session_scoped_learning_adjustment_port,
)

__all__ = [
    "CONTEXT_POLICY_VERSION",
    "OpenAICompatibleTeachingLLM",
    "SESSION_TTL_MINUTES",
    "SessionScopedConversationContextPort",
    "CallableLearningEventPort",
    "make_session_scoped_conversation_context_port",
    "make_session_scoped_learning_event_port",
    "normalize_context",
    "SessionScopedConversationHistoryPort",
    "make_session_scoped_conversation_history_port",
    "select_bounded_turns",
    "SessionScopedLearningAdjustmentPort",
    "make_session_scoped_learning_adjustment_port",
]
