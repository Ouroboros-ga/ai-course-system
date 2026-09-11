"""OJ 智能诊断：判定规则与诊断文案的**纯领域逻辑**。

本模块是 `domain/oj/intelligence/` 的规则核心，**不依赖 `app.models` /
`app.services`，不接收 session，不碰数据库**——与 `domain/` 下
`learning` / `safety` / `student_memory` 等模块的既有惯例一致。

职责边界（重要）：

- **本模块**：给定一次运行的终态与错误文本，判断错误类别、给出面向学生的
  摘要与调试步骤、给出机器可读的 reason code。**纯函数，无副作用。**
- **`services/coding_eduagent_service.py`**：负责查库、做 ORM ↔ 域输入的适配、
  持久化 `CodingDiagnosisRecord`。

这个切分的意义：判定规则可脱离数据库单独测试（本模块已由
`tests/test_oj_intelligence_characterization.py` 覆盖），且未来若诊断规则
要进 LLM 复核、或要在前端做预览，可以直接复用而不必起一个 session。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "DIAGNOSIS_ERROR_CLASSES",
    "DIAGNOSIS_POLICY_VERSION",
    "DiagnosisInput",
    "classify_run",
    "debug_steps_for",
    "hints_for",
    "line_from_text",
]


#: 诊断规则版本。变更判定分支或文案时递增，便于审计历史诊断记录。
DIAGNOSIS_POLICY_VERSION = "coding-diagnosis/rule-v1"


#: 全部错误类别（含兜底 `unknown`）。
DIAGNOSIS_ERROR_CLASSES = frozenset(
    {"syntax", "compile", "runtime", "logic", "complexity", "environment", "none", "unknown"}
)


#: 从错误文本里抽取行号：支持 `line 42` / `Line: 7` / `line=13` / `行 99` / `行:5`。
_LINE_RE = re.compile(r"(?:line|行)\s*[:=]?\s*(\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class DiagnosisInput:
    """一次运行的诊断输入——**与 ORM 解耦的归一化结构**。

    由 `CodingEduAgent` 从 `ExperimentRun` + `ExperimentRunArtifact` 装配。
    字段刻意保持「平淡」（str / list[str]），使域层不必知道 SQLModel 的存在。
    """

    outcome: str = "unknown"
    error_code: str = ""
    error_message: str = ""
    compile_message: str = ""
    runtime_message: str = ""
    artifacts: tuple[str, ...] = field(default_factory=tuple)
    """已筛过的 artifact 正文（调用方只传 `stderr` / `compile` 两类）。"""

    def evidence_text(self) -> str:
        """拼接全部判定依据文本为小写串——`classify_run` 的唯一文本来源。"""
        return " ".join(
            [
                self.error_code or "",
                self.error_message or "",
                self.compile_message or "",
                self.runtime_message or "",
                *self.artifacts,
            ]
        ).lower()


def normalize_outcome(value: Any) -> str:
    """枚举 / 字符串 / None 一律归一为小写字符串；空值归 `unknown`。"""
    raw = getattr(value, "value", value)
    return str(raw or "unknown")


def classify_run(data: DiagnosisInput) -> tuple[str, str, list[str]]:
    """判定错误类别。

    返回 `(error_class, summary, reason_codes)` 三元组。

    判定顺序**有优先级**：编译错误先于运行时错误，因为编译器报错时
    运行时文本通常是空的或误导性的。改动顺序会改变诊断结果。
    """
    outcome = normalize_outcome(data.outcome)
    text = data.evidence_text()

    if outcome == "compilation_error":
        if any(token in text for token in ("syntax", "indent", "parse", "语法", "缩进")):
            return "syntax", "编译阶段发现语法或缩进问题。", ["COMPILE_ERROR", "SYNTAX_LIKE"]
        return "compile", "代码未能通过编译或解释器检查。", ["COMPILE_ERROR"]

    if outcome == "runtime_error":
        if any(token in text for token in ("indexerror", "out of range", "越界")):
            return "runtime", "运行时访问了不存在的索引或元素。", ["RUNTIME_ERROR", "INDEX_LIKE"]
        if any(token in text for token in ("zerodivision", "division by zero", "除零")):
            return "runtime", "运行时发生除零错误。", ["RUNTIME_ERROR", "DIVISION_BY_ZERO"]
        return "runtime", "程序运行过程中抛出了错误。", ["RUNTIME_ERROR"]

    if outcome == "wrong_answer":
        return "logic", "程序可以运行，但输出与测试预期不一致。", ["WRONG_ANSWER", "CHECK_LOGIC"]

    if outcome == "time_limit_exceeded":
        return "complexity", "程序超过了本题的时间限制。", ["TIME_LIMIT", "CHECK_COMPLEXITY"]

    if outcome == "memory_limit_exceeded":
        return "complexity", "程序超过了本题的内存限制。", ["MEMORY_LIMIT", "CHECK_SPACE"]

    if outcome == "accepted":
        return "none", "本次运行通过了可见的评分检查。", ["ACCEPTED"]

    if outcome == "sandbox_unavailable":
        return "environment", "代码沙箱暂不可用，本次没有形成有效执行证据。", ["SANDBOX_UNAVAILABLE"]

    return "unknown", "当前运行结果不足以形成可靠的代码诊断。", ["INSUFFICIENT_EXECUTION_EVIDENCE"]


#: 每个错误类别的调试步骤。
#: 注意 `none`（通过）**只有 2 条**——通过时不需要修错指引，这是有意的不对称，
#: 不要为了「整齐」补齐成 3 条。已由 characterization 测试钉住。
_DEBUG_STEPS: dict[str, list[str]] = {
    "syntax": ["先查看编译器指出的行附近代码", "检查括号、缩进、关键字和语句结束符", "修复一个最小问题后重新运行"],
    "compile": ["确认语言版本和入口函数符合题目要求", "阅读第一条编译错误而不是后续连锁错误", "用最小代码片段重新提交"],
    "runtime": ["用最小输入复现错误", "检查边界条件和变量初始化", "逐步打印关键中间状态后重新运行"],
    "logic": ["找一个最小反例", "手工对照题目要求执行关键分支", "检查循环边界、状态更新和返回值"],
    "complexity": ["估算主要循环或递归的时间复杂度", "检查是否重复计算相同子问题", "再评估额外数据结构带来的空间开销"],
    "environment": ["稍后重试沙箱执行", "不要把未执行的结果当成通过或失败", "确认课程沙箱状态后再提交"],
    "none": ["可以查看隐藏边界条件并尝试解释每一步", "如需提升难度，请请求下一道课程练习"],
}

_UNKNOWN_DEBUG_STEPS = ["等待一次有效执行结果后再诊断", "不要根据猜测修改多个地方", "保留最小复现样例"]


def debug_steps_for(error_class: str) -> list[str]:
    """取该错误类别的调试步骤；未知类别走兜底。**总是返回新 list。**"""
    return list(_DEBUG_STEPS.get(error_class, _UNKNOWN_DEBUG_STEPS))


def hints_for(error_class: str) -> list[dict[str, Any]]:
    """由调试步骤前两条派生的概念级提示（**永不含完整解答**）。

    `full_solution` 恒为 `False`——分层提示的「禁止直接给答案」约束落在域层，
    不依赖调用方自觉。
    """
    return [
        {"level": "concept", "text": step, "full_solution": False}
        for step in debug_steps_for(error_class)[:2]
    ]


def line_from_text(*texts: str) -> int | None:
    """从若干段错误文本里抽取**第一个**出现的行号；没有则 `None`。"""
    match = _LINE_RE.search(" ".join(t or "" for t in texts))
    return int(match.group(1)) if match else None


def confidence_for(outcome: str) -> float:
    """判定置信度：能明确归类的终态给 0.95，其余（含 sandbox 不可用）给 0.35。

    低置信度不是「不确定」而是「不足以形成有效执行证据」，
    调用方据此把 `status` 落为 `insufficient_evidence`。
    """
    confident = {
        "accepted", "compilation_error", "runtime_error",
        "wrong_answer", "time_limit_exceeded", "memory_limit_exceeded",
    }
    return 0.95 if normalize_outcome(outcome) in confident else 0.35
