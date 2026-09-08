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
from langchain.agents.middleware import TodoListMiddleware
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
4. 计划（NX-H1）：TodoListMiddleware 提供 write_todos——只对真正多步骤
   （≥3 步）的任务建计划并随执行更新；寒暄/单步问答不建计划。
   计划状态（todos）是模型的计划标记，不等于工具成功或实验 PASS 证据。"""

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

# T2 Ask/Auto：触发实验代码沙箱的工具（Ask 不绑定；Auto 经批准后可用）。
# Ask 仍保留准备类工具（提案创建/修改/请求审批——“帮我运行”继续做准备工作
# 并给出切换入口）与只读/取消类工具（查运行、读日志、下载报告、用户取消）。
EXPERIMENT_EXECUTION_TOOLS = frozenset({"run_reproduction"})

# Research-only 工具（M1-B2 双 Profile）：General 模式结构性不绑定，
# 模型请求侧不可见（未传入 create_deep_agent 即不进 bind_tools）。
RESEARCH_ONLY_TOOLS = frozenset(
    {
        "search_arxiv_papers",
        "plan_reproduction",
        "run_reproduction",
        # NX-R1a：上传论文全文证据薄链（Research-only）。
        "collect_paper_evidence",
        "write_research_report",
        # NX-LB4/LB5：运行操作与提案工具（取消需用户一次性授权）。
        "get_reproduction_run",
        "cancel_reproduction_run",
        "add_reproduction_note",
        "create_reproduction_proposal",
        "update_reproduction_proposal",
        "request_reproduction_approval",
    }
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
- 全文证据研究（NX-R1a）：对用户上传的论文 PDF，用 collect_paper_evidence
  读取全文块建立证据（每条证据带 evidence_id 与原文 locator），再用
  write_research_report 写成带可核对引用的研究报告 Artifact；
- 复现规划：为论文生成快速复现（Quick Reproduction）计划，并提交专用 Repro Worker 执行；
- 复杂问题拆解：对开放性任务持续执行直到完成。

计划要求（NX-H1）：多步骤研究任务（检索、读证据、比较、写报告等 ≥3 步）
必须先用 write_todos 建计划，并在读完证据、完成综合等关键节点后更新计划
状态；计划完成的条目必须与真实完成的事实一致，不得提前勾选。

必须遵守的规则：
1. 诚实性：工具失败（如 ARXIV_UNAVAILABLE、REPRO_WORKER_UNAVAILABLE、
   EVIDENCE_UNAVAILABLE）时如实告知用户失败原因，绝不编造检索结果或复现结果。
2. 补充参考边界：web_search 与 search_arxiv_papers 的结果是"补充参考"，未经核实；
   表述时注明来源（搜索引擎/arXiv），不得宣称"已验证"或写成既定事实。
   搜索候选（元数据）与已读全文证据（evidence_id）严格区分：只有摘要的
   候选必须标注 abstract_only，不得冒充读过全文；全文不可得时提示用户上传。
3. 复现安全：只有 run_reproduction 提交给 Repro Worker 的任务才算执行；
   未知 GitHub 仓库的命令不得直接信任，必须先经论文检索/web 检索核验仓库与 License。
4. 运行操作（NX-LB4）：用 get_reproduction_run 查询用户明确提到的运行；
   cancel_reproduction_run 是破坏性操作——工具返回 confirmation_required 时
   必须先向用户说明并等待其界面确认，绝不能自行重试取消或替用户决定；
   提案修改（create/update_reproduction_proposal、request_reproduction_approval）
   只准备执行材料并把 proposal/approval 引用展示给用户，批准永远由用户发起。
5. 引用纪律：研究报告中只能引用 collect_paper_evidence 返回的 evidence_id
   （write_research_report 服务端渲染引用，模型不得编造页码或引文）；
   引用被拒时按返回的修复指引最多修正一次，仍失败则如实输出证据缺口。""",
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


def build_llm(model_name: str | None = None) -> ChatOpenAI | None:
    """按指定模型 id 构建 LLM（None → 配置默认模型）。

    调用方必须先经 normalize_model_name 校验：本函数不做 allowlist 检查，
    只负责实例化（测试桩替换点保持不变）。
    """
    from nexus.config import llm_default_model

    settings = get_settings()
    if not settings.deepseek_api_key:
        return None
    return ChatOpenAI(
        model=model_name or llm_default_model(settings),
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


def _tools_for_mode(mode: str, execution_mode: str | None = None) -> list[Any]:
    """M1-B2 模式工具白名单：General 结构性不绑定 research-only 工具。

    T2 Ask/Auto：Research+Ask 额外不绑定实验执行工具（run_reproduction）——
    Ask 下模型请求侧不可见，纵深防御执行核（服务端核销）仍独立校验。
    execution_mode 缺省按 Ask 收敛（安全默认）；General 传 auto 也不放行。
    """
    if mode == "general":
        return [t for t in NEXUS_TOOLS if t.name not in RESEARCH_ONLY_TOOLS]
    tools = list(NEXUS_TOOLS)
    if (execution_mode or "ask").strip().lower() != "auto":
        tools = [t for t in tools if t.name not in EXPERIMENT_EXECUTION_TOOLS]
    return tools


class InvalidNexusModel(ValueError):
    """未知模型 id：调用方必须转 HTTP 400 INVALID_NEXUS_MODEL。

    模型 id 大小写敏感（即 API 侧的真实 id，原样比对，不做归一化），
    防止"近似命中"把请求送到错误的计费模型。
    """

    def __init__(self, raw: Any) -> None:
        super().__init__(f"INVALID_NEXUS_MODEL:{raw!r}")
        self.raw = raw


def normalize_model_name(raw: str | None, available: list[str], default: str) -> str:
    """模型选择归一（模型网关 P0）：None 缺字段→默认模型；清单命中→原样；
    其他（含空串/空白/未知 id/非 str）→ InvalidNexusModel。"""
    if raw is None:
        return default
    if not isinstance(raw, str):
        raise InvalidNexusModel(raw)
    cleaned = raw.strip()
    if not cleaned:
        raise InvalidNexusModel(raw)
    if cleaned in available:
        return cleaned
    raise InvalidNexusModel(raw)


class InvalidNexusMode(ValueError):
    """未知 mode 词形：调用方必须转 HTTP 400 INVALID_NEXUS_MODE。

    v1.3 A1 冻结语义：缺字段/None → general（安全默认）；已知别名
    trim/lowercase 后匹配；其他字符串（含空串/纯空白）一律拒绝，不再
    静默回落——回落会把调用方拼写错误伪装成"正常 General 回答"。
    """

    def __init__(self, raw: Any) -> None:
        super().__init__(f"INVALID_NEXUS_MODE:{raw!r}")
        self.raw = raw


_GENERAL_ALIASES = frozenset({"general", "nexus_general"})
_RESEARCH_ALIASES = frozenset({"research", "nexus_research"})


def normalize_mode(mode: str | None) -> str:
    """请求 mode 严格归一（v1.3 A1，NX-G1）。

    - None（字段缺失）→ "general"；
    - 已知别名（去空白/小写后）→ 对应模式；
    - 其他（含 ""/空白/未知词）→ InvalidNexusMode；
    - 非 str 类型 → InvalidNexusMode（HTTP 层的 pydantic 会先以 422 拒绝，
      本分支是纵深防御，防内部调用方绕过 schema）。
    """
    if mode is None:
        return "general"
    if not isinstance(mode, str):
        raise InvalidNexusMode(mode)
    cleaned = mode.strip().lower()
    if cleaned in _GENERAL_ALIASES:
        return "general"
    if cleaned in _RESEARCH_ALIASES:
        return "research"
    raise InvalidNexusMode(mode)


def build_agent(
    mode: str = "general",
    checkpointer: Any | None = None,
    model: str | None = None,
    execution_mode: str | None = None,
) -> Any:
    """构建 Nexus 主智能体。LLM 未配置时抛出 RuntimeError（调用方 fail-closed）。

    M1-B2：mode ∈ {general, research} 决定工具面与 prompt 附录。两个模式共享
    同一 checkpointer 与 thread 命名空间（main._config_for 不变），同 session
    切模式上下文连续。checkpointer 为空时用 InMemorySaver（本地/测试）；服务器
    lifespan 传入 AsyncPostgresSaver 实现重启可续聊。Compact 始终经原生
    middleware 启用；工具面经三层收敛（见 NEXUS_EXCLUDED_TOOLS 注释）。

    T2 Ask/Auto：Research 工具面再按 execution_mode 拆分（Ask 不绑定
    run_reproduction；缺省 Ask，安全默认）。调用方（main 聊天入口）须传
    本次 effective 值；实例缓存键须区分 Ask/Auto（见 main.get_agent）。

    模型网关 P0：model 为服务端 allowlist 内的模型 id（调用方 main._require_model
    已校验）；同 (mode, model) 复用实例，不同模型各持独立 LLM。切模型不断会话
    上下文（同一 thread），只换后续生成的模型。
    """
    mode = normalize_mode(mode)
    llm = build_llm(model)
    if llm is None:
        raise RuntimeError("LLM_NOT_CONFIGURED: NEXUS_DEEPSEEK_API_KEY is empty")
    _register_tool_surface_profile()
    saver = checkpointer if checkpointer is not None else InMemorySaver()
    return create_deep_agent(
        model=llm,
        tools=_tools_for_mode(mode, execution_mode),
        system_prompt=SYSTEM_PROMPT + MODE_PROMPT_APPENDIX[mode],
        middleware=[
            FilesystemMiddleware(tools=["read_file"]),
            build_summarization_middleware(llm),
            # NX-H1：显式启用已安装的 TodoListMiddleware（langchain.agents
            # .middleware.todo）——write_todos 工具 + todos state，两模式同置，
            # 使用频率由提示词约束（简单 General 不强制建计划），不另设分类器。
            TodoListMiddleware(),
        ],
        checkpointer=saver,
    )
