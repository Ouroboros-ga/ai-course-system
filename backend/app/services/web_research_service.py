"""G7 WebResearchTool 受控研究服务

核心流程：
  1. 检查课程是否启用 WebResearch
  2. 脱敏查询（移除学生身份数据）
  3. 检查域名白名单
  4. 检查检索预算
  5. 检查缓存
  6. 执行搜索（通过 httpx 调用外部 API）
  7. 缓存结果
  8. 返回"补充参考"（带来源、时间、用途）

硬约束：
  - 不发送学生原始聊天记录、身份数据或正式 Memory
  - 外部资料只标记为"补充参考"
  - 不以外网结果直接修改掌握度、推荐优先级或课程图谱
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Optional, Any

import httpx
from sqlmodel import Session, select

from app.models.web_research_model import (
    WebResearchConfig,
    WebResearchResult,
    ExternalReference,
    ResearchStatus,
    DEFAULT_ALLOWED_DOMAINS,
    DEFAULT_SEARCH_BUDGET_PER_QUERY,
    DEFAULT_MAX_RESULTS_PER_SEARCH,
    DEFAULT_CACHE_TTL_MINUTES,
)

# 敏感数据模式（用于脱敏）
SENSITIVE_PATTERNS = [
    "学号", "身份证", "手机号", "邮箱", "密码", "token",
    "username", "password", "email", "phone", "student_id",
]


def sanitize_query(query: str) -> str:
    """脱敏查询：移除学生身份数据

    不发送学生原始聊天记录、身份数据或正式 Memory。
    """
    sanitized = query
    for pattern in SENSITIVE_PATTERNS:
        # 移除包含敏感词的部分
        if pattern.lower() in sanitized.lower():
            import re
            # 移除 "pattern:value" 或 "pattern=value" 格式
            sanitized = re.sub(
                rf'{pattern}\s*[:：=]\s*\S+',
                '[REDACTED]',
                sanitized,
                flags=re.IGNORECASE,
            )
    return sanitized


def get_or_create_config(session: Session, course_id: int) -> WebResearchConfig:
    """获取或创建默认配置"""
    config = session.exec(
        select(WebResearchConfig).where(WebResearchConfig.course_id == course_id)
    ).first()
    if config is None:
        config = WebResearchConfig(course_id=course_id, enabled=False)
        session.add(config)
        session.commit()
        session.refresh(config)
    return config


def execute_research(
    session: Session,
    course_id: int,
    query: str,
    *,
    user_id: Optional[int] = None,
) -> WebResearchResult:
    """执行受控外部研究

    返回标记为"补充参考"的外部资料，与课程 Evidence 分开。
    """
    config = get_or_create_config(session, course_id)

    # 1. 检查是否启用
    if not config.enabled:
        return _create_result(
            course_id, query, ResearchStatus.DISABLED,
            reason="WebResearch 已被教师关闭",
        )

    # 2. 脱敏查询
    sanitized_query = sanitize_query(query)
    query_hash = hashlib.sha256(sanitized_query.encode()).hexdigest()

    # 3. 检查缓存
    cached = _check_cache(session, course_id, query_hash, config.cache_ttl_minutes)
    if cached:
        cached.status = ResearchStatus.CACHE_HIT
        session.add(cached)
        session.commit()
        return cached

    # 4. 检查预算
    recent_searches = _count_recent_searches(session, course_id)
    if recent_searches >= config.search_budget_per_query:
        return _create_result(
            course_id, sanitized_query, ResearchStatus.BUDGET_EXCEEDED,
            reason=f"检索预算已用尽 ({recent_searches}/{config.search_budget_per_query})",
        )

    # 5. 执行搜索
    try:
        results = _perform_search(sanitized_query, config)
    except Exception as e:
        return _create_result(
            course_id, sanitized_query, ResearchStatus.SEARCH_FAILED,
            reason=f"搜索失败: {str(e)[:200]}",
        )

    # 6. 过滤域名白名单
    filtered_results = []
    for result in results:
        domain = result.get("source_domain", "")
        if domain in (config.allowed_domains or []):
            filtered_results.append(result)
        # 非白名单域名被过滤

    if not filtered_results:
        return _create_result(
            course_id, sanitized_query, ResearchStatus.NO_RESULTS,
            reason="无白名单域名内的搜索结果",
        )

    # 7. 缓存结果
    result_record = WebResearchResult(
        course_id=course_id,
        query_hash=query_hash,
        query_text=sanitized_query,
        status=ResearchStatus.SUCCESS,
        results=filtered_results[:config.max_results_per_search],
        searches_used=1,
        expires_at=datetime.utcnow() + timedelta(minutes=config.cache_ttl_minutes),
    )
    session.add(result_record)

    # 8. 持久化外部参考
    for r in filtered_results[:config.max_results_per_search]:
        ref = ExternalReference(
            course_id=course_id,
            research_result_id=None,  # 稍后更新
            source_domain=r.get("source_domain", ""),
            source_url=r.get("source_url", ""),
            title=r.get("title", ""),
            snippet=r.get("snippet", ""),
            purpose="supplementary_reference",
            is_supplementary=True,
        )
        session.add(ref)

    session.commit()
    session.refresh(result_record)

    # 更新 ExternalReference 的 research_result_id
    refs = session.exec(
        select(ExternalReference).where(
            ExternalReference.course_id == course_id,
            ExternalReference.research_result_id.is_(None),
        )
    ).all()
    for ref in refs:
        ref.research_result_id = result_record.id
        session.add(ref)
    session.commit()

    return result_record


def _perform_search(query: str, config: WebResearchConfig) -> list[dict[str, Any]]:
    """执行搜索（实际调用外部搜索 API）

    当前为结构化占位：实际搜索由外部工具接入。
    不发送学生身份数据。
    """
    # 实际实现会调用外部搜索 API（如 Web Search API）
    # 当前返回空列表，表示搜索功能需要外部工具接入
    # 不可用、无引用或越权来源时拒绝使用
    return []


def _check_cache(
    session: Session,
    course_id: int,
    query_hash: str,
    ttl_minutes: int,
) -> Optional[WebResearchResult]:
    """检查缓存"""
    cached = session.exec(
        select(WebResearchResult).where(
            WebResearchResult.course_id == course_id,
            WebResearchResult.query_hash == query_hash,
            WebResearchResult.status == ResearchStatus.SUCCESS,
        )
    ).first()
    if cached and not cached.is_expired:
        return cached
    return None


def _count_recent_searches(session: Session, course_id: int) -> int:
    """统计近期搜索次数（用于预算控制）"""
    recent = datetime.utcnow() - timedelta(hours=1)
    results = session.exec(
        select(WebResearchResult).where(
            WebResearchResult.course_id == course_id,
            WebResearchResult.created_at >= recent,
            WebResearchResult.status.in_([ResearchStatus.SUCCESS, ResearchStatus.CACHE_HIT]),
        )
    ).all()
    return sum(r.searches_used for r in results)


def _create_result(
    course_id: int,
    query: str,
    status: ResearchStatus,
    reason: str = "",
) -> WebResearchResult:
    """创建失败/禁用结果"""
    query_hash = hashlib.sha256(query.encode()).hexdigest() if query else ""
    return WebResearchResult(
        course_id=course_id,
        query_hash=query_hash,
        query_text=query,
        status=status,
        results=[],
        searches_used=0,
    )


def serialize_result(result: WebResearchResult) -> dict[str, Any]:
    """序列化研究结果为前端友好格式"""
    return {
        "id": result.id,
        "course_id": result.course_id,
        "status": result.status.value,
        "query_text": result.query_text,
        "results": result.results,
        "searches_used": result.searches_used,
        "is_supplementary": True,  # 始终标记为补充参考
        "cannot_modify_mastery": True,
        "cannot_modify_recommendation": True,
        "cannot_modify_graph": True,
        "created_at": result.created_at.isoformat() if result.created_at else None,
        "expires_at": result.expires_at.isoformat() if result.expires_at else None,
    }


def serialize_config(config: WebResearchConfig) -> dict[str, Any]:
    """序列化配置"""
    return {
        "course_id": config.course_id,
        "enabled": config.enabled,
        "allowed_domains": config.allowed_domains,
        "search_budget_per_query": config.search_budget_per_query,
        "max_results_per_search": config.max_results_per_search,
        "cache_ttl_minutes": config.cache_ttl_minutes,
        "created_at": config.created_at.isoformat() if config.created_at else None,
        "updated_at": config.updated_at.isoformat() if config.updated_at else None,
    }
