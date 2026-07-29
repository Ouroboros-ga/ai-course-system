from app.api.v1.endpoints.course_build_editor import _outline_node_view, _outline_tree_views, _script_node_view
from app.models.course_outline_model import CourseOutlineNode, OutlineNodeType, TeachingScriptNode


def test_scripts_receive_the_same_numbered_outline_label_as_the_structure():
    chapter = CourseOutlineNode(
        outline_node_id="on_chapter", outline_version_id="ov_demo", course_id=1,
        node_type=OutlineNodeType.CHAPTER, title="发动机基础", order_index=0,
    )
    section = CourseOutlineNode(
        outline_node_id="on_section", outline_version_id="ov_demo", course_id=1,
        parent_node_id=chapter.outline_node_id, node_type=OutlineNodeType.SECTION,
        title="四冲程发动机", order_index=0,
    )
    knowledge = CourseOutlineNode(
        outline_node_id="on_knowledge", outline_version_id="ov_demo", course_id=1,
        parent_node_id=section.outline_node_id, node_type=OutlineNodeType.KNOWLEDGE_POINT,
        title="工作原理", order_index=0,
    )
    ordered, displays = _outline_tree_views([knowledge, chapter, section])
    assert [node.outline_node_id for node in ordered] == ["on_chapter", "on_section", "on_knowledge"]
    assert displays[knowledge.outline_node_id]["display_label"] == "1.1.1 工作原理"
    script = TeachingScriptNode(
        course_id=1, script_version_id="tsv_demo", outline_node_id=knowledge.outline_node_id,
        content="讲稿正文",
    )
    view = _script_node_view(
        script,
        outline_view=_outline_node_view(knowledge, displays[knowledge.outline_node_id]),
    )
    assert view["display_label"] == "1.1.1 工作原理"
    assert view["outline_title"] == "工作原理"
