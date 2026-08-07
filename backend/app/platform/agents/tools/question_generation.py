"""Compatibility shim: question-generation port now lives in providers/research/question_generation."""

from __future__ import annotations

from ..providers.research.question_generation import (
    CallableQuestionGenerationPort,
    make_session_scoped_question_generation_port,
)
