"""本地 Demo 样例数据：汽车与发动机总论课程（仅用于本地体验建设页 UI）。

用法：uv run python -m scripts.seed_demo_course [--force]
- 默认：若已存在同 fanya_course_id 课程则跳过。
- --force：删除旧样例再重建（幂等重跑）。

本脚本只写入合成/假名化数据，不包含真实学生数据。
"""
from __future__ import annotations

import sys
import uuid
from datetime import datetime

from sqlmodel import select

from app.core.time_utils import utcnow_aware
from app.models.access_control_model import CourseMembership
from app.models.course_build_model import CourseBuildDraft
from app.models.course_model import Course, CourseStatus
from app.models.course_outline_model import (
    CourseOutlineNode,
    CourseOutlineVersion,
    OutlineLifecycleStatus,
    OutlineNodeType,
    TeachingScriptNode,
    TeachingScriptVersion,
)
from app.models.database import session_factory
from app.models.user_model import User

DEMO_FANYA_ID = "demo_auto_engine_total_20260812"

# 目录树：(node_type, title, source_block_count, locked, long_title)
TREE = [
    (OutlineNodeType.CHAPTER, "汽车与发动机总论", 35, False, False),
    (OutlineNodeType.SECTION, "汽车的定义、分类与总体构造", 8, False, False),
    (OutlineNodeType.KNOWLEDGE_POINT, "汽车的定义与分类", 3, True, False),
    (OutlineNodeType.KNOWLEDGE_POINT, "车辆识别代号编码", 2, False, False),
    (OutlineNodeType.KNOWLEDGE_POINT, "汽车的总体构造", 4, False, False),
    (OutlineNodeType.SECTION, "发动机的工作原理与总体构造", 10, False, False),
    (OutlineNodeType.KNOWLEDGE_POINT, "四冲程发动机的工作原理", 5, False, False),
    (OutlineNodeType.KNOWLEDGE_POINT, "发动机的总体构造", 3, False, False),
    (OutlineNodeType.KNOWLEDGE_POINT, "内燃机名称及型号编制规则（含国内与国外内燃机编号规范对照说明）", 6, False, True),
    (OutlineNodeType.SECTION, "汽车行驶的基本原理", 7, False, False),
    (OutlineNodeType.KNOWLEDGE_POINT, "汽车行驶的驱动条件与附着条件", 4, False, False),
    (OutlineNodeType.KNOWLEDGE_POINT, "驱动力与附着力的相互关系及其工程应用", 5, False, True),
]

SCRIPT_TEMPLATE = """# {label}

## 导入
同学们好，这一节我们讲解「{title}」。

## 讲解要点
- 首先明确概念：{title} 是理解本课程后续内容的基础。
- 结合课程原文材料，逐条解释关键术语与工程背景。
- 通过实例说明该知识点在实际车辆结构中的体现。

## 小结
掌握 {title} 后，请同学们完成课后思考题，并预习下一节内容。
"""


def _block_refs(prefix: str, count: int) -> list[str]:
    return [f"blk_{prefix}_{uuid.uuid4().hex[:8]}" for _ in range(count)]


def _build_tree(session, teacher_id: int, course_id: int, version_id: str) -> dict[str, CourseOutlineNode]:
    """按 TREE 顺序构造 chapter -> section -> knowledge_point 树。"""
    created: dict[str, CourseOutlineNode] = {}
    chapter: CourseOutlineNode | None = None
    section: CourseOutlineNode | None = None
    order: dict[tuple[str | None, str], int] = {}
    for node_type, title, block_count, locked, _long in TREE:
        parent = chapter if node_type == OutlineNodeType.SECTION else section
        key = (parent.outline_node_id if parent else None, node_type.value)
        order[key] = order.get(key, 0) + 1
        node = CourseOutlineNode(
            outline_version_id=version_id,
            course_id=course_id,
            parent_node_id=parent.outline_node_id if parent else None,
            node_type=node_type,
            title=title,
            order_index=order[key],
            source_block_refs=_block_refs(prefix=node_type.value, count=block_count),
            page_range="1-40",
            generation_reason="demo_seed",
            confidence=0.95,
            content_hash=f"seed_{uuid.uuid4().hex}",
            locked_by=teacher_id if locked else None,
            locked_at=utcnow_aware() if locked else None,
        )
        session.add(node)
        session.flush()
        created[node.outline_node_id] = node
        if node_type == OutlineNodeType.CHAPTER:
            chapter = node
        elif node_type == OutlineNodeType.SECTION:
            section = node
    return created


def _seed() -> None:
    force = "--force" in sys.argv
    with session_factory() as session:
        teacher = session.exec(select(User).where(User.username == "TTT")).first()
        if teacher is None:
            print("[seed] 未找到 TTT 用户，请先运行 app.scripts.init_users")
            raise SystemExit(1)

        existing = session.exec(select(Course).where(Course.fanya_course_id == DEMO_FANYA_ID)).first()
        if existing and not force:
            print(f"[seed] 样例课程已存在（course_id={existing.id}），跳过。加 --force 可重建。")
            return
        if existing:
            course_id = existing.id
            for row in session.exec(select(TeachingScriptNode).where(TeachingScriptNode.course_id == course_id)):
                session.delete(row)
            for row in session.exec(select(TeachingScriptVersion).where(TeachingScriptVersion.course_id == course_id)):
                session.delete(row)
            for row in session.exec(select(CourseOutlineNode).where(CourseOutlineNode.course_id == course_id)):
                session.delete(row)
            for row in session.exec(select(CourseOutlineVersion).where(CourseOutlineVersion.course_id == course_id)):
                session.delete(row)
            for row in session.exec(select(CourseBuildDraft).where(CourseBuildDraft.course_id == course_id)):
                session.delete(row)
            for row in session.exec(select(CourseMembership).where(CourseMembership.course_id == course_id)):
                session.delete(row)
            session.delete(existing)
            session.commit()
            print(f"[seed] 已清理旧样例课程 course_id={course_id}")

        course = Course(
            fanya_course_id=DEMO_FANYA_ID,
            fanya_course_name="汽车与发动机总论（本地样例）",
            title="汽车与发动机总论",
            description="本地 Demo 样例课程：模拟云端课程的目录树与讲稿，用于验证建设页 UI。",
            teacher_id=teacher.id,
            status=CourseStatus.DRAFT,
            is_ai_generated=True,
            total_duration=3600,
            total_nodes=len(TREE),
            source_file_name="汽车构造与原理.pdf",
            total_pages=40,
        )
        session.add(course)
        session.flush()

        outline = CourseOutlineVersion(
            course_id=course.id,
            version=1,
            lifecycle_status=OutlineLifecycleStatus.DRAFT,
            generation_source="demo_seed",
            review_status="pending",
            created_by=teacher.id,
        )
        session.add(outline)
        session.flush()

        nodes = _build_tree(session, teacher.id, course.id, outline.outline_version_id)

        script_version = TeachingScriptVersion(
            course_id=course.id,
            outline_version_id=outline.outline_version_id,
            version=1,
            lifecycle_status=OutlineLifecycleStatus.DRAFT,
            generation_source="demo_seed",
            review_status="pending",
            created_by=teacher.id,
        )
        session.add(script_version)
        session.flush()

        knowledge_points = [
            n for n in nodes.values() if n.node_type == OutlineNodeType.KNOWLEDGE_POINT
        ]
        for i, node in enumerate(knowledge_points):
            label = node.display_label if hasattr(node, "display_label") else node.title
            locked = i % 3 == 0  # 约 1/3 知识点讲稿锁定，演示锁定图标
            session.add(TeachingScriptNode(
                script_version_id=script_version.script_version_id,
                course_id=course.id,
                outline_node_id=node.outline_node_id,
                content=SCRIPT_TEMPLATE.format(label=f"{node.title}", title=node.title),
                style="beginner",
                evidence_refs=[f"ev_{uuid.uuid4().hex[:10]}" for _ in range(2)],
                source_block_refs=node.source_block_refs,
                content_hash=f"seed_script_{uuid.uuid4().hex}",
                locked_by=teacher.id if locked else None,
                locked_at=utcnow_aware() if locked else None,
            ))

        session.add(CourseBuildDraft(
            course_id=course.id,
            current_step="structure",
            overall_status="in_progress",
            created_by=teacher.id,
        ))
        session.commit()
        print(f"[seed] 完成：course_id={course.id} 章/节/知识点 = 1/3/{len(knowledge_points)}，"
              f"锁定大纲节点={(sum(1 for n in nodes.values() if n.locked_by))}，讲稿 {len(knowledge_points)} 条")


if __name__ == "__main__":
    _seed()
