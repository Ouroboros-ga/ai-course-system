"""平台级安全屏蔽词配置服务（2026-08-16 新增）。

管理员通过 ``/api/v1/admin/safety-keywords`` 管理平台级安全屏蔽词，
影响所有课程的输入安全评估。关键词按类别组织：

- ``cyber``：网安攻击类（原 KEYWORD_ASSIST_LIST 默认 10 个）；
- ``political_high_risk``：政治高危（主权/分裂/颠覆/极端/邪教类）；
- ``political_topic``：政治话题类别词（专业/网安课程拒绝，思政课放行教学）。

同一关键词在同类别内唯一；删除/禁用后安全评估引擎立即按新列表工作，
无缓存（评估为低频路径，直接查库）。
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import UniqueConstraint  # noqa: F401  (用于提示唯一约束语义)
from sqlmodel import Session, select

from app.core.time_utils import utcnow_aware
from app.models.safety_policy_model import (
    DEFAULT_KEYWORDS_BY_CATEGORY,
    KeywordCategory,
    SafetyKeywordConfig,
)


def list_keywords(
    session: Session,
    *,
    category: Optional[str] = None,
    enabled: Optional[bool] = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    """分页列出屏蔽词配置（默认返回全部，含默认兜底说明）。"""
    statement = select(SafetyKeywordConfig)
    if category:
        statement = statement.where(SafetyKeywordConfig.category == KeywordCategory(category))
    if enabled is not None:
        statement = statement.where(SafetyKeywordConfig.enabled.is_(enabled))
    total = len(session.exec(statement).all())
    rows = session.exec(
        statement.order_by(
            SafetyKeywordConfig.category,
            SafetyKeywordConfig.id,
        ).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return {
        "items": [_serialize(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "defaults": {k: list(v) for k, v in DEFAULT_KEYWORDS_BY_CATEGORY.items()},
    }


def create_keyword(
    session: Session,
    actor_id: int,
    *,
    keyword: str,
    category: str,
    risk_level: str = "medium",
    description: str = "",
) -> SafetyKeywordConfig:
    """新增屏蔽词；同一类别下重复则报 ValueError。

    ``risk_level`` 仅对 cyber 类别生效（high/medium）；政治类别固定 high。
    """
    normalized = keyword.strip()
    if not normalized:
        raise ValueError("屏蔽词不能为空")
    # 2026-08-17：最小长度校验（防止单字短词子串匹配大面积误伤）
    if len(normalized) < 2:
        raise ValueError("屏蔽词至少需要 2 个字符")
    cat = KeywordCategory(category)
    existing = session.exec(
        select(SafetyKeywordConfig).where(
            SafetyKeywordConfig.keyword == normalized,
            SafetyKeywordConfig.category == cat,
        )
    ).first()
    if existing is not None:
        raise ValueError(f"屏蔽词 '{normalized}' 已存在于类别 {category}")
    effective_risk = _normalize_risk(cat, risk_level)
    row = SafetyKeywordConfig(
        keyword=normalized,
        category=cat,
        enabled=True,
        risk_level=effective_risk,
        description=(description or "").strip(),
        created_by=actor_id,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def update_keyword(
    session: Session,
    actor_id: int,
    keyword_id: int,
    *,
    keyword: Optional[str] = None,
    category: Optional[str] = None,
    enabled: Optional[bool] = None,
    risk_level: Optional[str] = None,
    description: Optional[str] = None,
) -> SafetyKeywordConfig:
    """更新屏蔽词（仅更新传入字段）。"""
    row = session.get(SafetyKeywordConfig, keyword_id)
    if row is None:
        raise KeyError(f"屏蔽词配置 {keyword_id} 不存在")

    new_keyword = keyword.strip() if keyword is not None else row.keyword
    if not new_keyword:
        raise ValueError("屏蔽词不能为空")
    if len(new_keyword) < 2:
        raise ValueError("屏蔽词至少需要 2 个字符")
    new_category = KeywordCategory(category) if category is not None else row.category
    # 唯一性校验（排除自身）
    dup = session.exec(
        select(SafetyKeywordConfig).where(
            SafetyKeywordConfig.keyword == new_keyword,
            SafetyKeywordConfig.category == new_category,
            SafetyKeywordConfig.id != keyword_id,
        )
    ).first()
    if dup is not None:
        raise ValueError(f"屏蔽词 '{new_keyword}' 已存在于类别 {new_category.value}")

    row.keyword = new_keyword
    row.category = new_category
    if enabled is not None:
        row.enabled = enabled
    if risk_level is not None:
        row.risk_level = _normalize_risk(new_category, risk_level)
    if description is not None:
        row.description = (description or "").strip()
    row.updated_at = utcnow_aware()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def delete_keyword(session: Session, actor_id: int, keyword_id: int) -> None:
    """删除屏蔽词配置。"""
    row = session.get(SafetyKeywordConfig, keyword_id)
    if row is None:
        raise KeyError(f"屏蔽词配置 {keyword_id} 不存在")
    session.delete(row)
    session.commit()


def _normalize_risk(category: KeywordCategory, risk_level: str) -> str:
    """归一化风险等级：仅 cyber 类别接受 high/medium；政治类别固定 high。"""
    if category == KeywordCategory.CYBER and risk_level in ("high", "medium"):
        return risk_level
    return "high"


def _serialize(row: SafetyKeywordConfig) -> dict[str, Any]:
    return {
        "id": row.id,
        "keyword": row.keyword,
        "category": row.category.value,
        "enabled": row.enabled,
        "risk_level": getattr(row, "risk_level", "medium"),
        "description": row.description,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
