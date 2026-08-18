"""Deterministic policy: models do not choose the teaching action.

Migrated from ``app.platform.agents.policies.teaching_action``; the old
module re-exports this verbatim for backward compatibility.

认知数据存在两种序列化 schema，本策略对两者兼容：

- 六维认知端口（``providers/cognition/cognition.py``）输出
  ``evidence_confidence / confusion_risk / mastery_level / mastery_score /
  hint_dependency / explanation_need / inquiry_depth``；
- KG-MEST Shadow 报告端口（``providers/cognition/kg_mest.py``）输出
  ``confidence / repeated_error_risk / transfer_score / mastery_score /
  hint_dependency``。

读取规则：优先读六维字段，缺失时回退 KG-MEST 字段
（例如 ``evidence_confidence`` → ``confidence``、``confusion_risk`` →
``repeated_error_risk``）。所有数值读取都容忍 None 与非数值，避免
``float(None)`` 崩溃，也不把"未知"误判为"低分"。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _opt_float(learner: Mapping[str, Any], *keys: str) -> float | None:
    """Return the first non-None numeric value among ``keys``, else None.

    Values that are absent, None or non-numeric are skipped; a missing value
    is never coerced to 0.0 so callers can distinguish "no data" from "0".
    """
    for key in keys:
        value = learner.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _num(
    learner: Mapping[str, Any],
    *keys: str,
    default: float = 0.0,
) -> float:
    value = _opt_float(learner, *keys)
    return default if value is None else value


def _last_action(state: Mapping[str, Any]) -> str | None:
    """读取会话上一教学动作（M5 迟滞带依据）。

    由 ``workflow.record_event`` 经 conversation_context 持久化
    ``last_teaching_action``，``load_session_context`` 节点放入 state。
    无会话上下文时返回 None（退化原始阈值行为）。
    """
    session_context = state.get("session_context")
    if not isinstance(session_context, Mapping):
        return None
    last = session_context.get("last_teaching_action")
    return str(last) if last else None


def decide_teaching_action(state: Mapping[str, Any]) -> tuple[str, str]:
    if state.get("current_code_submission_id"):
        return "code_debugging", "code_submission_context_present"
    # 学生主动请求学习某个知识点（2026-08-18）："我想学传递函数"、
    # "感觉前置的微分方程不熟练，想先看看"等明确意图优先于诊断分支。
    # requested_concept_id 仅在图谱解析阶段确认存在时才会被写入 state。
    if state.get("requested_concept_id"):
        return "requested_jump", "learner_requested_jump"
    if _num(state, "concept_grounding_confidence") < 0.55:
        return "diagnostic_question", "concept_grounding_insufficient"
    learner = state.get("student_concept_state") or {}
    if not learner:
        return "diagnostic_question", "student_state_insufficient"
    # 六维端口输出 evidence_confidence，KG-MEST 端口输出 confidence。
    # 无证据/低置信度一律先诊断，不直接断言薄弱。
    confidence = _opt_float(learner, "evidence_confidence", "confidence")
    if confidence is None or confidence < 0.45:
        return "diagnostic_question", "student_state_insufficient"
    mastery_score = _opt_float(learner, "mastery_score")
    if mastery_score is None:
        return "diagnostic_question", "observed_performance_unknown"
    graph = state.get("graph_context") or {}
    prerequisites = graph.get("prerequisites") or state.get("prerequisites") or []
    weak_ids = {str(item.get("concept_id")) for item in state.get("weak_concepts", [])}
    if any(str(item.get("concept_id")) in weak_ids for item in prerequisites):
        return "prerequisite_review", "confirmed_weak_prerequisite"
    # 六维端口以 confusion_risk 表达重复错误/困惑，与 KG-MEST 的
    # repeated_error_risk 语义等价；两者都可驱动 misconception_repair。
    repeated_error_risk = _opt_float(learner, "repeated_error_risk", "confusion_risk")
    # M5 迟滞带：进入/退出双阈值，抑制阈值附近动作震荡。
    #   diagnostic_question   进入 confidence<0.45；退出 confidence>=0.6
    #   misconception_repair  进入 confusion>=0.7；  退出 <0.5
    #   hint_scaffolding      进入 mastery<0.7&hint>=0.6；退出 mastery>=0.75
    # 硬信号分支（code_debugging / concept_grounding / prerequisite_review /
    # transfer_practice）优先于迟滞保持，不被阻塞。
    last_action = _last_action(state)
    if last_action == "diagnostic_question" and confidence < 0.6:
        return "diagnostic_question", "hysteresis_hold_diagnostic"
    if (
        last_action == "misconception_repair"
        and repeated_error_risk is not None
        and repeated_error_risk >= 0.5
    ):
        return "misconception_repair", "hysteresis_hold_misconception_repair"
    hint_dependency = _opt_float(learner, "hint_dependency")
    if (
        last_action == "hint_scaffolding"
        and mastery_score < 0.75
        and hint_dependency is not None
        and hint_dependency >= 0.5
    ):
        return "hint_scaffolding", "hysteresis_hold_hint_scaffolding"
    if repeated_error_risk is not None and repeated_error_risk >= 0.7:
        return "misconception_repair", "repeated_error_risk_high"
    if mastery_score < 0.7 and hint_dependency is not None and hint_dependency >= 0.6:
        return "hint_scaffolding", "hint_dependency_high"
    # 六维端口不产出 transfer_score；仅在证据存在时（KG-MEST 路径）触发。
    transfer_score = _opt_float(learner, "transfer_score")
    if mastery_score >= 0.75 and transfer_score is not None and transfer_score < 0.5:
        return "transfer_practice", "transfer_evidence_insufficient"
    return "normal_answer", "sufficient_course_evidence"
