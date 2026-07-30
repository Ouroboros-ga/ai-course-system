"""Compatibility shim: question-bank port now lives in providers/research/question_bank."""

from __future__ import annotations

from ..providers.research.question_bank import (
    CallableQuestionBankPort,
    make_session_scoped_question_bank_port,
)
