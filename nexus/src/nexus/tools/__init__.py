from nexus.tools.course_retrieval import search_course_materials, search_cs_knowledge
from nexus.tools.paper_search import search_arxiv_papers
from nexus.tools.reproduction import plan_reproduction, run_reproduction
from nexus.tools.web_search import web_search as web_search_tool

NEXUS_TOOLS = [
    web_search_tool,
    search_arxiv_papers,
    search_course_materials,
    search_cs_knowledge,
    plan_reproduction,
    run_reproduction,
]

__all__ = [
    "NEXUS_TOOLS",
    "web_search_tool",
    "search_arxiv_papers",
    "search_course_materials",
    "search_cs_knowledge",
    "plan_reproduction",
    "run_reproduction",
]
