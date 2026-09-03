"""Deep Agents 编排：Nexus 主智能体。"""
from __future__ import annotations

from typing import Any

from deepagents import create_deep_agent
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver

from nexus.config import get_settings
from nexus.tools import NEXUS_TOOLS

SYSTEM_PROMPT = """你是 Nexus，CodeNexus 平台的科研智能体，服务对象是教师与学生。

你的职责：
- 论文调研：检索 arXiv 元数据与公开网页信息，梳理研究脉络、方法对比、相关工作；
- 复现规划：为论文生成快速复现（Quick Reproduction）计划，并提交专用 Repro Worker 执行；
- 复杂问题拆解：对开放性任务先用任务清单（todo）拆解，逐步推进，持续执行直到完成。

必须遵守的规则：
1. 诚实性：工具失败（如 WEB_SEARCH_UNAVAILABLE、ARXIV_UNAVAILABLE、
   REPRO_WORKER_UNAVAILABLE）时如实告知用户失败原因，绝不编造检索结果或复现结果。
2. 补充参考边界：web_search 与 search_arxiv_papers 的结果是"补充参考"，未经核实；
   表述时注明来源（搜索引擎/arXiv），不得宣称"已验证"或写成既定事实。
3. 复现安全：只有 run_reproduction 提交给 Repro Worker 的任务才算执行；
   未知 GitHub 仓库的命令不得直接信任，必须先经论文检索/web 检索核验仓库与 License。
4. 复杂任务先拆解：多步骤任务先建立 todo，逐步执行并勾选进度。
5. 语言：默认使用中文回答；技术术语与代码保持原文。"""


def build_llm() -> ChatOpenAI | None:
    settings = get_settings()
    if not settings.deepseek_api_key:
        return None
    return ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.deepseek_api_key,
        base_url=settings.llm_base_url,
        temperature=0.2,
        streaming=True,
    )


def build_agent() -> Any:
    """构建 Nexus 主智能体。LLM 未配置时抛出 RuntimeError（调用方 fail-closed）。"""
    llm = build_llm()
    if llm is None:
        raise RuntimeError("LLM_NOT_CONFIGURED: NEXUS_DEEPSEEK_API_KEY is empty")
    return create_deep_agent(
        model=llm,
        tools=NEXUS_TOOLS,
        system_prompt=SYSTEM_PROMPT,
        checkpointer=InMemorySaver(),
    )
