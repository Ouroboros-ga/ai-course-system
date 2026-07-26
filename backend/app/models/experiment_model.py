"""阶段6 课程实验、Judge0 与 CodingAgent 持久化模型

实现实验定义、版本、测试用例、尝试、运行和提交记录，以及 CodingAgent 分层提示。

设计要点：
- `ExperimentDefinition`：教师管理的课程实验，绑定 course_id 严格隔离；
  publish_status 控制 draft/published/archived；语言白名单与资源限制固化在服务端。
- `ExperimentVersion`：实验版本，可回滚；每版携带测试用例（含隐藏测试）。
- `ExperimentTestCase`：测试用例，is_hidden 控制学生可见性；run 不向前端泄露隐藏测试详情。
- `ExperimentAttempt`：学生一次实验尝试，绑定 active_version_id，状态机：
  in_progress → submitted → finalized | failed。
- `ExperimentRun`：学生一次代码提交运行，绑定 attempt_id 与 task_id；
  承载分层结果（编译/运行/测试）与资源消耗，不直接修改认知状态。
- `ExperimentRunArtifact`：运行产物（stdout/stderr/编译输出/测试报告），独立存储避免大字段污染主表。
- `CodingHintRecord`：CodingAgent 分层提示记录，禁止执行任意前端代码；
  每次提示携带 hint_level、reason_codes、policy_version，便于审计与教师审核。

只有 finalize 成功才形成正式评分型 LearningEvidence；单次 run 日志不写掌握结论。
所有表按 course_id 严格隔离，绝不跨课程暴露。
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Column, JSON, UniqueConstraint
from sqlmodel import Field, SQLModel


# ---------------------------------------------------------------------------
# 实验定义
# ---------------------------------------------------------------------------


class ExperimentPublishStatus(str, Enum):
    """实验发布状态"""
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class ExperimentDefinition(SQLModel, table=True):
    """课程实验定义

    - 教师管理；语言白名单与资源限制固化在服务端
    - publish_status 控制 draft/published/archived
    - 与课程严格隔离：course_id 必填，所有查询按 course_id 过滤
    """

    __tablename__ = "experiment_definitions"

    id: Optional[int] = Field(default=None, primary_key=True)
    experiment_id: str = Field(
        default_factory=lambda: "exp_" + uuid.uuid4().hex,
        unique=True, index=True,
    )
    course_id: int = Field(foreign_key="courses.id", index=True)
    title: str = Field(default="", max_length=200)
    description: str = Field(default="")
    statement_object_key: str = Field(default="", description="实验说明文档对象键")
    language_whitelist: list = Field(
        default_factory=list, sa_column=Column(JSON),
        description="允许的编程语言白名单（subset of ALLOWED_LANGUAGES）",
    )
    default_version_id: Optional[str] = Field(
        default=None, index=True,
        description="当前激活版本 experiment_version_id",
    )
    publish_status: ExperimentPublishStatus = Field(
        default=ExperimentPublishStatus.DRAFT, index=True,
    )
    knowledge_node_ids: list = Field(
        default_factory=list, sa_column=Column(JSON),
        description="关联知识点节点",
    )
    max_attempts: int = Field(default=3, description="最大尝试次数")
    cooldown_minutes: int = Field(default=30, description="尝试冷却（分钟）")

    created_by: int = Field(foreign_key="users.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    archived_at: Optional[datetime] = Field(default=None)


# ---------------------------------------------------------------------------
# 实验版本与测试用例
# ---------------------------------------------------------------------------


class ExperimentVersion(SQLModel, table=True):
    """实验版本

    - 不可变版本，支持回滚
    - 每版携带测试用例（含隐藏测试）
    - 教师锁定后不被 AI 重跑覆盖
    """

    __tablename__ = "experiment_versions"
    __table_args__ = (
        UniqueConstraint(
            "experiment_id", "version_number",
            name="uq_experiment_version_number",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    version_id: str = Field(
        default_factory=lambda: "expv_" + uuid.uuid4().hex,
        unique=True, index=True,
    )
    experiment_id: str = Field(index=True, description="关联 ExperimentDefinition.experiment_id")
    course_id: int = Field(foreign_key="courses.id", index=True)
    version_number: int = Field(default=1, ge=1)
    label: str = Field(default="", max_length=100)

    # 资源限制（固化在服务端，不暴露给前端覆盖）
    cpu_time_limit: int = Field(default=5, description="秒")
    memory_limit: int = Field(default=128_000, description="KB")
    wall_time_limit: int = Field(default=10, description="秒")
    max_processes: int = Field(default=30)
    max_file_size: int = Field(default=1024, description="KB")
    enable_network: bool = Field(default=False, description="始终关闭")

    # 评分策略
    passing_score: float = Field(default=0.6, description="及格分 0..1")
    writes_formal_evidence: bool = Field(
        default=True,
        description="是否在 finalize 时写入正式 LearningEvidence",
    )

    is_locked: bool = Field(default=False, description="教师锁定，AI 不可覆盖")
    is_active: bool = Field(default=False, index=True, description="当前激活版本")
    created_by: int = Field(foreign_key="users.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ExperimentTestCase(SQLModel, table=True):
    """实验测试用例

    - is_hidden 控制学生可见性；run 不向前端泄露隐藏测试详情
    - 测试用例权重用于评分
    """

    __tablename__ = "experiment_test_cases"

    id: Optional[int] = Field(default=None, primary_key=True)
    case_id: str = Field(
        default_factory=lambda: "tc_" + uuid.uuid4().hex,
        unique=True, index=True,
    )
    version_id: str = Field(index=True, description="关联 ExperimentVersion.version_id")
    course_id: int = Field(foreign_key="courses.id", index=True)
    case_name: str = Field(default="", max_length=100)
    stdin: str = Field(default="")
    expected_stdout: str = Field(default="")
    is_hidden: bool = Field(default=False, index=True, description="隐藏测试不向前端泄露详情")
    weight: float = Field(default=1.0, description="评分权重")
    time_limit_override: Optional[int] = Field(default=None, description="单 case 超时覆盖(秒)")
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# 学生尝试与运行
# ---------------------------------------------------------------------------


class AttemptStatus(str, Enum):
    """尝试状态机：in_progress → submitted → finalized | failed"""
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    FINALIZED = "finalized"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExperimentAttempt(SQLModel, table=True):
    """学生一次实验尝试

    - 绑定 active_version_id，避免教师发布新版破坏进行中尝试
    - 状态机：in_progress → submitted → finalized | failed
    - finalize 成功才形成正式评分型 LearningEvidence
    """

    __tablename__ = "experiment_attempts"

    id: Optional[int] = Field(default=None, primary_key=True)
    attempt_id: str = Field(
        default_factory=lambda: "att_" + uuid.uuid4().hex,
        unique=True, index=True,
    )
    experiment_id: str = Field(index=True)
    version_id: str = Field(index=True, description="尝试开始时激活的版本，固化不可漂移")
    course_id: int = Field(foreign_key="courses.id", index=True)
    student_id: int = Field(foreign_key="users.id", index=True)

    status: AttemptStatus = Field(default=AttemptStatus.IN_PROGRESS, index=True)
    started_at: datetime = Field(default_factory=datetime.utcnow)
    submitted_at: Optional[datetime] = Field(default=None)
    finalized_at: Optional[datetime] = Field(default=None)

    # finalize 后形成
    final_score: Optional[float] = Field(default=None, description="0..1")
    passed: Optional[bool] = Field(default=None)
    evidence_id: Optional[str] = Field(
        default=None, index=True,
        description="finalize 成功后形成的 LearningEvidenceRecord.evidence_id",
    )
    return_anchor: dict = Field(
        default_factory=dict, sa_column=Column(JSON),
        description="学习位置回锚（course_id/node_id/page 等）",
    )

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class RunOutcome(str, Enum):
    """运行结果分类：每类给出可解释但不泄露隐藏测试的反馈"""
    PENDING = "pending"
    ACCEPTED = "accepted"
    WRONG_ANSWER = "wrong_answer"
    TIME_LIMIT_EXCEEDED = "time_limit_exceeded"
    MEMORY_LIMIT_EXCEEDED = "memory_limit_exceeded"
    RUNTIME_ERROR = "runtime_error"
    COMPILATION_ERROR = "compilation_error"
    INTERNAL_ERROR = "internal_error"
    SANDBOX_UNAVAILABLE = "sandbox_unavailable"


class ExperimentRun(SQLModel, table=True):
    """学生一次代码提交运行

    - 绑定 attempt_id 与 task_id（异步任务）
    - 承载分层结果（编译/运行/测试）与资源消耗
    - 单次运行日志不直接修改认知状态
    """

    __tablename__ = "experiment_runs"

    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(
        default_factory=lambda: "run_" + uuid.uuid4().hex,
        unique=True, index=True,
    )
    attempt_id: str = Field(index=True, description="关联 ExperimentAttempt.attempt_id")
    course_id: int = Field(foreign_key="courses.id", index=True)
    student_id: int = Field(foreign_key="users.id", index=True)
    task_id: Optional[str] = Field(default=None, index=True, description="关联 TaskRecord.task_id")

    language: str = Field(default="", description="编程语言（必须在白名单）")
    source_code: str = Field(default="", description="学生提交代码（受限于最大长度）")

    outcome: RunOutcome = Field(default=RunOutcome.PENDING, index=True)
    passed_count: int = Field(default=0, description="通过测试用例数")
    total_count: int = Field(default=0, description="总测试用例数")
    score: Optional[float] = Field(default=None, description="0..1")

    # 分层结果摘要（不泄露隐藏测试详情）
    compile_ok: bool = Field(default=True)
    compile_message: str = Field(default="")
    runtime_message: str = Field(default="")
    test_summary: dict = Field(
        default_factory=dict, sa_column=Column(JSON),
        description="分层测试摘要 [{case_name, passed, reason}]，隐藏测试仅返回 passed/reason",
    )

    # 资源消耗
    cpu_time_ms: Optional[int] = Field(default=None)
    wall_time_ms: Optional[int] = Field(default=None)
    memory_kb: Optional[int] = Field(default=None)

    error_code: str = Field(default="")
    error_message: str = Field(default="")

    submitted_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = Field(default=None)


class ExperimentRunArtifact(SQLModel, table=True):
    """运行产物（stdout/stderr/编译输出/测试报告）

    独立存储避免大字段污染主表；按 run_id 索引。
    """

    __tablename__ = "experiment_run_artifacts"

    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(index=True, description="关联 ExperimentRun.run_id")
    course_id: int = Field(foreign_key="courses.id", index=True)
    artifact_type: str = Field(default="", index=True, description="stdout|stderr|compile|test_report")
    content: str = Field(default="")
    content_object_key: str = Field(default="", description="大对象存储键")
    is_truncated: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# CodingAgent 分层提示
# ---------------------------------------------------------------------------


class CodingHintLevel(str, Enum):
    """分层提示：从概念到代码逐步揭示，避免直接给出答案"""
    CONCEPT = "concept"        # 概念提示
    APPROACH = "approach"      # 思路提示
    SCAFFOLD = "scaffold"      # 脚手架提示（伪代码/结构）
    PARTIAL = "partial"        # 部分实现提示
    FULL_SOLUTION = "full_solution"  # 完整答案（仅在教师允许时）


class CodingHintRecord(SQLModel, table=True):
    """CodingAgent 分层提示记录

    - CodingAgent 只能请求受控执行和分层提示，不能执行任意前端代码
    - 每次提示携带 hint_level、reason_codes、policy_version
    - full_solution 需教师策略显式允许；默认禁止
    """

    __tablename__ = "coding_hint_records"

    id: Optional[int] = Field(default=None, primary_key=True)
    hint_id: str = Field(
        default_factory=lambda: "hint_" + uuid.uuid4().hex,
        unique=True, index=True,
    )
    attempt_id: str = Field(index=True, description="关联 ExperimentAttempt.attempt_id")
    course_id: int = Field(foreign_key="courses.id", index=True)
    student_id: int = Field(foreign_key="users.id", index=True)

    hint_level: CodingHintLevel = Field(index=True)
    reason_codes: list = Field(default_factory=list, sa_column=Column(JSON))
    policy_version: str = Field(default="coding-hint-v1.0")
    requested_at: datetime = Field(default_factory=datetime.utcnow)
    fulfilled_at: Optional[datetime] = Field(default=None)
    fulfilled_by_agent: bool = Field(default=False)

    # 提示内容（concept/approach/scaffold/partial/full_solution）
    hint_text: str = Field(default="")
    hint_metadata: dict = Field(default_factory=dict, sa_column=Column(JSON))

    # 教师审核（可选）
    teacher_reviewed: bool = Field(default=False)
    teacher_decision: Optional[str] = Field(default=None, description="approved|rejected")
    teacher_note: str = Field(default="")
    reviewed_by: Optional[int] = Field(default=None, foreign_key="users.id")
    reviewed_at: Optional[datetime] = Field(default=None)
