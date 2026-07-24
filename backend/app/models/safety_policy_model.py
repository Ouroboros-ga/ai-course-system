"""G6 课程安全围栏与沙箱治理数据模型

三类教师可配置、平台硬边界不可关闭的安全策略：
  1. CourseSafetyPolicy - 智能体安全围栏
  2. CourseSandboxPolicy - 课程实验沙箱权限
  3. SafetyAuditLog - 审计日志

平台硬边界（教师不可关闭）：
  - 宿主与容器隔离
  - 内网保护
  - 资源限制
  - 审计
  - 恶意持久化限制
  - 高风险系统调用限制
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel


class CourseType(str, Enum):
    """课程安全类型"""
    BASIC = "basic"                    # 基础教学
    PROFESSIONAL = "professional"      # 专业课程
    CYBERSECURITY = "cybersecurity"   # 网络安全课程
    CTF = "ctf"                        # CTF 隔离课程


class SandboxPreset(str, Enum):
    """沙箱预设"""
    BASIC_PROGRAMMING = "basic_programming"    # 基础编程
    ALGORITHM = "algorithm"                    # 算法实验
    DATA_PROCESSING = "data_processing"        # 数据处理
    CYBERSECURITY_RANGE = "cybersecurity_range"  # 网络安全隔离靶场
    CTF_ISOLATED = "ctf_isolated"              # CTF 隔离环境


class NetworkMode(str, Enum):
    """网络模式"""
    DISABLED = "disabled"            # 关闭
    WHITELIST = "whitelist"          # 白名单
    ISOLATED_RANGE = "isolated_range"  # 隔离靶场


class FileAccessMode(str, Enum):
    """文件访问模式"""
    TEMP_ONLY = "temp_only"      # 仅临时
    COURSE_FILES = "course_files"  # 课程文件


class SafetyPolicyStatus(str, Enum):
    """安全策略状态"""
    DRAFT = "draft"          # 策略草稿
    DRY_RUN = "dry_run"      # Dry-run 观察
    ACTIVE = "active"        # 正式启用
    CONFLICT = "conflict"    # 存在冲突


class AuditEventType(str, Enum):
    """审计事件类型"""
    POLICY_CHANGE = "policy_change"    # 策略修改
    HIT = "hit"                         # 关键词命中
    PASS = "pass"                       # 放行
    BLOCK = "block"                     # 阻断
    CONFIRM = "confirm"                 # 教师确认
    SANDBOX_RUN = "sandbox_run"         # 沙箱运行
    SANDBOX_BLOCK = "sandbox_block"     # 沙箱阻断


# 平台硬边界常量（教师不可关闭）
PLATFORM_HARD_LIMITS = {
    "host_container_isolation": True,
    "internal_network_protection": True,
    "resource_limits": True,
    "audit_enabled": True,
    "malicious_persistence_limit": True,
    "high_risk_syscall_limit": True,
    "no_host_path": True,
    "no_privileged_container": True,
}

# 关键词辅助规则（不作为唯一依据）
KEYWORD_ASSIST_LIST = [
    "ctf", "漏洞利用", "提权", "端口扫描", "恶意代码",
    "sql注入", "xss", "缓冲区溢出", "逆向工程", "密码破解",
]


class CourseSafetyPolicy(SQLModel, table=True):
    """课程智能体安全围栏配置

    教师可配置：课程类型、禁答主题、必须引用主题、课程白名单、高风险确认。
    关键词辅助规则不作为唯一允许或阻断依据。
    """

    __tablename__ = "course_safety_policies"

    id: Optional[int] = Field(default=None, primary_key=True)
    course_id: int = Field(foreign_key="courses.id", index=True, unique=True)

    # 课程安全类型
    course_type: CourseType = Field(default=CourseType.BASIC, index=True)

    # 教师可配置项
    forbidden_topics: list = Field(default_factory=list, sa_column=Column(JSON), description="禁答主题")
    required_citation_topics: list = Field(default_factory=list, sa_column=Column(JSON), description="必须引用主题")
    course_whitelist: list = Field(default_factory=list, sa_column=Column(JSON), description="课程白名单(允许的域名/目标)")
    high_risk_confirmation_required: bool = Field(default=True, description="高风险任务需教师确认")
    keyword_assist_enabled: bool = Field(default=True, description="关键词辅助规则启用")

    # 状态
    status: SafetyPolicyStatus = Field(default=SafetyPolicyStatus.DRAFT, index=True)

    # 平台硬边界（只读，始终为True，教师不可关闭）
    platform_hard_limits: dict = Field(
        default_factory=lambda: dict(PLATFORM_HARD_LIMITS),
        sa_column=Column(JSON),
        description="平台硬边界(只读)",
    )

    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class CourseSandboxPolicy(SQLModel, table=True):
    """课程实验沙箱权限配置

    教师为课程实验选择沙箱预设，配置语言、网络、文件、第三方包、资源限制。
    网络安全实验只能访问白名单目标或隔离靶场，不能任意访问公共互联网。
    """

    __tablename__ = "course_sandbox_policies"

    id: Optional[int] = Field(default=None, primary_key=True)
    course_id: int = Field(foreign_key="courses.id", index=True, unique=True)

    # 沙箱预设
    sandbox_preset: SandboxPreset = Field(default=SandboxPreset.BASIC_PROGRAMMING, index=True)

    # 语言与包
    allowed_languages: list = Field(
        default_factory=lambda: ["python3"],
        sa_column=Column(JSON),
        description="允许的语言列表",
    )
    allowed_packages: list = Field(
        default_factory=list,
        sa_column=Column(JSON),
        description="第三方包白名单",
    )

    # 网络与文件
    network_mode: NetworkMode = Field(default=NetworkMode.DISABLED, description="网络模式")
    network_whitelist: list = Field(
        default_factory=list,
        sa_column=Column(JSON),
        description="网络白名单目标(仅cybersecurity/ctf可用)",
    )
    file_access_mode: FileAccessMode = Field(default=FileAccessMode.TEMP_ONLY)

    # 资源限制（教师可在平台上限内调整）
    cpu_limit: int = Field(default=5, description="CPU时间限制(秒)")
    memory_limit: int = Field(default=128000, description="内存限制(KB)")
    wall_time_limit: int = Field(default=10, description="墙钟时间(秒)")

    # 环境策略
    environment_destroy_on_exit: bool = Field(default=True, description="退出时销毁环境")
    log_retention_days: int = Field(default=30, description="日志保留天数")

    # 平台硬边界（只读）
    platform_no_host_path: bool = Field(default=True, description="禁止宿主机路径(不可关闭)")
    platform_no_privileged: bool = Field(default=True, description="禁止特权容器(不可关闭)")
    platform_no_public_internet: bool = Field(
        default=True,
        description="禁止公共互联网任意访问(网安/CTF用白名单替代)",
    )

    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class SafetyAuditLog(SQLModel, table=True):
    """安全审计日志

    所有策略修改、命中、放行、阻断和教师确认均可审计。
    """

    __tablename__ = "safety_audit_logs"

    id: Optional[int] = Field(default=None, primary_key=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)

    event_type: AuditEventType = Field(index=True)
    action: str = Field(default="", description="动作描述")
    reason: str = Field(default="", description="原因")
    details: dict = Field(default_factory=dict, sa_column=Column(JSON), description="详细上下文")

    # 决策上下文
    course_type: Optional[str] = Field(default=None, description="决策时的课程类型")
    sandbox_preset: Optional[str] = Field(default=None, description="决策时的沙箱预设")
    keyword_matched: Optional[str] = Field(default=None, description="命中的关键词(如有)")
    decision_factors: list = Field(
        default_factory=list,
        sa_column=Column(JSON),
        description="决策因素列表(课程类型/教学意图/工具目标/隔离环境)",
    )

    created_at: datetime = Field(default_factory=datetime.utcnow)
