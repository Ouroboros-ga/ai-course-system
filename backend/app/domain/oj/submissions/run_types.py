"""Run 的类型语义。

背景
----
现有 ``ExperimentRun`` 只有一种语义：学生提交代码、系统判题。
但产品上至少需要区分三种运行：

- ``SUBMISSION`` —— **正式提交**：计入活动、计入排名、产生学习证据；
- ``TEST`` —— 学生在编辑器里点「运行」自测：用自定义 stdin 或公开样例，
  **不计分、不进排名、不更新掌握度、可随时丢弃**；
- ``REFERENCE_PREVIEW`` —— 教师上传参考解、系统跑全测试集验证题面完整性
  （对应现有 ``POST /versions/{version_id}/reference-preview``，
  校验时间落在 ``ExperimentVersion.reference_preview_verified_at``，
  **参考解源码不持久化**）。

用一个 ``run_type`` 字段表达三者，**而不是新增 ``oj_submission`` 表**——
避免第二套事实源（见 ADR-0001 决定 1）。

现状说明
--------
仓库已经具备「自定义输入」能力：``SandboxClient.submit_code(..., stdin="")``
（``services/sandbox_client.py``）与 ``POST /api/v1/sandbox/course/{id}/execute``
的 ``stdin`` 字段。缺的只是把它接进题目上下文并标上类型，
因此本模块不引入新的执行通道。

兼容
----
正式提交此前由 ``ExperimentRun.idempotency_key`` 非空隐含表达
（列注释：学生正式提交的请求幂等键）。``run_type`` 是**显式化**，
两者在过渡期需保持一致：``run_type == SUBMISSION`` ⇔ ``idempotency_key`` 非空。
见 ``tests/test_oj_run_semantics.py`` 的一致性断言。
"""

from __future__ import annotations

from enum import Enum
from typing import Any

__all__ = [
    "DEFAULT_RUN_TYPE",
    "SCORED_RUN_TYPES",
    "RunType",
    "is_scored_run_type",
    "normalize_run_type",
]


class RunType(str, Enum):
    """一次 run 的产品语义。"""

    SUBMISSION = "submission"
    TEST = "test"
    REFERENCE_PREVIEW = "reference_preview"


#: 列默认值。用常量而非字面量，避免迁移、模型与领域层三处各写一遍。
DEFAULT_RUN_TYPE: str = RunType.SUBMISSION.value

#: 参与计分 / 排名 / 学习证据的 run 类型。
#: 排名与掌握度只看这些类型——**TEST 跑多少次都不影响成绩**。
SCORED_RUN_TYPES: frozenset[RunType] = frozenset({RunType.SUBMISSION})


def normalize_run_type(value: Any) -> RunType | None:
    """把 str / Enum / None 归一化为 ``RunType``；无法识别返回 ``None``。

    同时接受 ``.value``（小写）与成员名（大写）—— 后者是枚举列在 PostgreSQL
    原生 enum 下的实际存储形式。只认小写会让库里读出来的值静默变成 ``None``，
    再被当成「非正式提交」，从而把真实提交挡在排名之外。
    """
    if value is None:
        return None
    raw = str(getattr(value, "value", value))
    try:
        return RunType(raw)
    except ValueError:
        pass
    try:
        return RunType[raw.upper()]
    except KeyError:
        return None


def is_scored_run_type(value: Any) -> bool:
    """该类型是否参与计分（排名与掌握度的唯一入口判据）。"""
    parsed = normalize_run_type(value)
    return parsed in SCORED_RUN_TYPES
