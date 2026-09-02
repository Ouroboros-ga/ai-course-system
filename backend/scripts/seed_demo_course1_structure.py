"""课程 1「数据结构」演示数据：目录树 + 讲授脚本 + PPT 映射。

依据课程 1 已上传材料「4正弦交流电路.pptx」(122 页) 的真实页面标题构造伪造
结构数据，供本地检查建设页 UI（课程结构 / 讲授脚本 / PPT 映射 / 媒体页 rail）。

数据来源全部为本地合成/真实解析产物（document_blocks / evidence_spans），
不包含真实学生数据。执行不会修改源材料、解析产物与知识图谱。

用法：uv run python -m scripts.seed_demo_course1_structure [--force]
- 默认：若课程 1 已存在目录/讲稿/映射则跳过。
- --force：删除课程 1 现有的目录/讲稿/映射再重建（幂等重跑）。
"""
from __future__ import annotations

import hashlib
import sys
import uuid

from sqlmodel import select

from app.core.time_utils import utcnow_aware
from app.models.course_build_model import CourseBuildDraft, SourceMaterial, SourceMaterialVersion
from app.models.course_model import Course
from app.models.course_outline_model import (
    CourseOutlineNode,
    CourseOutlineVersion,
    CoursePptMapping,
    OutlineLifecycleStatus,
    OutlineNodeType,
    TeachingScriptNode,
    TeachingScriptVersion,
)
from app.models.database import session_factory
from app.models.document_parse_model import DocumentBlock, EvidenceSpan
from app.models.user_model import User

COURSE_FANYA_ID = "local_cf6e1de0d0ea"

# 目录树：(node_type, title, page_start, page_end, locked, mapped)
# 页码与标题对齐课程 1 已上传 PPT 的真实 TITLE 块（p2 第4章 / p7 4.1.1 / p8 4.1.2 /
# p13 4.2 / p70 4.5 / p114 4.8 等）。``mapped=False`` 的知识点不建映射，演示"未映射"态。
TREE = [
    ("chapter", "正弦交流电路", 1, 122, False, True),
    ("section", "正弦量的基本概念", 4, 12, False, True),
    ("kp", "频率与周期", 7, 7, True, True),
    ("kp", "幅值与有效值", 8, 9, False, True),
    ("kp", "相位与相位差", 10, 12, False, False),
    ("section", "正弦量的相量表示法", 13, 32, False, True),
    ("kp", "正弦量用旋转有向线段表示", 14, 15, False, True),
    ("kp", "正弦量的相量表示", 16, 20, False, True),
    ("kp", "相量法应用与正误判断", 21, 32, True, True),
    ("section", "正弦交流电路的功率", 33, 69, False, True),
    ("kp", "有功功率与无功功率", 34, 40, False, True),
    ("kp", "视在功率与功率三角形", 41, 60, False, True),
    ("kp", "功率关系综合应用", 61, 69, False, True),
    ("section", "阻抗的串联与并联", 70, 113, False, True),
    ("kp", "阻抗的串联", 72, 83, True, True),
    ("kp", "正弦交流电路的分析和计算", 84, 94, False, True),
    ("kp", "阻抗的并联", 95, 113, False, True),
    ("section", "功率因数的提高", 114, 122, False, True),
    ("kp", "功率因数低的原因", 116, 118, False, True),
    ("kp", "功率因数的提高方法与结论", 119, 122, False, True),
]

SCRIPT_TEMPLATE = """# {label}

## 导入
同学们好，这一节我们讲解「{title}」。它来自课程第 4 章《正弦交流电路》的对应页码（第 {page_range} 页），我们先从现象出发建立直观认识。

## 讲解要点
- 先给出概念定义：{title} 是理解正弦交流电路的基础。
- 结合 PPT 中的公式与示意图，逐条解释关键参数与物理意义。
- 通过一个具体算例演示计算过程，并给出常见易错点提醒。

## 小结
掌握 {title} 后，请同学们完成课后思考题；下一节我们将基于它继续推导电路功率关系。
"""


def _hash(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _pages(start: int, end: int) -> list[int]:
    return list(range(start, end + 1))


def _block_refs_for_pages(session, course_id: int, material_version_id: str, pages: list[int], limit: int = 8) -> list[str]:
    """取真实 document_blocks 的 block_id 作为可审计来源引用。"""
    rows = session.exec(select(DocumentBlock).where(
        DocumentBlock.course_id == course_id,
        DocumentBlock.material_version_id == material_version_id,
        DocumentBlock.page_or_slide.in_(pages),
    ).order_by(DocumentBlock.page_or_slide, DocumentBlock.order_index)).all()
    return [row.block_id for row in rows[:limit] if row.block_id]


def _evidence_refs_for_pages(session, course_id: int, pages: list[int], limit: int = 3) -> list[str]:
    """取真实 evidence_spans 的 span_id 作为讲稿证据引用。"""
    rows = session.exec(select(EvidenceSpan).where(
        EvidenceSpan.course_id == course_id,
        EvidenceSpan.page_number.in_(pages),
    ).order_by(EvidenceSpan.page_number, EvidenceSpan.id)).all()
    return [row.span_id for row in rows[:limit] if row.span_id]


def _clean_course_data(session, course_id: int) -> None:
    """删除课程 1 现有的目录/讲稿/映射（仅演示层数据）。"""
    for row in session.exec(select(CoursePptMapping).where(CoursePptMapping.course_id == course_id)):
        session.delete(row)
    for row in session.exec(select(TeachingScriptNode).where(TeachingScriptNode.course_id == course_id)):
        session.delete(row)
    for row in session.exec(select(TeachingScriptVersion).where(TeachingScriptVersion.course_id == course_id)):
        session.delete(row)
    for row in session.exec(select(CourseOutlineNode).where(CourseOutlineNode.course_id == course_id)):
        session.delete(row)
    for row in session.exec(select(CourseOutlineVersion).where(CourseOutlineVersion.course_id == course_id)):
        session.delete(row)


def _build_outline(session, teacher_id: int, course_id: int, material_version_id: str, run_id: str) -> tuple[CourseOutlineVersion, list[CourseOutlineNode]]:
    outline = CourseOutlineVersion(
        course_id=course_id,
        version=1,
        lifecycle_status=OutlineLifecycleStatus.DRAFT,
        source_parse_run_id=run_id,
        generation_source="demo_seed",
        review_status="pending",
        created_by=teacher_id,
    )
    session.add(outline)
    session.flush()

    nodes: list[CourseOutlineNode] = []
    chapter: CourseOutlineNode | None = None
    section: CourseOutlineNode | None = None
    order: dict[tuple[str | None, str], int] = {}
    for node_type, title, page_start, page_end, locked, _mapped in TREE:
        if node_type == "chapter":
            node_cls = OutlineNodeType.CHAPTER
            parent = None
        elif node_type == "section":
            node_cls = OutlineNodeType.SECTION
            parent = chapter
        else:
            node_cls = OutlineNodeType.KNOWLEDGE_POINT
            parent = section
        key = (parent.outline_node_id if parent else None, node_cls.value)
        order[key] = order.get(key, 0) + 1
        refs = _block_refs_for_pages(session, course_id, material_version_id, _pages(page_start, page_end))
        node = CourseOutlineNode(
            outline_version_id=outline.outline_version_id,
            course_id=course_id,
            parent_node_id=parent.outline_node_id if parent else None,
            node_type=node_cls,
            title=title,
            order_index=order[key],
            source_block_refs=refs,
            page_range=f"{page_start}-{page_end}",
            generation_reason="demo_seed_based_on_uploaded_ppt",
            confidence=0.96,
            content_hash=_hash(node_cls.value, title, str(order[key])),
            locked_by=teacher_id if locked else None,
            locked_at=utcnow_aware() if locked else None,
        )
        session.add(node)
        session.flush()
        nodes.append(node)
        if node_cls == OutlineNodeType.CHAPTER:
            chapter = node
        elif node_cls == OutlineNodeType.SECTION:
            section = node
    return outline, nodes


def _build_scripts(session, teacher_id: int, course_id: int, outline: CourseOutlineVersion, nodes: list[CourseOutlineNode], run_id: str) -> list[TeachingScriptNode]:
    script_version = TeachingScriptVersion(
        course_id=course_id,
        outline_version_id=outline.outline_version_id,
        version=1,
        lifecycle_status=OutlineLifecycleStatus.DRAFT,
        source_parse_run_id=run_id,
        generation_source="demo_seed",
        review_status="pending",
        created_by=teacher_id,
    )
    session.add(script_version)
    session.flush()

    scripts: list[TeachingScriptNode] = []
    for node in nodes:
        if node.node_type != OutlineNodeType.KNOWLEDGE_POINT:
            continue
        pages = _pages(*map(int, node.page_range.split("-"))) if node.page_range else []
        script = TeachingScriptNode(
            script_version_id=script_version.script_version_id,
            course_id=course_id,
            outline_node_id=node.outline_node_id,
            content=SCRIPT_TEMPLATE.format(label=node.title, title=node.title, page_range=node.page_range or "-"),
            style="beginner",
            evidence_refs=_evidence_refs_for_pages(session, course_id, pages),
            source_block_refs=node.source_block_refs,
            content_hash=_hash("script", node.title),
            locked_by=teacher_id if node.locked_by else None,
            locked_at=utcnow_aware() if node.locked_by else None,
        )
        session.add(script)
        session.flush()
        scripts.append(script)
    return scripts


def _build_mappings(session, teacher_id: int, course_id: int, material_version_id: str, nodes: list[CourseOutlineNode]) -> list[CoursePptMapping]:
    mappings: list[CoursePptMapping] = []
    for i, (node_type, title, page_start, page_end, locked, mapped) in enumerate(TREE):
        if node_type != "kp" or not mapped:
            continue
        node = next(n for n in nodes if n.title == title and n.node_type == OutlineNodeType.KNOWLEDGE_POINT)
        refs = _block_refs_for_pages(session, course_id, material_version_id, _pages(page_start, page_end), limit=6)
        mapping = CoursePptMapping(
            course_id=course_id,
            outline_node_id=node.outline_node_id,
            material_version_id=material_version_id,
            page_start=page_start,
            page_end=page_end,
            page_refs=_pages(page_start, page_end),
            confidence=round(0.86 + (i % 5) * 0.02, 2),
            source_block_refs=refs,
            status="draft",
            teacher_locked=locked,  # 锁定节点映射不可被一键匹配覆盖
            created_by=teacher_id,
        )
        session.add(mapping)
        session.flush()
        mappings.append(mapping)
    return mappings


def _seed() -> None:
    force = "--force" in sys.argv
    with session_factory() as session:
        teacher = session.exec(select(User).where(User.username == "TTT")).first()
        if teacher is None:
            print("[seed] 未找到 TTT 用户，请先运行 app.scripts.init_users")
            raise SystemExit(1)

        course = session.exec(select(Course).where(Course.fanya_course_id == COURSE_FANYA_ID)).first()
        if course is None:
            course = session.exec(select(Course).where(Course.id == 1)).first()
        if course is None:
            print("[seed] 未找到课程 1，请先上传材料后再运行本脚本")
            raise SystemExit(1)
        course_id = course.id

        material = session.exec(select(SourceMaterial).where(
            SourceMaterial.course_id == course_id,
            SourceMaterial.material_type == "slide",
        ).order_by(SourceMaterial.id)).first()
        if material is None or not material.current_version_id:
            print(f"[seed] 课程 {course_id} 没有已上传的 PPT 材料，请先在建设页上传")
            raise SystemExit(1)
        version = session.exec(select(SourceMaterialVersion).where(
            SourceMaterialVersion.course_id == course_id,
            SourceMaterialVersion.version_id == material.current_version_id,
        )).first()
        if version is None:
            print(f"[seed] 材料版本 {material.current_version_id} 不存在，请先重新解析")
            raise SystemExit(1)

        existing_outline = session.exec(select(CourseOutlineVersion).where(
            CourseOutlineVersion.course_id == course_id,
        )).first()
        if existing_outline and not force:
            print(f"[seed] 课程 {course_id} 已有目录数据，跳过。加 --force 可重建。")
            return
        if existing_outline:
            _clean_course_data(session, course_id)
            session.commit()
            print(f"[seed] 已清理课程 {course_id} 旧演示数据")

        outline, nodes = _build_outline(
            session, teacher.id, course_id, version.version_id, version.parse_output_ref or None,
        )
        scripts = _build_scripts(session, teacher.id, course_id, outline, nodes, version.parse_output_ref or None)
        mappings = _build_mappings(session, teacher.id, course_id, version.version_id, nodes)

        draft = session.exec(select(CourseBuildDraft).where(CourseBuildDraft.course_id == course_id)).first()
        if draft is None:
            draft = CourseBuildDraft(course_id=course_id, created_by=teacher.id)
            session.add(draft)
        draft.current_step = "mapping"
        draft.overall_status = "in_progress"
        session.add(draft)

        session.commit()
        kp_count = sum(1 for n in nodes if n.node_type == OutlineNodeType.KNOWLEDGE_POINT)
        print(f"[seed] 完成：course_id={course_id} 材料版本={version.version_id}")
        print(f"[seed]   目录节点 {len(nodes)}（章/节/知识点 = 1/{sum(1 for n in nodes if n.node_type == OutlineNodeType.SECTION)}/{kp_count}）")
        print(f"[seed]   讲稿 {len(scripts)} 条；PPT 映射 {len(mappings)} 条（未映射知识点 "
              f"{kp_count - len(mappings)} 个用于演示未映射态）")


if __name__ == "__main__":
    _seed()
