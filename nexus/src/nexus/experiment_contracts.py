"""NX 自主实验固定契约（任务书 §2 原样，不表示已存在对应服务）。

- Resources / ExperimentScope / SandboxResult：pydantic 强校验，进出 HTTP
  控制服务的唯一形状；owner/session 由服务端注入，模型不能传用户 ID 或
  控制服务地址。
- RunRecord / AttemptRecord：JSON 可序列化记录形态（TypedDict，仅字段集合），
  调用方不得把该集合冒充完整 DB 设计；持久化实现见 T5 experiment_store。
- 授权 hash 覆盖 scope；实际命令与安装版本变化写 attempt，不回写授权 hash。
"""
from __future__ import annotations

from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field


class Resources(BaseModel):
    cpu: float = Field(gt=0)
    memory_mb: int = Field(gt=0)
    disk_mb: int = Field(gt=0)
    wall_time_s: int = Field(gt=0)


class ExperimentScope(BaseModel):
    objective: str
    repo_url: str
    repo_revision: str
    source_refs: list[str]
    data_refs: list[str]
    network_profile: str  # 服务端已配置的源策略，不是LLM自由填写ACL
    resources: Resources  # 服务端给默认值并核对可用容量
    mode: Literal["setup", "smoke", "reproduce"]
    allow_environment_repair: bool = True


class SandboxResult(BaseModel):
    operation_id: str
    status: Literal["running", "succeeded", "failed", "cancelled", "unknown"]
    exit_code: int | None = None
    output_tail: str = ""
    output_truncated: bool = False


# F1：操作类型（分类本身不是完成证据；判定看目标完成证据）。
# probe=目录/声明探测，environment=依赖安装/导入检查，diagnostic=诊断排错，
# target=目标执行，verification=验证/测试，file_tool=文件工具摘要。
OperationKind = Literal[
    "probe", "environment", "diagnostic", "target", "verification", "file_tool",
]

# F1：三种模式的目标差异（setup 不要求指标；smoke 要求目标程序/最小产物；
# reproduce 要求可比较指标政策）。
_GOAL_REQUIREMENTS: dict[str, dict[str, bool]] = {
    "setup": {"requires_env": True, "requires_target": False,
              "requires_metrics": False},
    "smoke": {"requires_env": True, "requires_target": True,
              "requires_metrics": False},
    "reproduce": {"requires_env": True, "requires_target": True,
                  "requires_metrics": True},
}


def derive_goal(scope: dict[str, Any] | None) -> dict[str, Any]:
    """由批准 scope 推导 ExperimentGoal（纯函数，可单测）。

    模型可以建议修复方式，但完成标准只来自本函数（服务端保存），
    禁止通过改写目标检查/指标阈值让结果通过。
    """
    scope = scope or {}
    mode = str(scope.get("mode") or "smoke")
    if mode not in _GOAL_REQUIREMENTS:
        mode = "smoke"
    req = _GOAL_REQUIREMENTS[mode]
    return {
        "mode": mode,
        "objective": str(scope.get("objective") or ""),
        "requires_env": req["requires_env"],
        "requires_target": req["requires_target"],
        "requires_metrics": req["requires_metrics"],
        "metric_policy": scope.get("metric_policy"),
        "env_checks": list(scope.get("env_checks") or []),
        "target_commands": list(scope.get("target_commands") or []),
    }


def classify_operation(command: str, kind_hint: str = "") -> str:
    """操作分类（启发式，确定性；存盘后作为判定输入，模型不可改写）。

    kind_hint=file_tool 直接归 file_tool；路由探针 `ls /workspace` 归 probe。
    其余按命令形状：环境安装/导入检查→environment；版本/资源诊断→diagnostic；
    测试/验证→verification；目录/仓库探测→probe；其余 execute→target。
    """
    import re as _re

    if str(kind_hint or "") == "file_tool":
        return "file_tool"
    text = (command or "").strip()
    if not text:
        return "diagnostic"
    if text.startswith("ls /workspace"):
        return "probe"
    low = text.lower()
    if _re.match(
        r"^(ls|pwd|cat|head|tail|find|git\s+(rev-parse|status|log)|"
        r"grep\s+\S+\s*$|ls\s+-a\s+/workspace)", text):
        # glob/grep 单 token 摘要已在 clean 侧另行处理；此处 probe 仅收
        # 目录/声明探测类命令。
        if low.startswith(("pip ", "conda ", "apt-get ", "npm ")):
            return "environment"
        return "probe"
    if low.startswith(
        ("pip ", "conda ", "apt-get ", "npm ", "poetry ",
         "pip install", "conda install", "python -m pip")):
        return "environment"
    if _re.match(
        r"^python\s+-c\s+[\"']import\s+", text, _re.IGNORECASE):
        return "environment"
    if low.startswith(
        ("python --version", "nvidia-smi", "df ", "free ",
         "which ", "env", "echo $")):
        return "diagnostic"
    if low.startswith(("pytest", "python -m pytest", "python -m unittest",
                       "flake8", "mypy")) or "eval_metric" in low:
        return "verification"
    return "target"


class RunRecord(TypedDict, total=False):
    """run 记录字段集合（非 DB 设计）：run_id、owner、session_id、scope_hash、
    approval_id、sandbox_id、graph_thread_id、status、attempt_no、
    last_operation_id。"""

    run_id: str
    owner: str
    session_id: str
    scope_hash: str
    approval_id: str
    sandbox_id: str
    graph_thread_id: str
    status: str
    attempt_no: int
    last_operation_id: str


class AttemptRecord(TypedDict, total=False):
    """attempt 记录字段集合（非 DB 设计）：operation_id、attempt_no、
    actual_command、config_changes、started_at、finished_at、exit_code、
    log_ref、artifact_refs。"""

    operation_id: str
    attempt_no: int
    actual_command: str
    config_changes: dict[str, Any]
    started_at: float
    finished_at: float
    exit_code: int | None
    log_ref: str
    artifact_refs: list[str]
