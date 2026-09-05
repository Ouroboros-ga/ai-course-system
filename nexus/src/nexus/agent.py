"""Deep Agents 编排：Nexus 主智能体。"""
from __future__ import annotations

from typing import Any

from deepagents import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    create_deep_agent,
    register_harness_profile,
)
from deepagents.backends.state import StateBackend
from deepagents.middleware.filesystem import FilesystemMiddleware
from deepagents.middleware.summarization import SummarizationMiddleware
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver

from nexus.config import get_settings
from nexus.tools import NEXUS_TOOLS

# BASE 只放模式无关的身份与规则：不得带科研底色，模式身份由
# MODE_PROMPT_APPENDIX 按模式追加（General 通用助手 / Research 科研智能体）。
SYSTEM_PROMPT = """你是 CodeNexus 的 Nexus AI，服务对象是教师与学生。

你按当前模式工作：General 模式处理通用复杂任务，Research 模式处理
论文研究与复现；只使用当前模式下可用的工具，不宣称不具备的能力。

必须遵守的规则：
1. 诚实性：工具失败（如 WEB_SEARCH_UNAVAILABLE、
   KNOWLEDGE_RETRIEVAL_UNAVAILABLE）时如实告知用户失败原因，
   绝不编造检索结果。
2. 证据合流（M2）：search_course_materials（课程资料，经核实）与
   search_cs_knowledge（CS 知识库，权威来源）的可信度高于公开网络资料；
   但引用必须按相关性取舍——资料与问题无关时如实说明未找到相关课程资料
   或知识库条目，不得强行引用，也**不得**对不同来源做任何加权、打分或合成分。
3. 语言：默认使用中文回答；技术术语与代码保持原文。
   （原“复杂任务先建 todo”规则已按 M1-B5 暂不启用：Deep Agents 0.7 默认移除 TodoListMiddleware，但仍可通过显式 middleware 重新启用；待按任务复杂度产品化。）"""

# 工具面收敛（M0-B1 / 前端规格 D1）。deepagents 默认挂载全部文件工具、
# execute 与 task 子代理；这里收回到产品定义的 NEXUS_TOOLS + read_file：
# 1. FilesystemMiddleware(tools=["read_file"]) 同名替换默认全量实例——
#    write_file/edit_file/delete/glob/grep/execute 在 __init__ 即不创建；
#    read_file 必须保留：SummarizationMiddleware 将旧历史 offload 到
#    StateBackend（LangGraph state，非宿主文件系统），模型需读回压缩历史。
# 2. HarnessProfile.excluded_tools 注册在 provider 键 "openai"（覆盖任意
#    NEXUS_LLM_MODEL 更名）：模型请求侧过滤 + 工具调用侧拒绝，兜底上游
#    默认工具集变化。
# 3. 当前比赛版关闭 GeneralPurposeSubagentProfile，避免在文件沙箱、审批和子任务持久化未产品化前扩大权限面；后续按受限 Profile 重新评估。
# 锁定：tests/test_agent_tools.py 断言执行器注册表恰为 read_file + NEXUS_TOOLS。
NEXUS_EXCLUDED_TOOLS = frozenset(
    {"ls", "write_file", "edit_file", "delete", "glob", "grep", "execute", "task"}
)

# Research-only 工具（M1-B2 双 Profile）：General 模式结构性不绑定，
# 模型请求侧不可见（未传入 create_deep_agent 即不进 bind_tools）。
RESEARCH_ONLY_TOOLS = frozenset(
    {"search_arxiv_papers", "plan_reproduction", "run_reproduction"}
)

MODE_PROMPT_APPENDIX = {
    "general": """

你是通用助手（General 模式）：用网页检索、课程资料与 CS 知识库
回答通用问题、整理资料、生成文档。
论文检索、复现规划与执行属 Research 模式能力，本模式下不可用；
用户提出此类需求时，应建议切换到 Nexus Research。""",
    "research": """

你是科研智能体（Research 模式），服务对象是教师与学生。

你的职责：
- 论文调研：检索 arXiv 元数据与公开网页信息，梳理研究脉络、方法对比、相关工作；
- 复现规划：为论文生成快速复现（Quick Reproduction）计划，并提交专用 Repro Worker 执行；
- 复杂问题拆解：对开放性任务持续执行直到完成。

必须遵守的规则：
1. 诚实性：工具失败（如 ARXIV_UNAVAILABLE、REPRO_WORKER_UNAVAILABLE）
   时如实告知用户失败原因，绝不编造检索结果或复现结果。
2. 补充参考边界：web_search 与 search_arxiv_papers 的结果是"补充参考"，未经核实；
   表述时注明来源（搜索引擎/arXiv），不得宣称"已验证"或写成既定事实。
3. 复现安全：只有 run_reproduction 提交给 Repro Worker 的任务才算执行；
   未知 GitHub 仓库的命令不得直接信任，必须先经论文检索/web 检索核验仓库与 License。""",
}


def _register_tool_surface_profile() -> None:
    """注册工具面收敛 profile（幂等：重复注册为 merge 语义）。"""
    register_harness_profile(
        "openai",
        HarnessProfile(
            excluded_tools=NEXUS_EXCLUDED_TOOLS,
            general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
        ),
    )


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


def build_summarization_middleware(llm: Any) -> SummarizationMiddleware:
    """DeepAgents 原生 Compact：旧历史 offload 到 StateBackend（随 checkpoint 持久化）。

    触发阈值来自配置（默认 50000 tokens / 保留近期 20 条），对应 deepseek-chat
    64k 窗口约 78% 触发。摘要仍走同一 DeepSeek 模型（额外 token 成本）。
    """
    settings = get_settings()
    return SummarizationMiddleware(
        model=llm,
        backend=StateBackend(),
        trigger={"tokens": settings.summary_trigger_tokens},
        keep=("messages", settings.summary_keep_messages),
    )


def _tools_for_mode(mode: str) -> list[Any]:
    """M1-B2 模式工具白名单：General 结构性不绑定 research-only 三工具。"""
    if mode == "general":
        return [t for t in NEXUS_TOOLS if t.name not in RESEARCH_ONLY_TOOLS]
    return list(NEXUS_TOOLS)


def normalize_mode(mode: str | None) -> str:
    """请求 mode 白名单归一：仅 research 词形进 Research，其余一律 General。

    None/缺省/未知值默认 General（最小权限原则）：Research 是用户显式打开的
    能力提升，API 忘传字段不得自动多出 Paper 与 Reproduction 工具。
    """
    cleaned = (mode or "").strip().lower()
    return "research" if cleaned in {"research", "nexus_research"} else "general"


def build_agent(mode: str = "general", checkpointer: Any | None = None) -> Any:
    """构建 Nexus 主智能体。LLM 未配置时抛出 RuntimeError（调用方 fail-closed）。

    M1-B2：mode ∈ {general, research} 决定工具面与 prompt 附录。两个模式共享
    同一 checkpointer 与 thread 命名空间（main._config_for 不变），同 session
    切模式上下文连续。checkpointer 为空时用 InMemorySaver（本地/测试）；服务器
    lifespan 传入 AsyncPostgresSaver 实现重启可续聊。Compact 始终经原生
    middleware 启用；工具面经三层收敛（见 NEXUS_EXCLUDED_TOOLS 注释）。
    """
    mode = normalize_mode(mode)
    llm = build_llm()
    if llm is None:
        raise RuntimeError("LLM_NOT_CONFIGURED: NEXUS_DEEPSEEK_API_KEY is empty")
    _register_tool_surface_profile()
    saver = checkpointer if checkpointer is not None else InMemorySaver()
    return create_deep_agent(
        model=llm,
        tools=_tools_for_mode(mode),
        system_prompt=SYSTEM_PROMPT + MODE_PROMPT_APPENDIX[mode],
        middleware=[
            FilesystemMiddleware(tools=["read_file"]),
            build_summarization_middleware(llm),
        ],
        checkpointer=saver,
    )
