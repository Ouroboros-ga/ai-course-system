"""G6 安全评估引擎

核心判断链：
  课程类型 + 当前教学目标 + 用户意图 + 请求对象 + 即将调用的工具 + 沙箱环境
  -> 允许 / 限制回答 / 教师确认 / 拒绝

三大能力：
  1. 内容安全评估 - 区分"知识回答"和"真实执行"
     允许合规知识流动，限制危险能力落地
  2. 工具权限校验链 - Agent请求工具 -> 课程权限 -> 安全策略 -> 白名单 -> 沙箱能力 -> 执行/确认/拒绝
  3. AI产出安全门控 - AI生成 -> 安全检查 -> 课程范围检查 -> 教师确认 -> 正式发布

关键词只能作为辅助信号，不能单独决定阻断。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Any
from datetime import datetime
from enum import Enum
import re

from sqlmodel import Session, select

from app.models.safety_policy_model import (
    CourseSafetyPolicy,
    CourseSandboxPolicy,
    SafetyAuditLog,
    CourseType,
    SandboxPreset,
    NetworkMode,
    AuditEventType,
    SafetyPolicyStatus,
    KEYWORD_ASSIST_LIST,
    POLITICAL_SENSITIVE_KEYWORDS,
    POLITICAL_TOPIC_KEYWORDS,
    COMPLIANT_POLITICAL_REPLY,
    COMPLIANT_SOVEREIGNTY_REPLY,
    DEFAULT_SAFETY_BLOCKED_REPLY,
    KeywordCategory,
    SafetyKeywordConfig,
    DEFAULT_KEYWORDS_BY_CATEGORY,
)


# ==================== 请求上下文与决策 ====================

class RequestIntent(str, Enum):
    """请求意图：区分知识回答与真实执行"""
    KNOWLEDGE = "knowledge"          # 知识回答：解释原理、防御措施、案例分析
    EXECUTION = "execution"          # 真实执行：运行代码、扫描目标、连接服务
    GENERATION = "generation"        # 内容生成：AI产出候选内容
    UNKNOWN = "unknown"


class DecisionAction(str, Enum):
    """决策动作"""
    ALLOW = "allow"                  # 允许
    RESTRICT_ANSWER = "restrict"      # 限制回答（仅知识层面，不执行）
    REQUIRE_CONFIRMATION = "confirm"  # 需教师确认
    REJECT = "reject"                 # 拒绝


@dataclass(frozen=True)
class RequestContext:
    """安全评估请求上下文

    捕获完整决策链的输入：
    - course_type: 课程安全类型
    - teaching_objective: 当前教学目标
    - user_intent: 用户意图(知识/执行/生成)
    - request_target: 请求对象(目标域名/IP/文件)
    - tool_to_call: 即将调用的工具
    - sandbox_environment: 沙箱环境状态
    """
    course_type: CourseType
    teaching_objective: str = ""
    user_intent: RequestIntent = RequestIntent.UNKNOWN
    request_target: Optional[str] = None
    tool_to_call: Optional[str] = None
    sandbox_preset: Optional[SandboxPreset] = None
    network_mode: Optional[NetworkMode] = None
    is_isolated: bool = False


@dataclass(frozen=True)
class SafetyDecision:
    """安全评估结果"""
    allowed: bool
    action: DecisionAction = DecisionAction.ALLOW
    requires_confirmation: bool = False
    reason: str = ""
    decision_factors: list[str] = field(default_factory=list)
    keyword_matched: Optional[str] = None
    # 2026-08-16：阻断时返回的合规回答文案（两套思政合规文案之一，或教师禁答兜底）
    compliance_reply: Optional[str] = None
    policy_version: str = "safety-policy-v2.1"
    context: Optional[RequestContext] = None


# 风险等级
RISK_LOW = "low"
RISK_MEDIUM = "medium"
RISK_HIGH = "high"

# 2026-08-17：思政课政治教学上下文词（立场性/教学性表述）。
# 思政课程命中政治高危词时，须同时满足：active 策略 + 教学意图 +
# 内容含以下上下文词之一才放行（如"为什么必须反对台独"），
# 否则仍拒绝——避免"请解释如何支持台独"这类措辞借道。
_POLITICAL_TEACHING_CONTEXT = (
    "为什么", "理解", "维护", "坚持", "反对", "抵制", "拥护",
    "依法", "意义", "内涵", "危害", "重要性", "学习", "辨析", "必须",
)


def _has_political_teaching_context(content: str) -> bool:
    lower = content.lower()
    return any(word in lower for word in _POLITICAL_TEACHING_CONTEXT)

# 关键词到风险等级的映射
KEYWORD_RISK = {
    "ctf": RISK_MEDIUM,
    "漏洞利用": RISK_HIGH,
    "提权": RISK_HIGH,
    "端口扫描": RISK_MEDIUM,
    "恶意代码": RISK_HIGH,
    "sql注入": RISK_MEDIUM,
    "xss": RISK_MEDIUM,
    "缓冲区溢出": RISK_HIGH,
    "逆向工程": RISK_MEDIUM,
    "密码破解": RISK_HIGH,
}


def evaluate_content_safety(
    session: Session,
    course_id: int,
    content: str,
    *,
    user_id: Optional[int] = None,
    tool_target: Optional[str] = None,
) -> SafetyDecision:
    """评估内容安全性

    关键词不能作为唯一允许或阻断依据。
    必须结合课程类型、教学意图、工具目标和隔离环境综合判断。

    2026-08-17 修复：
    - 政治敏感检查前置为平台级底线（fail-closed）：政治高危词（主权/分裂/
      颠覆/极端/邪教类）在任何课程、任何策略状态下都拒绝，不依赖教师配置；
      政治话题类别词在无有效策略时按专业课程默认处理（拒绝）。
    - 禁答主题为教师显式禁止项，命中直接拒绝，不再进入多因素分析
      （此前未知词默认中风险会在教学语境下被放行，禁答形同虚设）。
    """
    # 0. 平台级政治敏感底线（前置，任何课程/策略状态生效）
    keyword_map = _load_active_keywords(session)
    political_match = _match_political_keywords(content, keyword_map)
    if political_match:
        high_risk_words = keyword_map.get(KeywordCategory.POLITICAL_HIGH_RISK.value)
        if not high_risk_words:
            high_risk_words = list(POLITICAL_SENSITIVE_KEYWORDS)
        high_risk_lower = {word.lower() for word in high_risk_words}
        if political_match.lower() in high_risk_lower:
            # 思政课程教学豁免（2026-08-17，严格条件）：
            # active 思政策略 + 教学意图 + 立场/教学上下文词（如"为什么必须反对台独"）
            # 才放行政治概念讨论；专业/网安课程及普通措辞仍无条件拒绝。
            policy = session.exec(
                select(CourseSafetyPolicy).where(CourseSafetyPolicy.course_id == course_id)
            ).first()
            if policy is not None and policy.status == SafetyPolicyStatus.ACTIVE \
                    and policy.course_type == CourseType.IDEOLOGICAL:
                teaching_intent = _detect_teaching_intent(content)
                if teaching_intent == "educational" and _has_political_teaching_context(content):
                    decision = SafetyDecision(
                        allowed=True,
                        reason=f"思政课程：'{political_match}' 属政治教学内容，教学语境下放行。",
                        decision_factors=[
                            "ideological_high_risk_teaching_allowed",
                            f"teaching_intent={teaching_intent}",
                            "political_teaching_context",
                        ],
                        keyword_matched=political_match,
                    )
                    _log_audit(
                        session, course_id, user_id, policy,
                        AuditEventType.HIT,
                        f"思政课政治教学 '{political_match}' 教学语境放行", decision,
                        keyword_matched=political_match,
                    )
                    return decision
            decision = SafetyDecision(
                allowed=False,
                action=DecisionAction.REJECT,
                reason=f"政治敏感高危内容 '{political_match}' 被拒绝",
                decision_factors=["political_sensitive_high_risk", "platform_level_fail_closed"],
                keyword_matched=political_match,
                compliance_reply=COMPLIANT_SOVEREIGNTY_REPLY,
            )
            _log_audit(
                session, course_id, user_id, None,
                AuditEventType.BLOCK,
                f"政治敏感高危关键词 '{political_match}' 命中（平台底线，无需课程策略）", decision,
                keyword_matched=political_match,
            )
            return decision
        # 政治话题类别词：需按课程类型判断
        policy = session.exec(
            select(CourseSafetyPolicy).where(CourseSafetyPolicy.course_id == course_id)
        ).first()
        if policy is None or policy.status in (SafetyPolicyStatus.DRAFT, SafetyPolicyStatus.CONFLICT):
            # 无有效策略：按专业课程默认处理，政治话题内容拒绝
            decision = SafetyDecision(
                allowed=False,
                action=DecisionAction.REJECT,
                reason=f"政治话题 '{political_match}' 超出默认课程教学范围，拒绝回答。",
                decision_factors=[
                    "political_topic_blocked",
                    "no_active_policy_default_professional",
                ],
                keyword_matched=political_match,
                compliance_reply=COMPLIANT_POLITICAL_REPLY,
            )
            _log_audit(
                session, course_id, user_id, policy,
                AuditEventType.BLOCK,
                f"政治话题 '{political_match}' 命中（无有效策略默认拒绝）", decision,
                keyword_matched=political_match,
            )
            return decision
        decision = _political_sensitive_decision(
            policy, content, political_match, tool_target, session, course_id,
            keyword_map=keyword_map,
        )
        _log_audit(
            session, course_id, user_id, policy,
            AuditEventType.BLOCK if not decision.allowed else AuditEventType.HIT,
            f"政治敏感关键词 '{political_match}' 命中", decision,
            keyword_matched=political_match,
        )
        return decision

    # 1. 加载安全策略
    policy = session.exec(
        select(CourseSafetyPolicy).where(CourseSafetyPolicy.course_id == course_id)
    ).first()

    if policy is None:
        # 无策略时默认安全（基础教学；政治敏感已在步骤 0 拦截）
        return SafetyDecision(
            allowed=True,
            reason="无安全策略，默认允许",
            decision_factors=["no_policy_default_allow"],
        )

    # 如果策略是草稿状态，不执行阻断（政治敏感已在步骤 0 拦截）
    if policy.status in (SafetyPolicyStatus.DRAFT, SafetyPolicyStatus.CONFLICT):
        return SafetyDecision(
            allowed=True,
            reason=f"策略状态为 {policy.status.value}，不执行阻断",
            decision_factors=[f"policy_status={policy.status.value}"],
        )

    # 2. 检查禁答主题：教师显式禁止项，命中直接拒绝（2026-08-17 修复）
    for topic in policy.forbidden_topics:
        if topic.lower() in content.lower():
            decision = SafetyDecision(
                allowed=False,
                action=DecisionAction.REJECT,
                reason=f"禁答主题 '{topic}' 命中，拒绝回答",
                decision_factors=[
                    f"course_type={policy.course_type.value}",
                    "forbidden_topic_blocked",
                ],
                keyword_matched=topic,
                compliance_reply=DEFAULT_SAFETY_BLOCKED_REPLY,
            )
            _log_audit(session, course_id, user_id, policy,
                        AuditEventType.BLOCK, f"禁答主题 '{topic}' 命中", decision,
                        keyword_matched=topic)
            return decision

    # 3. 关键词辅助规则
    if policy.keyword_assist_enabled:
        matched_keyword = _match_keywords(content, keyword_map)
        if matched_keyword:
            # 关键词命中，升级为多因素分析（不直接阻断）
            decision = _multi_factor_analysis(
                policy, content, matched_keyword, tool_target, session, course_id,
                keyword_risks=_load_active_keyword_risks(session),
            )
            _log_audit(session, course_id, user_id, policy,
                        AuditEventType.HIT if decision.allowed else AuditEventType.BLOCK,
                        f"关键词 '{matched_keyword}' 命中", decision,
                        keyword_matched=matched_keyword)
            return decision

    # 4. 检查必须引用主题
    for topic in policy.required_citation_topics:
        if topic.lower() in content.lower():
            _log_audit(session, course_id, user_id, policy,
                        AuditEventType.PASS,
                        f"必须引用主题 '{topic}' 命中，放行", None)
            return SafetyDecision(
                allowed=True,
                reason=f"必须引用主题 '{topic}' 命中",
                decision_factors=["required_citation_topic_match"],
            )

    # 5. 无命中，放行
    return SafetyDecision(
        allowed=True,
        reason="无安全策略命中",
        decision_factors=["no_match"],
    )


def _load_active_keywords(session: Session) -> dict[str, list[str]]:
    """加载启用中的平台级屏蔽词（2026-08-16：管理员可配置）。

    返回 ``{category: [keywords]}``；数据库表不存在（未迁移/测试环境）或某类别
    无启用项时，回退到该类别默认硬编码列表，保证现有行为不变。
    """
    result: dict[str, list[str]] = {cat: [] for cat in DEFAULT_KEYWORDS_BY_CATEGORY}
    try:
        rows = session.exec(
            select(SafetyKeywordConfig).where(
                SafetyKeywordConfig.enabled.is_(True)
            )
        ).all()
    except Exception:  # noqa: BLE001 -- 表不可用时回退默认列表
        rows = []
    for row in rows:
        category = row.category.value if hasattr(row.category, "value") else str(row.category)
        result.setdefault(category, []).append(row.keyword)
    # 空类别回退默认列表
    for category, fallback in DEFAULT_KEYWORDS_BY_CATEGORY.items():
        if not result.get(category):
            result[category] = list(fallback)
    return result


def _load_active_keyword_risks(session: Session) -> dict[str, str]:
    """加载启用中屏蔽词的风险等级（2026-08-17：管理员可配置）。

    返回 ``{keyword.lower(): "high"|"medium"}``；表不可用时返回空，
    调用方回退到硬编码 ``KEYWORD_RISK``，再默认中风险。
    """
    try:
        rows = session.exec(
            select(SafetyKeywordConfig).where(
                SafetyKeywordConfig.enabled.is_(True)
            )
        ).all()
    except Exception:  # noqa: BLE001 -- 表不可用时回退默认映射
        return {}
    result: dict[str, str] = {}
    for row in rows:
        risk = row.risk_level if hasattr(row, "risk_level") else "medium"
        result[row.keyword.lower()] = risk if risk in (RISK_HIGH, RISK_MEDIUM) else RISK_MEDIUM
    return result


def _match_political_keywords(
    content: str,
    keyword_map: Optional[dict[str, list[str]]] = None,
) -> Optional[str]:
    """匹配政治敏感关键词（高危词优先，其次政治话题类别词）。

    返回命中的第一个关键词；未命中返回 None。
    高危词（主权/极端类）在任何课程类型下都触发；类别词仅在专业/网安课程触发，
    思政课程将类别词视为正常教学内容（由 _political_sensitive_decision 处理）。
    """
    kw = keyword_map or {}
    sensitive = kw.get(KeywordCategory.POLITICAL_HIGH_RISK.value)
    if not sensitive:
        sensitive = list(POLITICAL_SENSITIVE_KEYWORDS)
    topics = kw.get(KeywordCategory.POLITICAL_TOPIC.value)
    if not topics:
        topics = list(POLITICAL_TOPIC_KEYWORDS)

    content_lower = content.lower()
    for keyword in sensitive:
        if keyword.lower() in content_lower:
            return keyword
    for keyword in topics:
        if keyword.lower() in content_lower:
            return keyword
    return None


def _political_sensitive_decision(
    policy: CourseSafetyPolicy,
    content: str,
    matched: str,
    tool_target: Optional[str],
    session: Session,
    course_id: int,
    *,
    keyword_map: Optional[dict[str, list[str]]] = None,
) -> SafetyDecision:
    """政治敏感内容决策（2026-08-16 新增）。

    规则：
    - 高危词（国家主权/领土完整/分裂/颠覆/极端/邪教类）命中：任何课程类型（含思政课）都拒绝，
      回答使用 COMPLIANT_SOVEREIGNTY_REPLY；
    - 政治话题类别词（政治人物/政治事件/非法政治思想等）命中：
      * 思政类课程：视为正常教学内容，教学语境下放行；
      * 专业课程 / 网络安全课程：拒绝，回答使用 COMPLIANT_POLITICAL_REPLY。
    """
    factors: list[str] = [
        f"course_type={policy.course_type.value}",
        f"political_keyword={matched}",
        "political_sensitive",
    ]
    course_type = policy.course_type
    matched_lower = matched.lower()

    # 高危词：主权/分裂/颠覆/极端/邪教类，任何课程都拒绝（词表来自管理员配置或默认）
    kw = keyword_map or {}
    sensitive = kw.get(KeywordCategory.POLITICAL_HIGH_RISK.value)
    if not sensitive:
        sensitive = list(POLITICAL_SENSITIVE_KEYWORDS)
    sensitive_lower = {item.lower() for item in sensitive}
    if matched_lower in sensitive_lower:
        return SafetyDecision(
            allowed=False,
            action=DecisionAction.REJECT,
            reason=f"政治敏感高危内容 '{matched}' 被拒绝",
            decision_factors=factors + ["political_sensitive_high_risk"],
            keyword_matched=matched,
            compliance_reply=COMPLIANT_SOVEREIGNTY_REPLY,
        )

    # 思政类课程：政治话题类别词属于正常教学内容
    if course_type == CourseType.IDEOLOGICAL:
        teaching_intent = _detect_teaching_intent(content)
        factors.append(f"teaching_intent={teaching_intent}")
        if teaching_intent == "educational":
            return SafetyDecision(
                allowed=True,
                reason=f"思政课程：政治话题 '{matched}' 属正常教学内容，教学语境下放行。",
                decision_factors=factors + ["ideological_topic_allowed"],
                keyword_matched=matched,
            )
        return SafetyDecision(
            allowed=False,
            requires_confirmation=True,
            reason=f"思政课程：政治话题 '{matched}' 非教学语境，需教师确认。",
            decision_factors=factors + ["ideological_topic_requires_confirmation"],
            keyword_matched=matched,
        )

    # 专业课程 / 网络安全课程：拒绝政治话题类别内容
    return SafetyDecision(
        allowed=False,
        action=DecisionAction.REJECT,
        reason=f"当前课程为 {course_type.value}，政治话题 '{matched}' 超出教学范围，拒绝回答。",
        decision_factors=factors + ["political_topic_blocked"],
        keyword_matched=matched,
        compliance_reply=COMPLIANT_POLITICAL_REPLY,
    )


def _multi_factor_analysis(
    policy: CourseSafetyPolicy,
    content: str,
    matched: str,
    tool_target: Optional[str],
    session: Session,
    course_id: int,
    *,
    keyword_risks: Optional[dict[str, str]] = None,
) -> SafetyDecision:
    """多因素分析：课程类型 + 教学意图 + 工具目标 + 沙箱策略

    关键词不能单独决定阻断。

    2026-08-17：
    - 风险等级优先取管理员配置（keyword_risks），回退硬编码 KEYWORD_RISK；
    - 专业课程中风险教学放行前校验沙箱网络模式（异常开启时转教师确认）。
    """
    factors: list[str] = []
    course_type = policy.course_type
    factors.append(f"course_type={course_type.value}")

    # 判断风险等级：管理员配置 > 硬编码映射 > 默认中风险
    risk = RISK_MEDIUM
    if keyword_risks and matched.lower() in keyword_risks:
        risk = keyword_risks[matched.lower()]
    else:
        risk = KEYWORD_RISK.get(matched.lower(), RISK_MEDIUM)
    factors.append(f"keyword_risk={risk}")

    # 教学意图分析：是否为教学语境
    teaching_intent = _detect_teaching_intent(content)
    factors.append(f"teaching_intent={teaching_intent}")

    # 工具目标分析
    if tool_target:
        factors.append(f"tool_target={tool_target}")
        # 检查是否在白名单内（2026-08-17：规范化匹配，大小写/尾斜杠不敏感）
        if _normalize_target(tool_target) in {
            _normalize_target(item) for item in (policy.course_whitelist or [])
        }:
            factors.append("tool_target_in_whitelist")
        else:
            factors.append("tool_target_not_in_whitelist")

    # 沙箱策略分析
    sandbox_policy = session.exec(
        select(CourseSandboxPolicy).where(CourseSandboxPolicy.course_id == course_id)
    ).first()
    if sandbox_policy:
        factors.append(f"sandbox_preset={sandbox_policy.sandbox_preset.value}")
        factors.append(f"network_mode={sandbox_policy.network_mode.value}")
        if sandbox_policy.network_mode == NetworkMode.ISOLATED_RANGE:
            factors.append("isolated_environment=True")
        elif sandbox_policy.network_mode == NetworkMode.WHITELIST:
            factors.append("whitelist_network=True")
        else:
            factors.append("network_disabled=True")
    else:
        factors.append("no_sandbox_policy")

    # ---- 决策逻辑 ----

    # 网络安全课程（2026-08-16 起合并原 CTF 审查）：
    # 隔离靶场（cybersecurity_range 或 ctf_isolated）+ 白名单 + 教学语境内允许合规教学内容
    if course_type == CourseType.CYBERSECURITY:
        isolated = sandbox_policy and sandbox_policy.sandbox_preset in (
            SandboxPreset.CYBERSECURITY_RANGE,
            SandboxPreset.CTF_ISOLATED,
        )
        if isolated:
            if teaching_intent == "educational":
                # 检查工具目标是否在白名单内（2026-08-17：规范化匹配）
                if tool_target and _normalize_target(tool_target) not in {
                    _normalize_target(item) for item in (policy.course_whitelist or [])
                }:
                    return SafetyDecision(
                        allowed=False,
                        reason=f"网安课程：工具目标 '{tool_target}' 不在白名单内。",
                        decision_factors=factors,
                        keyword_matched=matched,
                    )
                return SafetyDecision(
                    allowed=True,
                    requires_confirmation=risk == RISK_HIGH and policy.high_risk_confirmation_required,
                    reason=f"网安课程，教学内容在隔离靶场和白名单内允许。关键词 '{matched}' 非唯一依据。",
                    decision_factors=factors,
                    keyword_matched=matched,
                )
        # 网安课程但无隔离靶场 -> 需确认
        return SafetyDecision(
            allowed=False,
            requires_confirmation=True,
            reason=f"网安课程但未配置隔离靶场，需教师确认。关键词 '{matched}' 非唯一依据。",
            decision_factors=factors,
            keyword_matched=matched,
        )

    # 思政类课程（2026-08-16 新增）：网安攻击类关键词不属于思政教学内容，拒绝
    if course_type == CourseType.IDEOLOGICAL:
        return SafetyDecision(
            allowed=False,
            action=DecisionAction.REJECT,
            reason=f"思政课程：'{matched}' 不属于思政教学内容，拒绝回答。",
            decision_factors=factors + ["ideological_block_cyber_topic"],
            keyword_matched=matched,
            compliance_reply=DEFAULT_SAFETY_BLOCKED_REPLY,
        )

    # 专业课程（含原基础教学）：高风险内容阻断或需教师确认
    if risk == RISK_HIGH:
        if policy.high_risk_confirmation_required:
            return SafetyDecision(
                allowed=False,
                requires_confirmation=True,
                reason=f"专业课程：高风险关键词 '{matched}' 需教师确认。关键词非唯一依据，已综合课程类型和教学意图。",
                decision_factors=factors,
                keyword_matched=matched,
            )
        return SafetyDecision(
            allowed=False,
            action=DecisionAction.REJECT,
            reason=f"专业课程：高风险内容 '{matched}' 被阻断。",
            decision_factors=factors,
            keyword_matched=matched,
            compliance_reply=DEFAULT_SAFETY_BLOCKED_REPLY,
        )

    # 中等风险：在教学语境下放行
    if risk == RISK_MEDIUM and teaching_intent == "educational":
        # 2026-08-17：专业课程放行前校验沙箱网络——专业课程网络必须关闭；
        # 若沙箱被异常开启为隔离/白名单（DB 直改等），转教师确认避免可执行指令外泄。
        if course_type == CourseType.PROFESSIONAL and sandbox_policy is not None \
                and sandbox_policy.network_mode != NetworkMode.DISABLED:
            return SafetyDecision(
                allowed=False,
                requires_confirmation=True,
                reason=f"专业课程沙箱网络未关闭，中风险关键词 '{matched}' 需教师确认。",
                decision_factors=factors + ["professional_sandbox_network_not_disabled"],
                keyword_matched=matched,
            )
        return SafetyDecision(
            allowed=True,
            reason=f"中等风险关键词 '{matched}' 在教学语境下放行。关键词非唯一依据。",
            decision_factors=factors,
            keyword_matched=matched,
        )

    # 默认阻断
    return SafetyDecision(
        allowed=False,
        reason=f"内容 '{matched}' 被阻断（综合判断）。",
        decision_factors=factors,
        keyword_matched=matched,
    )


def _match_keywords(
    content: str,
    keyword_map: Optional[dict[str, list[str]]] = None,
) -> Optional[str]:
    """匹配网安攻击类关键词辅助规则（词表来自管理员配置或默认列表）。"""
    kw = keyword_map or {}
    keywords = kw.get(KeywordCategory.CYBER.value)
    if not keywords:
        keywords = list(KEYWORD_ASSIST_LIST)
    content_lower = content.lower()
    for keyword in keywords:
        if keyword.lower() in content_lower:
            return keyword
    return None


def _detect_teaching_intent(content: str) -> str:
    """检测教学意图

    区分"知识回答"和"真实执行"：
    - 知识回答：解释原理、防御措施、案例分析 -> educational
    - 真实执行：运行代码、扫描目标、连接服务 -> execution

    2026-08-17 修复：执行词与知识词同时出现时（如"请解释如何对目标进行
    sql注入 攻击"），若内容不含防御/原理类上下文则判为 execution，
    堵住"解释 + 攻击动词"的措辞包装；含防御/原理/分析等上下文的
    攻击概念讨论（如"如何防御 SQL 注入攻击"）仍判 educational。
    """
    knowledge_indicators = [
        "学习", "理解", "原理", "解释", "什么是", "为什么",
        "防御", "防范", "案例", "教学", "课程", "练习",
        "如何防御", "如何检测", "安全措施",
    ]
    execution_indicators = [
        "执行", "运行", "扫描", "攻击", "注入", "提取",
        "破解", "连接", "访问", "发送", "部署", "安装",
        "编译并运行", "实际操作", "对准", "目标",
    ]
    # 防御/原理类上下文：攻击概念的教学讨论（防御性/分析性），不是攻击指令
    defensive_indicators = [
        "防御", "防范", "检测", "原理", "分析", "理解",
        "如何防御", "如何检测", "安全措施", "风险", "危害",
        "是什么", "什么是", "为什么", "学习", "案例", "课程", "练习",
    ]
    content_lower = content.lower()

    has_execution = any(ind in content_lower for ind in execution_indicators)
    has_knowledge = any(ind in content_lower for ind in knowledge_indicators)

    if has_execution and not has_knowledge:
        return "execution"
    if has_knowledge:
        # 2026-08-17：执行词 + 知识词同时出现时，防御/原理上下文才判 educational
        if has_execution and not any(ind in content_lower for ind in defensive_indicators):
            return "execution"
        return "educational"
    return "unknown"


def _detect_request_intent(content: str) -> RequestIntent:
    """检测请求意图：知识回答 vs 真实执行 vs 内容生成"""
    content_lower = content.lower()

    # 生成意图
    generation_indicators = ["生成", "创建", "自动生成", "AI产出", "草稿", "候选"]
    if any(ind in content_lower for ind in generation_indicators):
        return RequestIntent.GENERATION

    # 执行意图
    execution_indicators = [
        "执行", "运行", "扫描", "攻击", "注入", "连接",
        "发送请求", "编译并运行", "实际操作",
    ]
    if any(ind in content_lower for ind in execution_indicators):
        return RequestIntent.EXECUTION

    # 知识意图
    knowledge_indicators = [
        "解释", "原理", "什么是", "为什么", "如何防御",
        "学习", "理解", "案例", "教学",
    ]
    if any(ind in content_lower for ind in knowledge_indicators):
        return RequestIntent.KNOWLEDGE

    return RequestIntent.UNKNOWN


_READ_ONLY_TOOLS = frozenset({
    "student_state", "studentstatetool",
    "cognition", "cognitiontool",
    "graph_read", "graphreadtool",
    "course_retrieval", "courseretrievaltool",
    "question_bank", "questionbanktool",
    "visualization", "visualizationtool",
})
_NETWORK_TOOLS = frozenset({
    "http_request", "network_request", "socket_connect", "port_scan",
    "curl", "wget", "web_research", "webresearchtool",
})
_FILE_TOOLS = frozenset({"file_read", "file_write", "file_exec"})
_SANDBOX_TOOLS = frozenset({
    "code_execute", "compile_run", "test_run", "sandbox", "sandboxtool",
})
_MUTATING_TOOLS = frozenset({"learning_event", "learningeventtool"})
_KNOWN_TOOLS = (
    _READ_ONLY_TOOLS | _NETWORK_TOOLS | _FILE_TOOLS |
    _SANDBOX_TOOLS | _MUTATING_TOOLS
)
_FORBIDDEN_OPERATIONS = (
    "rm -rf", "sudo", "chmod 777", "dd if=", "mkfs",
    "shutdown", "reboot", "docker.sock", "--privileged",
)

# 2026-08-17：黑名单空白归一化（堵住 "rm  -rf"（双空格）等空白变体绕过）
_NORMALIZED_FORBIDDEN_OPERATIONS = [
    (original, re.sub(r"\s+", "", original).casefold())
    for original in _FORBIDDEN_OPERATIONS
]


def check_forbidden_operations(text: str) -> Optional[str]:
    """扫描文本中的平台硬边界禁止操作（2026-08-17 提取为独立函数）。

    供沙箱执行端点等真实执行路径复用；命中返回禁止操作，未命中返回 None。
    匹配前同时归一化文本与黑名单的空白（大小写不敏感），
    堵住 ``rm  -rf``（双空格）等空白变体绕过。
    """
    normalized = re.sub(r"\s+", "", text or "").casefold()
    for original, normalized_item in _NORMALIZED_FORBIDDEN_OPERATIONS:
        if normalized_item in normalized:
            return original
    return None


def _normalize_tool_name(tool_name: str) -> str:
    return tool_name.strip().replace("-", "_").casefold()


def _is_host_path(target: Optional[str]) -> bool:
    if not target:
        return False
    value = target.strip().replace("\\", "/").casefold()
    return (
        value.startswith(("/", "//"))
        or (len(value) >= 3 and value[1:3] == ":/")
        or value == ".."
        or value.startswith("../")
        or "/../" in value
        or value.startswith(("file:", "/proc/", "/sys/", "/dev/"))
    )


def _normalize_target(value: Optional[str]) -> str:
    """规范化网络目标（白名单匹配用）：去空白、去尾部斜杠、大小写不敏感。

    2026-08-17 修复：DNS 大小写不敏感，白名单此前精确匹配会把
    合法目标（如 ``Target.Cyber.Lab``）误拒，导致可用性问题。
    """
    return (value or "").strip().rstrip("/").casefold()


def evaluate_tool_call(
    session: Session,
    course_id: int,
    *,
    tool_name: str,
    tool_target: Optional[str] = None,
    tool_params: Optional[dict] = None,
    user_id: Optional[int] = None,
) -> SafetyDecision:
    """工具权限校验链

    Agent请求工具 -> 校验课程权限 -> 校验安全策略 -> 校验目标白名单 -> 校验沙箱能力 -> 执行/确认/拒绝

    安全不依赖模型"自觉"，而依赖执行层真正卡住危险动作。
    """
    normalized_tool = _normalize_tool_name(tool_name)
    params_text = str(tool_params or {}).casefold()

    # 平台硬边界不得因课程尚未创建/激活策略而失效。
    forbidden_operation = check_forbidden_operations(params_text)
    if forbidden_operation is not None:
        return SafetyDecision(
            allowed=False,
            action=DecisionAction.REJECT,
            reason=f"平台硬边界：禁止操作 '{forbidden_operation}'",
            decision_factors=[
                f"tool_name={normalized_tool}",
                "platform_hard_limit_violation",
            ],
        )

    if normalized_tool not in _KNOWN_TOOLS:
        return SafetyDecision(
            allowed=False,
            action=DecisionAction.REJECT,
            reason="未注册的工具不能执行",
            decision_factors=[
                f"tool_name={normalized_tool}",
                "unknown_tool_rejected",
            ],
        )

    if normalized_tool in _FILE_TOOLS and _is_host_path(tool_target):
        return SafetyDecision(
            allowed=False,
            action=DecisionAction.REJECT,
            reason="平台硬边界：禁止访问宿主机路径",
            decision_factors=[
                f"tool_name={normalized_tool}",
                "host_path_blocked",
            ],
        )

    policy = session.exec(
        select(CourseSafetyPolicy).where(CourseSafetyPolicy.course_id == course_id)
    ).first()

    if policy is None:
        if normalized_tool not in _READ_ONLY_TOOLS:
            return SafetyDecision(
                allowed=False,
                action=DecisionAction.REJECT,
                reason="执行型工具需要已激活的课程安全策略",
                decision_factors=["no_active_policy_fail_closed"],
            )
        return SafetyDecision(
            allowed=True,
            reason="只读工具通过平台硬边界检查",
            decision_factors=["no_policy_read_only_allow"],
        )

    if policy.status in (SafetyPolicyStatus.DRAFT, SafetyPolicyStatus.CONFLICT):
        if normalized_tool not in _READ_ONLY_TOOLS:
            return SafetyDecision(
                allowed=False,
                action=DecisionAction.REJECT,
                reason="执行型工具需要已激活且无冲突的课程安全策略",
                decision_factors=[
                    f"policy_status={policy.status.value}",
                    "inactive_policy_fail_closed",
                ],
            )
        return SafetyDecision(
            allowed=True,
            reason="只读工具通过平台硬边界检查",
            decision_factors=[
                f"policy_status={policy.status.value}",
                "inactive_policy_read_only_allow",
            ],
        )

    # 加载沙箱策略
    sandbox_policy = session.exec(
        select(CourseSandboxPolicy).where(CourseSandboxPolicy.course_id == course_id)
    ).first()

    factors: list[str] = [
        f"course_type={policy.course_type.value}",
        f"tool_name={normalized_tool}",
        f"tool_target={tool_target or 'none'}",
    ]

    if sandbox_policy:
        factors.append(f"sandbox_preset={sandbox_policy.sandbox_preset.value}")
        factors.append(f"network_mode={sandbox_policy.network_mode.value}")
        is_isolated = sandbox_policy.network_mode == NetworkMode.ISOLATED_RANGE
        factors.append(f"is_isolated={is_isolated}")
    else:
        is_isolated = False
        factors.append("no_sandbox_policy")

    # 1. 平台硬边界：始终禁止的操作
    # 2. 网络工具目标白名单校验
    if normalized_tool in _NETWORK_TOOLS and not tool_target:
        return SafetyDecision(
            allowed=False,
            action=DecisionAction.REJECT,
            reason="网络工具必须提供经过课程策略校验的目标",
            decision_factors=factors + ["network_target_required"],
        )
    if normalized_tool in _NETWORK_TOOLS and tool_target:
        # 网安课程（含原 CTF）：检查目标是否在白名单内
        if policy.course_type == CourseType.CYBERSECURITY:
            whitelist = {_normalize_target(item) for item in (policy.course_whitelist or [])}
            if _normalize_target(tool_target) not in whitelist:
                _log_audit(session, course_id, user_id, policy,
                            AuditEventType.BLOCK,
                            f"工具目标 '{tool_target}' 不在课程白名单内", None)
                return SafetyDecision(
                    allowed=False,
                    action=DecisionAction.REJECT,
                    reason=f"工具目标 '{tool_target}' 不在课程白名单内。CTF/网安课程只能访问白名单目标或隔离靶场。",
                    decision_factors=factors + ["target_not_in_whitelist"],
                )
            factors.append("target_in_whitelist")
        else:
            # 专业/思政课程：禁止网络工具对真实目标
            _log_audit(session, course_id, user_id, policy,
                        AuditEventType.BLOCK,
                        f"专业/思政课程禁止网络工具 '{tool_name}' 对真实目标", None)
            return SafetyDecision(
                allowed=False,
                action=DecisionAction.REJECT,
                reason=f"专业/思政课程：禁止网络工具 '{tool_name}' 对真实目标 '{tool_target}'。仅允许原理解释。",
                decision_factors=factors + ["network_tool_blocked_in_basic_course"],
            )

    # 3. 文件系统工具：禁止宿主机路径
    if normalized_tool in _FILE_TOOLS:
        if _is_host_path(tool_target):
            _log_audit(session, course_id, user_id, policy,
                        AuditEventType.BLOCK,
                        f"禁止访问宿主机路径 '{tool_target}'", None)
            return SafetyDecision(
                allowed=False,
                action=DecisionAction.REJECT,
                reason=f"平台硬边界：禁止访问宿主机路径 '{tool_target}'",
                decision_factors=factors + ["host_path_blocked"],
            )

    # 4. 沙箱执行工具：检查沙箱能力
    if normalized_tool in _SANDBOX_TOOLS:
        if sandbox_policy is None:
            _log_audit(session, course_id, user_id, policy,
                        AuditEventType.BLOCK,
                        "沙箱执行工具但无沙箱策略", None)
            return SafetyDecision(
                allowed=False,
                action=DecisionAction.REJECT,
                reason="沙箱执行工具需要沙箱策略配置",
                decision_factors=factors + ["no_sandbox_policy"],
            )
        # 检查语言是否允许
        if tool_params and "language" in tool_params:
            lang = tool_params["language"]
            if lang not in (sandbox_policy.allowed_languages or []):
                _log_audit(session, course_id, user_id, policy,
                            AuditEventType.BLOCK,
                            f"语言 '{lang}' 不在允许列表中", None)
                return SafetyDecision(
                    allowed=False,
                    action=DecisionAction.REJECT,
                    reason=f"语言 '{lang}' 不在课程允许的语言列表中",
                    decision_factors=factors + [f"language_{lang}_not_allowed"],
                )

    # 5. 高风险操作需教师确认
    high_risk_tools = {"code_execute", "port_scan", "network_request"}
    if normalized_tool in high_risk_tools and policy.high_risk_confirmation_required:
        _log_audit(session, course_id, user_id, policy,
                    AuditEventType.CONFIRM,
                    f"高风险工具 '{tool_name}' 需教师确认", None)
        return SafetyDecision(
            allowed=False,
            action=DecisionAction.REQUIRE_CONFIRMATION,
            requires_confirmation=True,
            reason=f"高风险工具 '{tool_name}' 需教师确认后执行",
            decision_factors=factors + ["high_risk_confirmation"],
        )

    # 6. 通过所有检查
    _log_audit(session, course_id, user_id, policy,
                AuditEventType.PASS,
                f"工具 '{tool_name}' 通过安全校验", None)
    return SafetyDecision(
        allowed=True,
        action=DecisionAction.ALLOW,
        reason=f"工具 '{tool_name}' 通过安全校验",
        decision_factors=factors + ["all_checks_passed"],
    )


def evaluate_ai_content(
    session: Session,
    course_id: int,
    content: str,
    *,
    source_materials: Optional[list[str]] = None,
    user_id: Optional[int] = None,
) -> SafetyDecision:
    """AI 产出安全门控

    AI生成 -> 安全策略检查 -> 原文与课程范围检查 -> 教师确认 -> 正式发布

    AI 产出先作为候选，不直接进入正式课程。
    """
    policy = session.exec(
        select(CourseSafetyPolicy).where(CourseSafetyPolicy.course_id == course_id)
    ).first()

    factors: list[str] = ["ai_content_gate", f"course_type={policy.course_type.value if policy else 'none'}"]

    if policy is None:
        return SafetyDecision(
            allowed=True,
            action=DecisionAction.REQUIRE_CONFIRMATION,
            requires_confirmation=True,
            reason="无安全策略，AI产出需教师确认后发布",
            decision_factors=factors + ["no_policy_require_confirmation"],
        )

    # 1. 安全策略检查
    safety_decision = evaluate_content_safety(
        session, course_id, content, user_id=user_id,
    )
    factors.extend(safety_decision.decision_factors)

    if not safety_decision.allowed:
        return SafetyDecision(
            allowed=False,
            action=DecisionAction.REJECT,
            reason=f"AI产出被安全策略拒绝: {safety_decision.reason}",
            decision_factors=factors,
        )

    # 2. 原文与课程范围检查
    if source_materials:
        factors.append(f"source_materials_count={len(source_materials)}")
        # 检查AI内容是否引用了课程资料
        has_source_reference = any(
            src in content or content in src
            for src in source_materials
        )
        if has_source_reference:
            factors.append("has_source_reference")
        else:
            factors.append("no_source_reference_warning")

    # 3. AI产出始终需要教师确认才能正式发布
    _log_audit(session, course_id, user_id, policy,
                AuditEventType.CONFIRM,
                "AI产出需教师确认后正式发布", None)
    return SafetyDecision(
        allowed=True,
        action=DecisionAction.REQUIRE_CONFIRMATION,
        requires_confirmation=True,
        reason="AI产出通过安全检查，需教师确认后正式发布",
        decision_factors=factors + ["teacher_confirmation_required"],
    )


def _log_audit(
    session: Session,
    course_id: int,
    user_id: Optional[int],
    policy: CourseSafetyPolicy,
    event_type: AuditEventType,
    action: str,
    decision: Optional[SafetyDecision],
    keyword_matched: Optional[str] = None,
):
    """记录审计日志"""
    log = SafetyAuditLog(
        course_id=course_id,
        user_id=user_id,
        event_type=event_type,
        action=action,
        reason=decision.reason if decision else "",
        details={
            "allowed": decision.allowed if decision else None,
            "requires_confirmation": decision.requires_confirmation if decision else None,
        },
        course_type=policy.course_type.value if policy else None,
        sandbox_preset=None,
        keyword_matched=keyword_matched,
        decision_factors=decision.decision_factors if decision else [],
    )
    session.add(log)
    session.commit()


def get_or_create_safety_policy(session: Session, course_id: int) -> CourseSafetyPolicy:
    """获取或创建默认安全策略"""
    policy = session.exec(
        select(CourseSafetyPolicy).where(CourseSafetyPolicy.course_id == course_id)
    ).first()
    if policy is None:
        policy = CourseSafetyPolicy(course_id=course_id)
        session.add(policy)
        session.commit()
        session.refresh(policy)
    return policy


def get_or_create_sandbox_policy(session: Session, course_id: int) -> CourseSandboxPolicy:
    """获取或创建默认沙箱策略"""
    policy = session.exec(
        select(CourseSandboxPolicy).where(CourseSandboxPolicy.course_id == course_id)
    ).first()
    if policy is None:
        policy = CourseSandboxPolicy(course_id=course_id)
        session.add(policy)
        session.commit()
        session.refresh(policy)
    return policy
