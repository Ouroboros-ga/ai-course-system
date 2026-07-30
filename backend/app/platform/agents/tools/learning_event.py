"""Compatibility shim: learning-event port now lives in providers/teaching/learning_event."""

from __future__ import annotations

from ..providers.teaching.learning_event import (
    CallableLearningEventPort,
    make_session_scoped_learning_event_port,
)
