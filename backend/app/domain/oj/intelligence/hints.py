"""OJ 分层提示的**纯领域规则**（PR-06b，与 PR-06a 同一拆分取向）。

`CodingHintService` 里可归位的语义只有三件 —— 策略版本、full_solution 门禁、
审核决定值域。CRUD（建记录 / 列表 / 教师审核落库）是「何时读写 DB」，
留在 `experiment_service.CodingHintService`。

full_solution 门禁为什么是域规则而不是服务端 if
------------------------------------------------
「未获教师策略允许不得给完整答案」是**教学安全不变式**，不是某个端点的
参数校验：任何产生提示的路径（学生请求、finalize 附带、将来的批量生成）
都必须过同一道门。放在域层单点，调用方无法绕过；留在 service 的 if 里，
下一个写入点就会把它抄丢。
"""
from __future__ import annotations

__all__ = [
    "CODING_HINT_POLICY_VERSION",
    "FULL_SOLUTION_LEVEL",
    "HINT_REVIEW_DECISIONS",
    "assert_full_solution_allowed",
    "normalize_review_decision",
]

#: 提示策略版本号，每次提示策略变更时递增。
#: （原 `experiment_service.CODING_HINT_POLICY_VERSION`，PR-06b 归位。）
CODING_HINT_POLICY_VERSION = "coding-hint-v1.0"

#: full_solution 的取值字面量。与 `CodingHintLevel.FULL_SOLUTION.value` 一致
#: —— 两处独立定义（域层不 import ORM），一致性由测试守住。
FULL_SOLUTION_LEVEL = "full_solution"

#: 教师审核的合法决定。**不收其他词**：审核态决定 hint 是否可继续展示，
#: 拼写变体（ok / pass）会让前端分支失控。
HINT_REVIEW_DECISIONS: frozenset[str] = frozenset({"approved", "rejected"})


def assert_full_solution_allowed(hint_level: object, full_solution_allowed: bool) -> None:
    """full_solution 提示必须持教师策略授权，否则拒绝（不变式，单点把门）。

    `hint_level` 接受枚举或字符串（域层不 import ORM，与 `normalize_outcome`
    同一双接受取向）；`None` / 未知层级**不在此放行也不在此拒绝** ——
    层级合法性是 ORM 枚举的职责，这里只管 full_solution 这一道门。
    """
    raw = getattr(hint_level, "value", hint_level)
    if raw == FULL_SOLUTION_LEVEL and not full_solution_allowed:
        raise ValueError("教师策略未允许 full_solution 提示")


def normalize_review_decision(value: object) -> str:
    """规范化审核决定：非法值抛错，不兜底（审核态不可有模糊中间态）。"""
    text = str(getattr(value, "value", value) or "").strip().lower()
    if text not in HINT_REVIEW_DECISIONS:
        raise ValueError(
            f"审核决定必须是 {' 或 '.join(sorted(HINT_REVIEW_DECISIONS))}，收到：{value!r}"
        )
    return text
