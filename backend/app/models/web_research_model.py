"""G7 WebResearchTool 受控研究与接入

为 EduAgent 增加外部资料补充能力，但不让外网内容污染课程事实、引用链或认知结论。

硬约束：
  - 域名白名单：只允许教师配置的域名
  - 检索预算：限制每课程每查询的搜索次数
  - 结果缓存：避免重复搜索
  - 引用链接：每条外部参考带来源、时间和用途
  - 外部资料只标记为"补充参考"，与课程 Evidence 分开
  - 不发送学生原始聊天记录、身份数据或正式 Memory
  - 不以外网结果直接修改掌握度、推荐优先级或课程图谱
  - 教师可以关闭课程级 WebResearch
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel


class ResearchStatus(str, Enum):
    """研究结果状态"""
    SUCCESS = "success"
    NO_RESULTS = "no_results"
    DISABLED = "disabled"
    BUDGET_EXCEEDED = "budget_exceeded"
    DOMAIN_NOT_ALLOWED = "domain_not_allowed"
    SEARCH_FAILED = "search_failed"
    CACHE_HIT = "cache_hit"


# 默认允许的域名（教师可扩展）
DEFAULT_ALLOWED_DOMAINS = [
    "wikipedia.org",
    "stackoverflow.com",
    "github.com",
    "mdn.mozilla.org",
    "w3.org",
    "ieee.org",
    "acm.org",
]

# 默认预算
DEFAULT_SEARCH_BUDGET_PER_QUERY = 3
DEFAULT_MAX_RESULTS_PER_SEARCH = 5
DEFAULT_CACHE_TTL_MINUTES = 30


class WebResearchConfig(SQLModel, table=True):
    """课程级 WebResearch 配置

    教师可以关闭课程级 WebResearch。
    """

    __tablename__ = "web_research_configs"

    id: Optional[int] = Field(default=None, primary_key=True)
    course_id: int = Field(foreign_key="courses.id", index=True, unique=True)

    enabled: bool = Field(default=False, description="是否启用 WebResearch")
    allowed_domains: list = Field(
        default_factory=lambda: list(DEFAULT_ALLOWED_DOMAINS),
        sa_column=Column(JSON),
        description="域名白名单",
    )
    search_budget_per_query: int = Field(default=DEFAULT_SEARCH_BUDGET_PER_QUERY, description="每查询搜索预算")
    max_results_per_search: int = Field(default=DEFAULT_MAX_RESULTS_PER_SEARCH, description="每次搜索最大结果数")
    cache_ttl_minutes: int = Field(default=DEFAULT_CACHE_TTL_MINUTES, description="缓存TTL(分钟)")

    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WebResearchResult(SQLModel, table=True):
    """WebResearch 检索结果缓存

    外部资料只能标记为"补充参考"，与课程 Evidence 分开。
    """

    __tablename__ = "web_research_results"

    id: Optional[int] = Field(default=None, primary_key=True)
    course_id: int = Field(foreign_key="courses.id", index=True)

    # 查询信息（已脱敏，不含学生身份数据）
    query_hash: str = Field(index=True, description="查询内容SHA256哈希")
    query_text: str = Field(default="", description="脱敏后的查询文本(不含学生数据)")
    status: ResearchStatus = Field(default=ResearchStatus.SUCCESS, index=True)
    failure_reason: str = Field(default="", description="失败/拒绝原因，不含外部异常详情")

    # 结果（标记为"补充参考"）
    results: list = Field(
        default_factory=list,
        sa_column=Column(JSON),
        description="搜索结果列表，每条含source_domain/source_url/title/snippet/retrieved_at/purpose/is_supplementary",
    )

    # 预算跟踪
    searches_used: int = Field(default=0, description="本次研究使用的搜索次数")

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = Field(default=None, description="缓存过期时间")

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return True
        now = datetime.now(timezone.utc)
        expires_at = self.expires_at
        if expires_at.tzinfo is None:
            # Existing SQLite rows are UTC-naive compatibility data.
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return now > expires_at


class ExternalReference(SQLModel, table=True):
    """外部参考记录

    每条外部参考带来源、时间和用途。
    不以外网结果直接修改掌握度、推荐优先级或课程图谱。
    """

    __tablename__ = "external_references"

    id: Optional[int] = Field(default=None, primary_key=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    research_result_id: Optional[int] = Field(default=None, foreign_key="web_research_results.id", index=True)

    # 来源信息
    source_domain: str = Field(index=True, description="来源域名")
    source_url: str = Field(default="", description="来源URL")
    title: str = Field(default="", description="参考标题")
    snippet: str = Field(default="", description="内容摘要")
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="检索时间")

    # 用途与标记
    purpose: str = Field(default="supplementary_reference", description="用途")
    is_supplementary: bool = Field(default=True, description="始终为True，标记为补充参考")

    # 隔离标记
    cannot_modify_mastery: bool = Field(default=True, description="不可修改掌握度")
    cannot_modify_recommendation: bool = Field(default=True, description="不可修改推荐优先级")
    cannot_modify_graph: bool = Field(default=True, description="不可修改课程图谱")

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
