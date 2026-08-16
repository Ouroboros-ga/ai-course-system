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

from sqlalchemy import Column, JSON, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.core.time_utils import utcnow_aware


class CourseType(str, Enum):
    """课程安全类型（2026-08-16 合并后仅三种，旧值作为兼容别名保留）

    合并语义：
    - ``PROFESSIONAL`` 合并了原 ``BASIC``（基础教学）与 ``PROFESSIONAL``（专业课程）；
    - ``CYBERSECURITY`` 合并了原 ``CYBERSECURITY``（网络安全课程）与 ``CTF``（CTF 隔离课程）的审查逻辑，
      二者都要求在隔离靶场 + 白名单内才允许合规教学内容；
    - ``IDEOLOGICAL`` 为新增思政类课程，允许合规政治教学内容，但拒绝非法政治思想与分裂/颠覆类内容。

    旧值 ``basic`` / ``ctf`` 仍可被读取或写入（``_missing_`` 兼容映射），
    前端未迁移期间传入旧值不会报错，均归一化为新类型。
    """
    PROFESSIONAL = "professional"        # 专业课程（原 basic + professional）
    CYBERSECURITY = "cybersecurity"     # 网络安全课程（原 cybersecurity + ctf 审查合并）
    IDEOLOGICAL = "ideological"          # 思政类课程（新增）

    # ---- 兼容别名（旧代码 / 旧数据 / 旧前端值）----
    BASIC = "professional"               # 原基础教学 -> 专业课程
    CTF = "cybersecurity"                # 原 CTF 隔离课程 -> 网络安全课程

    @classmethod
    def _missing_(cls, value: object):
        """把历史字符串值（大小写不敏感）归一化为新课程类型。"""
        legacy = {
            "basic": cls.PROFESSIONAL,
            "ctf": cls.CYBERSECURITY,
        }
        if isinstance(value, str):
            return legacy.get(value.lower())
        return None


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

# ---------------------------------------------------------------------------
# 政治敏感内容审查（2026-08-16 新增）
# ---------------------------------------------------------------------------

# 国家主权与领土完整类高危词：任何课程类型（含思政课程）命中即拒绝，
# 回答使用 COMPLIANT_SOVEREIGNTY_REPLY。
POLITICAL_SOVEREIGNTY_KEYWORDS = [
    "分裂国家", "颠覆国家政权", "台独", "藏独", "疆独", "港独",
    "叛国", "破坏国家统一", "国家主权", "领土完整", "国家利益",
    "危害国家安全", "泄露国家秘密",
]

# 非法政治思想 / 极端内容高危词：任何课程类型命中即拒绝，回答使用主权合规文案。
POLITICAL_EXTREMISM_KEYWORDS = [
    "非法政治思想", "法轮功", "邪教", "邪教组织", "恐怖主义",
    "恐怖袭击", "极端主义", "民族分裂主义",
]

# 政治敏感高危词全集（主权类 + 极端类）：所有课程类型命中即拒绝。
POLITICAL_SENSITIVE_KEYWORDS = (
    POLITICAL_SOVEREIGNTY_KEYWORDS + POLITICAL_EXTREMISM_KEYWORDS
)

# 政治话题类别词：仅在专业/网络安全课程中拒绝（回答使用 COMPLIANT_POLITICAL_REPLY）；
# 思政类课程视其为正常教学内容，不拒绝。
POLITICAL_TOPIC_KEYWORDS = [
    "政治人物", "政治事件", "政治运动", "政治谣言", "政治斗争",
]

# 符合中国特色社会主义价值观的两套合规回答（用于拒绝后的智能体回复）：
# 1) 政治问题合规回答：面向专业/网络安全课程中非教学范围的政治类提问；
# 2) 维护国家主权完整回答：面向涉及国家主权、领土完整、分裂/颠覆类内容。
COMPLIANT_POLITICAL_REPLY = (
    "该问题涉及政治领域内容，超出当前课程的教学范围。根据平台内容合规要求，"
    "本课程不解答此类问题，建议以国家权威发布的信息为准，并继续专注于本课程的专业知识学习。"
)
COMPLIANT_SOVEREIGNTY_REPLY = (
    "维护国家主权和领土完整是全体中国人民的共同意志和法定义务，任何分裂国家、"
    "危害国家安全的行为都违背中国法律和社会主义核心价值观。本课程不提供相关内容，"
    "请以国家法律法规和权威信息为准。"
)

# 安全审查阻断的通用回复（无课程定制文案时的兜底）
DEFAULT_SAFETY_BLOCKED_REPLY = (
    "该提问内容超出当前课程教学范围，无法回答。如有课程相关问题，欢迎继续提问。"
)

# ---------------------------------------------------------------------------
# 平台级安全屏蔽词配置（2026-08-16 新增，管理员可增删改/启禁用）
# ---------------------------------------------------------------------------


class KeywordCategory(str, Enum):
    """屏蔽词类别：与审查逻辑的分类一一对应。"""

    CYBER = "cyber"                            # 网安攻击类（原 KEYWORD_ASSIST_LIST）
    POLITICAL_HIGH_RISK = "political_high_risk"  # 政治高危（主权/分裂/颠覆/极端/邪教）
    POLITICAL_TOPIC = "political_topic"        # 政治话题类别词（思政课放行教学）


# 各类别默认屏蔽词（数据库表为空或不可用时的兜底；迁移 0063 将其 seed 入库）
DEFAULT_KEYWORDS_BY_CATEGORY: dict[str, list[str]] = {
    KeywordCategory.CYBER.value: list(KEYWORD_ASSIST_LIST),
    KeywordCategory.POLITICAL_HIGH_RISK.value: list(POLITICAL_SENSITIVE_KEYWORDS),
    KeywordCategory.POLITICAL_TOPIC.value: list(POLITICAL_TOPIC_KEYWORDS),
}


class SafetyKeywordConfig(SQLModel, table=True):
    """平台级安全屏蔽词配置

    管理员通过 ``/api/v1/admin/safety-keywords`` 管理；按类别（cyber /
    political_high_risk / political_topic）组织，同一关键词在同类别内唯一。
    启用中的屏蔽词由安全评估引擎加载，替代硬编码默认列表；
    表为空或不可用时回退到 ``DEFAULT_KEYWORDS_BY_CATEGORY``。
    """

    __tablename__ = "safety_keyword_configs"
    __table_args__ = (
        # 同一类别下关键词唯一，防止重复配置
        UniqueConstraint("keyword", "category", name="uq_safety_keyword_category"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    keyword: str = Field(max_length=100, index=True, description="屏蔽词")
    category: KeywordCategory = Field(index=True, description="屏蔽词类别")
    enabled: bool = Field(default=True, description="是否启用")
    # 2026-08-17：风险等级（high/medium），仅 cyber 类别生效；管理员可配置，
    # 决定网安关键词在教学语境下的放行/确认/阻断。political_* 类别固定 high。
    risk_level: str = Field(default="medium", max_length=10, description="风险等级 high/medium")
    description: str = Field(default="", max_length=200, description="说明")

    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=utcnow_aware)
    updated_at: datetime = Field(default_factory=utcnow_aware)


class CourseSafetyPolicy(SQLModel, table=True):
    """课程智能体安全围栏配置

    教师可配置：课程类型、禁答主题、必须引用主题、课程白名单、高风险确认。
    关键词辅助规则不作为唯一允许或阻断依据。
    """

    __tablename__ = "course_safety_policies"

    id: Optional[int] = Field(default=None, primary_key=True)
    course_id: int = Field(foreign_key="courses.id", index=True, unique=True)

    # 课程安全类型
    course_type: CourseType = Field(default=CourseType.PROFESSIONAL, index=True)

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
    created_at: datetime = Field(default_factory=utcnow_aware)
    updated_at: datetime = Field(default_factory=utcnow_aware)


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
    created_at: datetime = Field(default_factory=utcnow_aware)
    updated_at: datetime = Field(default_factory=utcnow_aware)


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

    created_at: datetime = Field(default_factory=utcnow_aware)
