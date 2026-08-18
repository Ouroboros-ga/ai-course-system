"""TeachingAction policy: six-dimension cognition vs KG-MEST schema contract tests.

回归目标（2026-08-16）：
- 默认生产路径下 student_concept_state 来自六维认知端口（evidence_confidence /
  confusion_risk 等字段），策略必须据此分流，而不是恒走 diagnostic_question；
- KG-MEST 报告路径（confidence / repeated_error_risk / transfer_score）保持原行为；
- 任何 None / 缺失 / 非数值输入都不得抛 TypeError，也不得把"未知"当"低分"。
"""
from __future__ import annotations

from app.platform.agents.edu.policy import decide_teaching_action


def _state(learner, *, concept_grounding_confidence: float = 0.9, weak=None, prerequisites=None):
    return {
        "concept_grounding_confidence": concept_grounding_confidence,
        "student_concept_state": learner,
        "weak_concepts": weak or [],
        "graph_context": {"prerequisites": prerequisites or []},
    }


def test_sixdim_sufficient_evidence_selects_normal_answer():
    learner = {
        "evidence_confidence": 0.85,
        "mastery_score": 0.9,
        "confusion_risk": 0.1,
        "hint_dependency": 0.1,
        "explanation_need": 0.1,
    }
    assert decide_teaching_action(_state(learner)) == (
        "normal_answer",
        "sufficient_course_evidence",
    )


def test_sixdim_confusion_risk_selects_misconception_repair():
    # 六维端口用 confusion_risk 表达重复错误/困惑，应等价驱动 misconception_repair。
    learner = {
        "evidence_confidence": 0.85,
        "mastery_score": 0.6,
        "confusion_risk": 0.9,
        "hint_dependency": 0.1,
    }
    assert decide_teaching_action(_state(learner)) == (
        "misconception_repair",
        "repeated_error_risk_high",
    )


def test_sixdim_hint_dependency_selects_hint_scaffolding():
    learner = {
        "evidence_confidence": 0.85,
        "mastery_score": 0.5,
        "confusion_risk": 0.2,
        "hint_dependency": 0.8,
    }
    assert decide_teaching_action(_state(learner)) == (
        "hint_scaffolding",
        "hint_dependency_high",
    )


def test_sixdim_low_evidence_selects_diagnostic():
    # 样本不足（evidence_confidence=0.3）时先诊断，不直接断言薄弱。
    learner = {
        "evidence_confidence": 0.3,
        "mastery_score": 0.6,
        "confusion_risk": 0.1,
    }
    assert decide_teaching_action(_state(learner))[0] == "diagnostic_question"


def test_sixdim_no_evidence_does_not_crash_and_selects_diagnostic():
    learner = {
        "evidence_confidence": None,
        "mastery_score": None,
        "confusion_risk": None,
        "hint_dependency": None,
    }
    action, reason = decide_teaching_action(_state(learner))
    assert action == "diagnostic_question"
    assert reason == "student_state_insufficient"


def test_kq_mest_schema_still_selects_transfer_practice():
    learner = {
        "mastery_score": 0.85,
        "confidence": 0.9,
        "repeated_error_risk": 0.1,
        "hint_dependency": 0.1,
        "transfer_score": 0.3,
    }
    assert decide_teaching_action(_state(learner)) == (
        "transfer_practice",
        "transfer_evidence_insufficient",
    )


def test_kq_mest_confidence_none_does_not_crash():
    learner = {"confidence": None, "mastery_score": None}
    action, reason = decide_teaching_action(_state(learner))
    assert action == "diagnostic_question"
    assert reason == "student_state_insufficient"


def test_non_numeric_confidence_does_not_crash():
    learner = {"confidence": "n/a", "mastery_score": 0.8}
    action, reason = decide_teaching_action(_state(learner))
    assert action == "diagnostic_question"
    assert reason == "student_state_insufficient"


def test_missing_concept_grounding_selects_diagnostic():
    learner = {"evidence_confidence": 0.85, "mastery_score": 0.9}
    action, reason = decide_teaching_action(
        _state(learner, concept_grounding_confidence=0.0)
    )
    assert action == "diagnostic_question"
    assert reason == "concept_grounding_insufficient"


def test_confirmed_weak_prerequisite_selects_prerequisite_review():
    learner = {
        "evidence_confidence": 0.85,
        "mastery_score": 0.6,
        "confusion_risk": 0.1,
    }
    state = _state(
        learner,
        weak=[{"concept_id": "ordered-array"}],
        prerequisites=[
            {"concept_id": "ordered-array"},
            {"concept_id": "binary-search"},
        ],
    )
    assert decide_teaching_action(state) == (
        "prerequisite_review",
        "confirmed_weak_prerequisite",
    )


# ---------------------------------------------------------------------------
# M5 迟滞带：进入/退出双阈值抑制动作震荡
# ---------------------------------------------------------------------------


def _state_with_last(learner, last_action, **kwargs):
    state = _state(learner, **kwargs)
    state["session_context"] = {"last_teaching_action": last_action}
    return state


def test_diagnostic_hysteresis_holds_until_confidence_recovers():
    # 上一动作 diagnostic，confidence 回升到 0.5（仍在 0.6 退出门槛内）-> 保持
    learner = {
        "evidence_confidence": 0.5,
        "mastery_score": 0.9,
        "confusion_risk": 0.1,
        "hint_dependency": 0.1,
    }
    assert decide_teaching_action(
        _state_with_last(learner, "diagnostic_question")
    ) == ("diagnostic_question", "hysteresis_hold_diagnostic")


def test_diagnostic_hysteresis_releases_after_confidence_recovers():
    # confidence 0.62 >= 0.6 退出 -> 不再保持，落到 normal
    learner = {
        "evidence_confidence": 0.62,
        "mastery_score": 0.9,
        "confusion_risk": 0.1,
        "hint_dependency": 0.1,
    }
    action, reason = decide_teaching_action(
        _state_with_last(learner, "diagnostic_question")
    )
    assert action == "normal_answer"
    assert reason == "sufficient_course_evidence"


def test_misconception_repair_hysteresis_holds_until_risk_drops():
    # 上一动作 misconception_repair，confusion 降到 0.6（仍在 0.5 退出门槛内）-> 保持
    learner = {
        "evidence_confidence": 0.85,
        "mastery_score": 0.6,
        "confusion_risk": 0.6,
        "hint_dependency": 0.1,
    }
    assert decide_teaching_action(
        _state_with_last(learner, "misconception_repair")
    ) == ("misconception_repair", "hysteresis_hold_misconception_repair")


def test_misconception_repair_hysteresis_releases_after_risk_drops():
    learner = {
        "evidence_confidence": 0.85,
        "mastery_score": 0.6,
        "confusion_risk": 0.4,
        "hint_dependency": 0.1,
    }
    action, reason = decide_teaching_action(
        _state_with_last(learner, "misconception_repair")
    )
    assert action != "misconception_repair"
    assert not reason.startswith("hysteresis_hold")


def test_hint_scaffolding_hysteresis_holds_until_mastery_recovers():
    # 上一动作 hint_scaffolding，mastery 0.72（仍 < 0.75 退出门槛）-> 保持
    learner = {
        "evidence_confidence": 0.85,
        "mastery_score": 0.72,
        "confusion_risk": 0.1,
        "hint_dependency": 0.65,
    }
    assert decide_teaching_action(
        _state_with_last(learner, "hint_scaffolding")
    ) == ("hint_scaffolding", "hysteresis_hold_hint_scaffolding")


def test_hint_scaffolding_hysteresis_releases_after_mastery_recovers():
    learner = {
        "evidence_confidence": 0.85,
        "mastery_score": 0.78,
        "confusion_risk": 0.1,
        "hint_dependency": 0.65,
    }
    action, reason = decide_teaching_action(
        _state_with_last(learner, "hint_scaffolding")
    )
    assert action == "normal_answer"
    assert reason == "sufficient_course_evidence"


def test_no_session_context_falls_back_to_original_thresholds():
    # 无 session_context（首次请求/兼容路径）-> 迟滞不生效，原始阈值行为
    learner = {
        "evidence_confidence": 0.5,
        "mastery_score": 0.9,
        "confusion_risk": 0.1,
        "hint_dependency": 0.1,
    }
    action, reason = decide_teaching_action(_state(learner))
    assert action == "normal_answer"
    assert reason == "sufficient_course_evidence"


def test_hard_signal_prerequisite_review_not_blocked_by_hysteresis():
    # 硬信号（已确认薄弱前置）优先于迟滞保持
    learner = {
        "evidence_confidence": 0.5,
        "mastery_score": 0.6,
        "confusion_risk": 0.1,
    }
    state = _state_with_last(
        learner,
        "diagnostic_question",
        weak=[{"concept_id": "ordered-array"}],
        prerequisites=[{"concept_id": "ordered-array"}],
    )
    assert decide_teaching_action(state) == (
        "prerequisite_review",
        "confirmed_weak_prerequisite",
    )


# ---------------------------------------------------------------------------
# 学生主动学习跳转（2026-08-18）：requested_jump 优先于诊断/薄弱分支
# ---------------------------------------------------------------------------


def test_requested_jump_beats_weak_concept_grounding():
    # 学生明确请求学习某知识点（requested_concept_id 已解析）时，
    # 即使当前概念落地置信度低、认知状态不足，也优先响应用户的跳转请求。
    learner = {"evidence_confidence": None, "mastery_score": None}
    state = _state(
        learner,
        concept_grounding_confidence=0.0,
        weak=[],
        prerequisites=[],
    )
    state["requested_concept_id"] = "kn_transfer-function"
    assert decide_teaching_action(state) == (
        "requested_jump",
        "learner_requested_jump",
    )


def test_requested_jump_beats_diagnostic_and_weak_signals():
    learner = {
        "evidence_confidence": 0.3,
        "mastery_score": 0.6,
        "confusion_risk": 0.9,
    }
    state = _state(learner)
    state["requested_concept_id"] = "kn_linearization"
    action, reason = decide_teaching_action(state)
    assert action == "requested_jump"
    assert reason == "learner_requested_jump"


def test_no_requested_concept_keeps_existing_behavior():
    # 没有 requested_concept_id 时保持原有策略（薄弱前置仍触发 prerequisite_review）
    learner = {
        "evidence_confidence": 0.85,
        "mastery_score": 0.6,
        "confusion_risk": 0.1,
    }
    state = _state(
        learner,
        weak=[{"concept_id": "ordered-array"}],
        prerequisites=[{"concept_id": "ordered-array"}],
    )
    assert decide_teaching_action(state) == (
        "prerequisite_review",
        "confirmed_weak_prerequisite",
    )
