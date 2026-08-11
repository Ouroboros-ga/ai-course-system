from app.platform.agents.prep.actions import (
    PrepAction,
    PrepIntentDecision,
    prep_intent_from_decision,
    resolve_prep_intent,
)


def test_legacy_resolver_does_not_guess_free_text_from_keywords():
    intent = resolve_prep_intent(
        "请一键整理讲解脚本，保留术语但让表达更适合初学者。",
        selected_outline_node_id=None,
    )

    assert intent.action is None
    assert intent.needs_clarification


def test_legacy_resolver_asks_for_structured_classification_before_node_scope():
    intent = resolve_prep_intent(
        "把这个标题改得更准确，去掉 OCR 的图号。",
        selected_outline_node_id=None,
    )

    assert intent.action is None
    assert intent.needs_clarification
    assert "标题" in intent.clarification


def test_button_token_bypasses_language_guessing_but_keeps_teacher_requirements():
    intent = resolve_prep_intent(
        "删掉重复节点，并把动力基础放到发动机结构之前。",
        selected_outline_node_id=None,
        explicit_action=PrepAction.ORGANIZE_STRUCTURE,
    )

    assert intent.action == PrepAction.ORGANIZE_STRUCTURE
    assert not intent.apply_immediately
    assert intent.instruction.startswith("删掉")


def test_semantic_classifier_decision_can_authorize_a_high_confidence_batch():
    intent = prep_intent_from_decision(
        "请把整门课的讲解统一成适合初学者的表达并直接应用。",
        selected_outline_node_id=None,
        decision=PrepIntentDecision(
            action=PrepAction.OPTIMIZE_ALL_SCRIPTS,
            confidence=0.96,
            apply_immediately=True,
        ),
    )

    assert intent.action == PrepAction.OPTIMIZE_ALL_SCRIPTS
    assert intent.apply_immediately
    assert not intent.needs_clarification


def test_semantic_classifier_keeps_low_confidence_batch_reviewable():
    intent = prep_intent_from_decision(
        "帮我统一一下讲解。",
        selected_outline_node_id=None,
        decision=PrepIntentDecision(
            action=PrepAction.OPTIMIZE_ALL_SCRIPTS,
            confidence=0.82,
            apply_immediately=True,
        ),
    )

    assert intent.action == PrepAction.OPTIMIZE_ALL_SCRIPTS
    assert not intent.apply_immediately
    assert not intent.needs_clarification


def test_semantic_classifier_requires_scope_for_single_node_action():
    intent = prep_intent_from_decision(
        "把当前标题说得更准确。",
        selected_outline_node_id=None,
        decision=PrepIntentDecision(
            action=PrepAction.OPTIMIZE_NODE_TITLE,
            confidence=0.94,
        ),
    )

    assert intent.action is None
    assert intent.needs_clarification
    assert "标题" in intent.clarification


def test_free_text_ppt_requires_the_structured_classifier():
    intent = resolve_prep_intent("一键匹配 PPT 与课程知识点", selected_outline_node_id=None)

    assert intent.action is None
    assert intent.needs_clarification
