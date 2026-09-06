from nexus.tools.artifact import write_artifact
from nexus.tools.attachments import read_attachment
from nexus.tools.course_retrieval import search_course_materials, search_cs_knowledge
from nexus.tools.paper_research import collect_paper_evidence, write_research_report
from nexus.tools.paper_search import search_arxiv_papers
from nexus.tools.reproduction import plan_reproduction, run_reproduction
from nexus.tools.web_search import web_search as web_search_tool

NEXUS_TOOLS = [
    web_search_tool,
    search_arxiv_papers,
    search_course_materials,
    search_cs_knowledge,
    write_artifact,
    plan_reproduction,
    run_reproduction,
    read_attachment,
    # NX-R1a：上传论文全文证据薄链（Research-only）。
    collect_paper_evidence,
    write_research_report,
]

__all__ = [
    "NEXUS_TOOLS",
    "web_search_tool",
    "search_arxiv_papers",
    "search_course_materials",
    "search_cs_knowledge",
    "write_artifact",
    "plan_reproduction",
    "run_reproduction",
    "read_attachment",
    "collect_paper_evidence",
    "write_research_report",
]
