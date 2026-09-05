"""Research-domain providers（TeachingAgent 活链保留）。

S3 修正（按代码核定，见 P2 计划 §14.9）：原 ``paper_search``（nexus 已有
独立降级链实现）、``workspace``、``access`` 随 ResearchAgent 工作台下线删除；
``question_bank``/``question_generation``/``web_research`` 为 TeachingAgent
出题与 web 检索链的活依赖，**保留**。
"""

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
