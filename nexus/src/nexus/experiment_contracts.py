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
