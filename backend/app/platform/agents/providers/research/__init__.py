"""Research-domain providers: web research and question bank."""

from .question_bank import (
    CallableQuestionBankPort,
    make_session_scoped_question_bank_port,
)
from .web_research import (
    CallableWebResearchPort,
    make_session_scoped_web_research_port,
)

__all__ = [
    "CallableQuestionBankPort",
    "CallableWebResearchPort",
    "make_session_scoped_question_bank_port",
    "make_session_scoped_web_research_port",
]
