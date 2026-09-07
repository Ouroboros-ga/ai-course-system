from nexus.tools.artifact import write_artifact
from nexus.tools.attachments import read_attachment
from nexus.tools.course_retrieval import search_course_materials, search_cs_knowledge
from nexus.tools.paper_research import collect_paper_evidence, write_research_report
from nexus.tools.paper_search import search_arxiv_papers
from nexus.tools.reproduction import (
    add_reproduction_note,
    cancel_reproduction_run,
    create_reproduction_proposal,
    get_reproduction_run,
    plan_reproduction,
    request_reproduction_approval,
    run_reproduction,
    update_reproduction_proposal,
)
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
    # NX-LB4/LB5：运行操作与提案工具（Research-only；取消需用户一次性授权）。
    get_reproduction_run,
    cancel_reproduction_run,
    add_reproduction_note,
    create_reproduction_proposal,
    update_reproduction_proposal,
    request_reproduction_approval,
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
    "get_reproduction_run",
    "cancel_reproduction_run",
    "add_reproduction_note",
    "create_reproduction_proposal",
    "update_reproduction_proposal",
    "request_reproduction_approval",
]
