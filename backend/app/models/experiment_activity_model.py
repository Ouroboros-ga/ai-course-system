"""OJ Activity 域模型：作业 / 比赛等活动对题目的组织层。

命名说明（ADR-0001 决定 ⑥，**已接受的债**）：物理表名沿用 `experiment_*`
前缀 —— 前端 49 个 API client、108 条契约测试、75 个迁移都建在
`/experiments` 与 `experiment_*` 上，改名风险 ≥ 收益。域语义上是 Activity。

设计要点
--------
- **Activity 是组织层，不是第二套作答链路**。学生作答仍走
  `ExperimentAttempt` / `ExperimentRun`（本模块只给两者加可空 `activity_id`），
  判题 / 诊断 / 证据全链路零改动 —— ADR 红线「不双写 problem / submission」。
- **同一 Activity 固定一个 `problem_version_id`**（全部题目共用）。该不变式
  在域层 `assert_pinned_versions` 于**写入点**强制，坏数据进不来。
- type / status / scoring_mode / ranking_mode / scope_type 全部用
  `String` + 域层值域约束（`domain/oj/activity/policies.py`），**不用 DB 原生
  enum** —— 与本模块 `run_state` / `difficulty` 的取向一致，扩值免迁移。
- **刻意没有 "closed" 状态**：活动是否结束由 `end_at` 时间窗推导，存一个
  可漂移的 closed 位会和时间窗打架。
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, JSON, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.core.time_utils import utcnow_aware
from app.domain.oj.activity.policies import (
    DEFAULT_ACTIVITY_TYPE,
    normalize_activity_status,
    normalize_activity_type,
    normalize_ranking_mode,
    normalize_scoring_mode,
)


def _activity_key() -> str:
    return "act_" + uuid.uuid4().hex


class ExperimentActivity(SQLModel, table=True):
    """活动（作业 / 比赛）—— 组织若干题目并施加时间窗与可见范围。

    - 教师在课程内创建；`status` 走 draft → published → archived
    - 是否可作答 = `status == published` **且** 时间窗开放（时间判定在域层）
    - `scoring_mode` / `ranking_mode` 本期只实现 `sum` / `none`
    """

    __tablename__ = "experiment_activities"

    id: Optional[int] = Field(default=None, primary_key=True)
    activity_id: str = Field(
        default_factory=_activity_key,
        unique=True, index=True, max_length=64,
        description="业务键，供 attempt/run 引用（与其余 *_id 字符串键同约定）",
    )
    type: str = Field(
        default=DEFAULT_ACTIVITY_TYPE, index=True, max_length=32,
        description="homework/contest/exam/practice_set（值域见 domain/oj/activity）",
    )
    title: str = Field(max_length=200, description="活动标题")
    description_md: str = Field(
        default="", max_length=20_000,
        description="活动说明（Markdown 源文本）",
    )
    course_id: int = Field(foreign_key="courses.id", index=True)
    owner_id: int = Field(foreign_key="users.id", index=True, description="创建教师")

    status: str = Field(
        default="draft", index=True, max_length=16,
        description="draft/published/archived（无 closed：结束与否由 end_at 推导）",
    )

    # 时间窗。两端都可空 = 不限时（作业常见形态），域层只校验「都给了时 end > start」。
    start_at: Optional[datetime] = Field(default=None, index=True)
    end_at: Optional[datetime] = Field(default=None, index=True)
    allow_late_submit: bool = Field(
        default=False, description="截止后是否允许继续作答（迟交会在判定结果里标记 late）"
    )
    freeze_at: Optional[datetime] = Field(
        default=None,
        description="榜单冻结时刻（contest 语义，PR-15 实现；本列先建好不加行为）",
    )

    # 算分 / 排行。本期只实现 sum / none，值域在域层收窄到已实现项。
    scoring_mode: str = Field(default="sum", max_length=32)
    ranking_mode: str = Field(default="none", max_length=32)

    # 0 = 不限。语义「0 是不限而不是 0 次」写在域层与服务层，避免裸看列名误解。
    max_submissions: int = Field(default=0, ge=0, description="每生每题最大提交次数，0 = 不限")

    config_json: dict = Field(default_factory=dict, sa_column=Column(JSON))

    created_at: datetime = Field(default_factory=utcnow_aware)
    updated_at: datetime = Field(default_factory=utcnow_aware)
    published_at: Optional[datetime] = Field(default=None)

    def __init__(self, **data):  # noqa: D107  # 统一在入口规范化字符串枚举列
        if "type" in data:
            data["type"] = normalize_activity_type(data["type"])
        if "status" in data:
            data["status"] = normalize_activity_status(data["status"])
        if "scoring_mode" in data:
            data["scoring_mode"] = normalize_scoring_mode(data["scoring_mode"])
        if "ranking_mode" in data:
            data["ranking_mode"] = normalize_ranking_mode(data["ranking_mode"])
        super().__init__(**data)


class ExperimentActivityProblem(SQLModel, table=True):
    """活动—题目关联。

    - `problem_definition_id` / `problem_version_id` 引用**既有** experiment 域
      （definition 的业务键 `experiment_id`、version 的业务键 `version_id`），
      不新建题目表 —— ADR ①不建第二套表。
    - `version_id` 写入后不可变（发布前固化），由 service 在写入点强制。
    """

    __tablename__ = "experiment_activity_problems"

    id: Optional[int] = Field(default=None, primary_key=True)
    activity_id: str = Field(index=True, description="关联 ExperimentActivity.activity_id")
    problem_definition_id: str = Field(
        index=True, max_length=64,
        description="关联 ExperimentDefinition.experiment_id",
    )
    problem_version_id: str = Field(
        index=True, max_length=64,
        description="固化版本：同一 Activity 的全部题必须指向同一 version_id",
    )
    ordinal: int = Field(ge=1, description="题序，决定展示与算分顺序（重算 deterministic 的依据）")
    label: str = Field(default="", max_length=32, description="展示用题号，如 A / B / 1")
    max_score: float = Field(default=1.0, ge=0.0, description="该题满分")

    created_at: datetime = Field(default_factory=utcnow_aware)


class ExperimentActivityScope(SQLModel, table=True):
    """活动可见范围。

    - `course` 本期实现行为；`class` / `user` 建模但行为后续 PR 实现，
      service 侧解析时显式跳过并记日志（不报错、不静默当成 course）。
    - 同一 (activity_id, scope_type, scope_id) 唯一，重复添加无害化在 service。
    """

    __tablename__ = "experiment_activity_scopes"
    __table_args__ = (
        UniqueConstraint(
            "activity_id", "scope_type", "scope_id",
            name="uq_experiment_activity_scope",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    activity_id: str = Field(index=True, description="关联 ExperimentActivity.activity_id")
    scope_type: str = Field(max_length=16, description="course/class/user")
    scope_id: int = Field(description="随 scope_type 变化：course_id / class_id / user_id")

    created_at: datetime = Field(default_factory=utcnow_aware)


