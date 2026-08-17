"""M6：六维提示词注入 + 结构化解析契约测试。

回归目标（2026-08-17）：
- RESPONSE_SYSTEM 显式声明六维使用规则（调节讲解深度/风格，None 按 unknown
  不按 0.0，不声称更新掌握度/图谱/推荐）；
- 出题端口 build_generation_prompt 的六维 None 序列化为 "unknown"，绝不注入 0.0；
- inquiry_depth / intent 越界解析安全（None / "other" 兜底）；
- 预算收紧时六维 bucket 优先于 conversation_history 保留。
全部为纯函数/本地测试，不调用真实 LLM。
"""
from __future__ import annotations

import pytest

from app.platform.agents.edu.prompts import PROMPT_VERSION, RESPONSE_SYSTEM
from app.platform.agents.edu.workflow import (
    _constraint_intent,
    _fit_context_to_budget,
    _parse_inquiry_depth,
)
from app.services.question_generation_llm import build_generation_prompt


def test_response_system_declares_six_dimension_usage_rules():
    assert "认知状态（六维）使用规则" in RESPONSE_SYSTEM
    assert "unknown" in RESPONSE_SYSTEM
    assert "0.0" in RESPONSE_SYSTEM  # 显式禁止把未知当 0.0
    assert "更新" in RESPONSE_SYSTEM and "掌握度" in RESPONSE_SYSTEM


def test_prompt_version_bumped_to_1_3():
    assert PROMPT_VERSION == "teaching-agent-prompts/1.3"


def test_generation_prompt_serializes_none_as_unknown():
    system, user = build_generation_prompt(
        purpose="quiz",
        difficulty="easy",
        node_context=None,
        cognitive_snapshot={},
        six_dimensions={
            "observed_performance_score": 0.6,
            "evidence_confidence": None,
            "confusion_risk": None,
            "inquiry_depth": 0.8,
            "hint_dependency": None,
            "explanation_need": 0.3,
        },
        reason_codes=["low_performance_high_confidence"],
    )
    # None 维度序列化为 "unknown"，绝不注入 0.0 / null
    assert '"evidence_confidence": "unknown"' in user
    assert '"confusion_risk": "unknown"' in user
    assert '"hint_dependency": "unknown"' in user
    assert '"evidence_confidence": null' not in user
    assert '"evidence_confidence": 0.0' not in user
    # 有值维度保留数值
    assert '"observed_performance_score": 0.6' in user


def test_generation_prompt_keeps_all_six_dimension_keys():
    system, user = build_generation_prompt(
        purpose="quiz",
        difficulty="medium",
        node_context=None,
        cognitive_snapshot={},
        six_dimensions={"evidence_confidence": 0.7},
        reason_codes=[],
    )
    # 注入存在的键；不凭空补全缺失维度为 0.0
    assert "evidence_confidence" in user
    assert '"confusion_risk": 0.0' not in user
    assert '"hint_dependency": 0.0' not in user


def test_inquiry_depth_out_of_range_parses_none():
    assert _parse_inquiry_depth(1.5) is None
    assert _parse_inquiry_depth(-0.1) is None
    assert _parse_inquiry_depth("abc") is None
    assert _parse_inquiry_depth(None) is None
    assert _parse_inquiry_depth(0.75) == 0.75


def test_intent_out_of_range_falls_back_to_other():
    assert _constraint_intent({"intent": "bogus_intent"}) == "other"
    assert _constraint_intent({"intent": None}) == "other"
    assert _constraint_intent({"intent": "concept_question"}) == "concept_question"
    assert _constraint_intent({}) == "other"


def test_fit_context_budget_keeps_sixdim_before_history():
    context = {
        "course_id": 1,
        "user_message": "什么是数组",
        "intent": "concept_question",
        "current_concept_id": "ordered-array",
        "constraint_instruction": "约束",
        "cognitive_state": {
            "observed_performance_score": 0.55,
            "evidence_confidence": 0.75,
            "confusion_risk": 0.35,
            "inquiry_depth": 0.7,
            "hint_dependency": 0.4,
            "explanation_need": 0.45,
            "mastery_level": "medium",
            "sample_size": 6,
            "reason_codes": [
                "performance_from_quiz_accuracy",
                "low_performance_high_confidence",
                "confusion_from_error_pattern",
            ],
        },
        "conversation_history": [
            {"role": "user", "content": "第一个历史问题的完整文本内容用于压测预算"},
            {"role": "assistant", "content": "第一个历史回答的完整文本内容用于压测预算"},
            {"role": "user", "content": "第二个历史问题的完整文本内容用于压测预算"},
        ],
    }
    # 预算只够"必需身份 + cognitive_state"，conversation_history 必须被裁
    fitted, meta = _fit_context_to_budget(context, max_chars=500)
    assert "cognitive_state" in fitted
    assert "conversation_history" not in fitted
    assert "conversation_history" in meta["dropped_buckets"]


def test_fit_context_budget_large_budget_keeps_both():
    context = {
        "course_id": 1,
        "user_message": "问题",
        "intent": "other",
        "current_concept_id": "x",
        "constraint_instruction": "约束",
        "cognitive_state": {"evidence_confidence": 0.85},
        "conversation_history": [{"role": "user", "content": "历史问题"}],
    }
    fitted, meta = _fit_context_to_budget(context, max_chars=10000)
    assert "cognitive_state" in fitted
    assert "conversation_history" in fitted
    assert meta["dropped_buckets"] == []
