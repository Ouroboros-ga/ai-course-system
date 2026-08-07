"""Research-domain providers: web research and question bank."""

from .question_bank import (
    CallableQuestionBankPort,
    make_session_scoped_question_bank_port,
)
from .question_generation import (
    CallableQuestionGenerationPort,
    make_session_scoped_question_generation_port,
)
from .web_research import (
    CallableWebResearchPort,
    make_session_scoped_web_research_port,
)

__all__ = [
    "CallableQuestionBankPort",
    "CallableQuestionGenerationPort",
    "CallableWebResearchPort",
    "make_session_scoped_question_bank_port",
    "make_session_scoped_question_generation_port",
    "make_session_scoped_web_research_port",
]
