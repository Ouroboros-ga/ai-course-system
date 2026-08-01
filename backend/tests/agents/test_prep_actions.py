from app.platform.agents.prep.actions import PrepAction, resolve_prep_intent


def test_natural_language_routes_to_the_same_all_script_action_as_the_button():
    intent = resolve_prep_intent(
        "请一键整理讲解脚本，保留术语但让表达更适合初学者。",
        selected_outline_node_id=None,
    )

    assert intent.action == PrepAction.OPTIMIZE_ALL_SCRIPTS
    assert not intent.needs_clarification
    assert intent.apply_immediately
    assert "初学者" in intent.instruction


def test_natural_language_requires_a_selected_node_for_single_node_actions():
    intent = resolve_prep_intent(
        "把这个标题改得更准确，去掉 OCR 的图号。",
        selected_outline_node_id=None,
    )

    assert intent.action is None
    assert intent.needs_clarification
    assert "选中" in intent.clarification


def test_button_token_bypasses_language_guessing_but_keeps_teacher_requirements():
    intent = resolve_prep_intent(
        "删掉重复节点，并把动力基础放到发动机结构之前。",
        selected_outline_node_id=None,
        explicit_action=PrepAction.ORGANIZE_STRUCTURE,
    )

    assert intent.action == PrepAction.ORGANIZE_STRUCTURE
    assert not intent.apply_immediately
    assert intent.instruction.startswith("删掉")


def test_ppt_request_is_routed_to_the_existing_mapping_workflow():
    intent = resolve_prep_intent("一键匹配 PPT 与课程知识点", selected_outline_node_id=None)

    assert intent.action == PrepAction.MATCH_PPT
