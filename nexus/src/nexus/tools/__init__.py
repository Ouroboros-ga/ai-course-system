from nexus.tools.artifact import create_document_output, write_artifact
from nexus.tools.attachments import read_attachment
from nexus.tools.compare import (
    cancel_compare,
    get_compare,
    link_compare_run,
    plan_compare,
)
from nexus.tools.course_retrieval import search_course_materials, search_cs_knowledge
from nexus.tools.paper_research import collect_paper_evidence, read_paper_more, write_research_report
from nexus.tools.paper_search import search_arxiv_papers
from nexus.research_loop import (
    advance_research_task,
    cancel_research_task,
    complete_research_task,
    get_research_task,
    link_experiment_run,
    plan_research_task,
    submit_research_result,
)
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
from nexus.experiment_intake import prepare_experiment

NEXUS_TOOLS = [
    web_search_tool,
    search_arxiv_papers,
    search_course_materials,
    search_cs_knowledge,
    write_artifact,
    # F6：同一冻结快照的多格式正式输出（纯渲染，Ask 可用，不属于执行授权）。
    create_document_output,
    plan_reproduction,
    run_reproduction,
    read_attachment,
    # NX-R1a：上传论文全文证据薄链（Research-only）。
    collect_paper_evidence,
    read_paper_more,
    write_research_report,
    # NX-LB4/LB5：运行操作与提案工具（Research-only；取消需用户一次性授权）。
    get_reproduction_run,
    cancel_reproduction_run,
    add_reproduction_note,
    create_reproduction_proposal,
    update_reproduction_proposal,
    request_reproduction_approval,
    # T3：无 preset 入口（Research-only；只准备提案，不执行）。
    prepare_experiment,
    # F7：持续研究循环（Research-only；模型驱动、平台护栏）。
    plan_research_task,
    advance_research_task,
    submit_research_result,
    complete_research_task,
    link_experiment_run,
    cancel_research_task,
    get_research_task,
    # F8：受控对照（Research-only；只关联终态运行、不执行）。
    plan_compare,
    link_compare_run,
    get_compare,
    cancel_compare,
]

__all__ = [
    "NEXUS_TOOLS",
    "web_search_tool",
    "search_arxiv_papers",
    "search_course_materials",
    "search_cs_knowledge",
    "write_artifact",
    "create_document_output",
    "plan_reproduction",
    "run_reproduction",
    "read_attachment",
    "collect_paper_evidence",
    "read_paper_more",
    "write_research_report",
    "get_reproduction_run",
    "cancel_reproduction_run",
    "add_reproduction_note",
    "create_reproduction_proposal",
    "update_reproduction_proposal",
    "request_reproduction_approval",
    "prepare_experiment",
    "plan_research_task",
    "advance_research_task",
    "submit_research_result",
    "complete_research_task",
    "link_experiment_run",
    "cancel_research_task",
    "get_research_task",
    "plan_compare",
    "link_compare_run",
    "get_compare",
    "cancel_compare",
]
