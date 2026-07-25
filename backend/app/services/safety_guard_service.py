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
    policy_version: str = "safety-policy-v2.0"
    context: Optional[RequestContext] = None


# 风险等级
RISK_LOW = "low"
RISK_MEDIUM = "medium"
RISK_HIGH = "high"

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
    """
    # 加载安全策略
    policy = session.exec(
        select(CourseSafetyPolicy).where(CourseSafetyPolicy.course_id == course_id)
    ).first()

    if policy is None:
        # 无策略时默认安全（基础教学）
        return SafetyDecision(
            allowed=True,
            reason="无安全策略，默认允许",
            decision_factors=["no_policy_default_allow"],
        )

    # 如果策略是草稿状态，不执行阻断
    if policy.status in (SafetyPolicyStatus.DRAFT, SafetyPolicyStatus.CONFLICT):
        return SafetyDecision(
            allowed=True,
            reason=f"策略状态为 {policy.status.value}，不执行阻断",
            decision_factors=[f"policy_status={policy.status.value}"],
        )

    # 1. 检查禁答主题
    for topic in policy.forbidden_topics:
        if topic.lower() in content.lower():
            # 禁答主题命中，但需要多因素分析
            decision = _multi_factor_analysis(
                policy, content, topic, tool_target, session, course_id
            )
            _log_audit(session, course_id, user_id, policy,
                        AuditEventType.HIT if decision.allowed else AuditEventType.BLOCK,
                        f"禁答主题 '{topic}' 命中", decision)
            return decision

    # 2. 关键词辅助规则
    if policy.keyword_assist_enabled:
        matched_keyword = _match_keywords(content)
        if matched_keyword:
            # 关键词命中，升级为多因素分析（不直接阻断）
            decision = _multi_factor_analysis(
                policy, content, matched_keyword, tool_target, session, course_id
            )
            _log_audit(session, course_id, user_id, policy,
                        AuditEventType.HIT if decision.allowed else AuditEventType.BLOCK,
                        f"关键词 '{matched_keyword}' 命中", decision,
                        keyword_matched=matched_keyword)
            return decision

    # 3. 检查必须引用主题
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

    # 4. 无命中，放行
    return SafetyDecision(
        allowed=True,
        reason="无安全策略命中",
        decision_factors=["no_match"],
    )


def _multi_factor_analysis(
    policy: CourseSafetyPolicy,
    content: str,
    matched: str,
    tool_target: Optional[str],
    session: Session,
    course_id: int,
) -> SafetyDecision:
    """多因素分析：课程类型 + 教学意图 + 工具目标 + 沙箱策略

    关键词不能单独决定阻断。
    """
    factors: list[str] = []
    course_type = policy.course_type
    factors.append(f"course_type={course_type.value}")

    # 判断风险等级
    risk = KEYWORD_RISK.get(matched.lower(), RISK_MEDIUM)
    factors.append(f"keyword_risk={risk}")

    # 教学意图分析：是否为教学语境
    teaching_intent = _detect_teaching_intent(content)
    factors.append(f"teaching_intent={teaching_intent}")

    # 工具目标分析
    if tool_target:
        factors.append(f"tool_target={tool_target}")
        # 检查是否在白名单内
        if tool_target in (policy.course_whitelist or []):
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

    # CTF 隔离课程：在隔离环境内允许合规教学内容
    if course_type == CourseType.CTF:
        if sandbox_policy and sandbox_policy.sandbox_preset == SandboxPreset.CTF_ISOLATED:
            # CTF 使用隔离靶场，允许合规教学内容
            if teaching_intent == "educational":
                return SafetyDecision(
                    allowed=True,
                    requires_confirmation=risk == RISK_HIGH and policy.high_risk_confirmation_required,
                    reason=f"CTF 隔离课程，教学内容在隔离环境内允许。关键词 '{matched}' 非唯一依据。",
                    decision_factors=factors,
                    keyword_matched=matched,
                )
        # CTF 课程但无隔离环境 -> 需确认
        return SafetyDecision(
            allowed=False,
            requires_confirmation=True,
            reason=f"CTF 课程但未配置隔离靶场，需教师确认。关键词 '{matched}' 非唯一依据。",
            decision_factors=factors,
            keyword_matched=matched,
        )

    # 网络安全课程：在白名单和隔离环境内允许
    if course_type == CourseType.CYBERSECURITY:
        if sandbox_policy and sandbox_policy.sandbox_preset == SandboxPreset.CYBERSECURITY_RANGE:
            if teaching_intent == "educational":
                # 检查工具目标是否在白名单内
                if tool_target and tool_target not in (policy.course_whitelist or []):
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

    # 基础/专业课程：高风险内容阻断或需确认
    if risk == RISK_HIGH:
        if policy.high_risk_confirmation_required:
            return SafetyDecision(
                allowed=False,
                requires_confirmation=True,
                reason=f"基础/专业课程：高风险关键词 '{matched}' 需教师确认。关键词非唯一依据，已综合课程类型和教学意图。",
                decision_factors=factors,
                keyword_matched=matched,
            )
        return SafetyDecision(
            allowed=False,
            reason=f"基础/专业课程：高风险内容 '{matched}' 被阻断。",
            decision_factors=factors,
            keyword_matched=matched,
        )

    # 中等风险：在教学语境下放行
    if risk == RISK_MEDIUM and teaching_intent == "educational":
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


def _match_keywords(content: str) -> Optional[str]:
    """匹配关键词辅助规则"""
    content_lower = content.lower()
    for keyword in KEYWORD_ASSIST_LIST:
        if keyword.lower() in content_lower:
            return keyword
    return None


def _detect_teaching_intent(content: str) -> str:
    """检测教学意图

    区分"知识回答"和"真实执行"：
    - 知识回答：解释原理、防御措施、案例分析 -> educational
    - 真实执行：运行代码、扫描目标、连接服务 -> execution
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
    content_lower = content.lower()

    has_execution = any(ind in content_lower for ind in execution_indicators)
    has_knowledge = any(ind in content_lower for ind in knowledge_indicators)

    if has_execution and not has_knowledge:
        return "execution"
    if has_knowledge:
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
    forbidden_operation = next(
        (item for item in _FORBIDDEN_OPERATIONS if item in params_text),
        None,
    )
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
        # 网安/CTF 课程：检查目标是否在白名单内
        if policy.course_type in (CourseType.CYBERSECURITY, CourseType.CTF):
            whitelist = policy.course_whitelist or []
            if tool_target not in whitelist:
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
            # 基础/专业课程：禁止网络工具对真实目标
            _log_audit(session, course_id, user_id, policy,
                        AuditEventType.BLOCK,
                        f"基础/专业课程禁止网络工具 '{tool_name}' 对真实目标", None)
            return SafetyDecision(
                allowed=False,
                action=DecisionAction.REJECT,
                reason=f"基础/专业课程：禁止网络工具 '{tool_name}' 对真实目标 '{tool_target}'。仅允许原理解释。",
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
