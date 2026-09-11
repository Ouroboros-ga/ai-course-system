"""OJ 智能诊断子域（`intelligence`）。

承载「运行结果 → 学生可读诊断」的判定规则：错误分类、调试步骤、
分层提示、行号抽取、置信度。

设计约束（ADR-0001 决定 9）：

- 诊断 / 提示 / 解析是**核心 OJ 子域**，不是 P2 附加功能。
- 本包**只放纯规则**，不依赖 `app.models` / `app.services`、不接收 session。
  持久化与 ORM 适配留在 `services/coding_eduagent_service.py`。
- 分层提示的审计字段（`hint_level` / `reason_codes` / `policy_version`）
  必须保留，`full_solution` 默认禁止。

这与 `domain/learning`、`domain/safety`、`domain/student_memory` 等既有模块
的边界一致：域层定义「规则是什么」，服务层决定「何时读写数据库」。
"""

from app.domain.oj.intelligence.rules import (
    DIAGNOSIS_ERROR_CLASSES,
    DIAGNOSIS_POLICY_VERSION,
    DiagnosisInput,
    classify_run,
    confidence_for,
    debug_steps_for,
    hints_for,
    line_from_text,
    normalize_outcome,
)

__all__ = [
    "DIAGNOSIS_ERROR_CLASSES",
    "DIAGNOSIS_POLICY_VERSION",
    "DiagnosisInput",
    "classify_run",
    "confidence_for",
    "debug_steps_for",
    "hints_for",
    "line_from_text",
    "normalize_outcome",
]
