"""Research-domain providers: scholarly search, web research and question bank."""

from .access import CourseAccessResearchScopePort
from .paper_search import ArxivPaperSearchProvider

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
    "ArxivPaperSearchProvider",
    "CourseAccessResearchScopePort",
    "make_session_scoped_question_bank_port",
    "make_session_scoped_question_generation_port",
    "make_session_scoped_web_research_port",
]
