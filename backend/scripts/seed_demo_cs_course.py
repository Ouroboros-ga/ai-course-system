"""本地 Demo 样例数据：计算机学科课程「数据结构与算法基础」学习侧闭环。

该脚本仅写合成/假名化数据，不包含真实学生数据（AGENTS.md §4.1）。

目标：让学生账号能打开 /app/course/:id/learn 学习（纯文本讲稿），并验证
课程学习部分的提问（TeachingAgent / V1 /chat/ask）功能。

覆盖一个完整可学习的课程所需的最小闭环：
  Course(已发布) + CourseOutlineVersion/Node(章/节/知识点) +
  TeachingScriptVersion/Node(纯文本讲稿) + CourseKnowledgeNode(稳定节点身份) +
  CourseCapability(learning/cognitive_analysis/...) + CourseMembership(教师/学生) +
  CourseRelease(status=published, is_active=True)  <-- 学生侧内容选择器

用法：uv run python -m scripts.seed_demo_cs_course [--force]
注意：本脚本直接写入 CourseRelease（绕过质量门禁），仅供本地体验看效果。
"""
from __future__ import annotations

import sys
import uuid

from sqlmodel import select

from app.core.time_utils import utcnow_aware
from app.models.access_control_model import (
    CourseCapability,
    CourseMembership,
    CourseRole,
    MembershipStatus,
)
from app.models.course_build_model import CourseRelease, ReleaseStatus
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
from app.models.graph_production_model import CourseKnowledgeNode, CourseKnowledgeNodeStatus
from app.models.user_model import User

DEMO_FANYA_ID = "demo_cs_data_structures_algorithms_20260905"

# 目录树：(node_type, title, knowledge_key, 讲稿内容)
# knowledge_key == CourseKnowledgeNode.node_key，供学习轨迹/六维认知身份解析。
TREE = [
    ("chapter", "数据结构与算法基础", None),
    ("section", "第一章 线性结构", None),
    ("kp", "数组与链表", "kn_cs_array_linked"),
    ("kp", "栈与队列", "kn_cs_stack_queue"),
    ("section", "第二章 查找与排序", None),
    ("kp", "哈希表", "kn_cs_hash_table"),
    ("kp", "快速排序", "kn_cs_quick_sort"),
    ("section", "第三章 图论基础", None),
    ("kp", "图的遍历（BFS 与 DFS）", "kn_cs_graph_traverse"),
    ("kp", "最短路径（Dijkstra）", "kn_cs_shortest_path"),
]

SCRIPT_MAP = {
    "kn_cs_array_linked": (
        "数组与链表是两种最基础的线性存储结构。数组在内存中连续存放，"
        "支持 O(1) 的随机访问，但插入和删除需要搬移元素，平均为 O(n)。"
        "链表通过指针把分散的结点串联起来，插入和删除只需要修改指针，为 O(1)，"
        "但不支持随机访问，查找为 O(n)。实际工程中常根据读写比例选择结构。"
    ),
    "kn_cs_stack_queue": (
        "栈（Stack）是后进先出（LIFO）的线性结构，只能在栈顶插入和删除，"
        "常用于函数调用、表达式求值、括号匹配。队列（Queue）是先进先出（FIFO）"
        "的线性结构，一端入队、另一端出队，常用于广度优先搜索、消息队列。"
    ),
    "kn_cs_hash_table": (
        "哈希表通过哈希函数把键映射到数组下标，实现平均 O(1) 的查找。"
        "冲突用链地址法或开放定址法解决。装填因子越大冲突越多，"
        "实践中会通过扩容与再哈希保持常数级复杂度。"
    ),
    "kn_cs_quick_sort": (
        "快速排序采用分治法：选取基准元素，把序列划分成小于基准和大于基准两部分，"
        "再递归地排序。平均时间复杂度 O(n log n)，最坏 O(n^2)，"
        "是不稳定的排序算法，适合大规模数据。"
    ),
    "kn_cs_graph_traverse": (
        "图的遍历有广度优先（BFS）和深度优先（DFS）两种。BFS 借助队列逐层扩展，"
        "能找到无权图的最短路径；DFS 借助栈或递归深入一个分支，"
        "常用于连通性判断与拓扑排序。两者都需要 visited 标记防止重复访问。"
    ),
    "kn_cs_shortest_path": (
        "Dijkstra 算法求解带非负权重的单源最短路径。它维护一个到源点的距离集合，"
        "每次从未确定顶点中选出距离最小者并松弛其邻边。复杂度可用优先队列优化"
        "到 O((V+E) log V)，不能处理负权边（负权需用 Bellman-Ford）。"
    ),
}


def _seed() -> None:
    force = "--force" in sys.argv
    with session_factory() as session:
        teacher = session.exec(select(User).where(User.username == "TTT")).first()
        if teacher is None:
            print("[seed] 未找到 TTT 用户，请先运行 app.scripts.init_users")
            raise SystemExit(1)
        students = session.exec(
            select(User).where(User.username.in_(["demo_student", "demo_xh202620"]))
        ).all()

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
            for row in session.exec(select(CourseKnowledgeNode).where(CourseKnowledgeNode.course_id == course_id)):
                session.delete(row)
            for row in session.exec(select(CourseRelease).where(CourseRelease.course_id == course_id)):
                session.delete(row)
            for row in session.exec(select(CourseMembership).where(CourseMembership.course_id == course_id)):
                session.delete(row)
            for row in session.exec(select(CourseCapability).where(CourseCapability.course_id == course_id)):
                session.delete(row)
            session.delete(existing)
            session.commit()
            print(f"[seed] 已清理旧样例课程 course_id={course_id}")

        course = Course(
            fanya_course_id=DEMO_FANYA_ID,
            fanya_course_name="数据结构与算法基础（本地样例）",
            title="数据结构与算法基础",
            description="本地 Demo 计算机学科课程：纯文本讲稿，用于验证学习页面与提问功能。",
            teacher_id=teacher.id,
            status=CourseStatus.PUBLISHED,
            is_ai_generated=True,
            total_duration=0,
            total_nodes=sum(1 for n in TREE if n[0] == "kp"),
            source_file_name="data_structures_and_algorithms.txt",
            total_pages=12,
        )
        session.add(course)
        session.flush()

        outline = CourseOutlineVersion(
            course_id=course.id,
            version=1,
            lifecycle_status=OutlineLifecycleStatus.PUBLISHED,
            generation_source="demo_seed_cs",
            review_status="approved",
            created_by=teacher.id,
        )
        session.add(outline)
        session.flush()

        # 建树
        chapter: CourseOutlineNode | None = None
        section: CourseOutlineNode | None = None
        order: dict[tuple[str | None, str], int] = {}
        kp_nodes: list[CourseOutlineNode] = []
        for node_type, title, knowledge_key in TREE:
            if node_type == "chapter":
                cls, parent = OutlineNodeType.CHAPTER, None
            elif node_type == "section":
                cls, parent = OutlineNodeType.SECTION, chapter
            else:
                cls, parent = OutlineNodeType.KNOWLEDGE_POINT, section
            key = (parent.outline_node_id if parent else None, cls.value)
            order[key] = order.get(key, 0) + 1
            node = CourseOutlineNode(
                outline_version_id=outline.outline_version_id,
                course_id=course.id,
                parent_node_id=parent.outline_node_id if parent else None,
                node_type=cls,
                title=title,
                order_index=order[key],
                knowledge_graph_node_id=knowledge_key,
                source_block_refs=([] if knowledge_key is None else [f"ev_{uuid.uuid4().hex[:10]}"]),
                page_range="1-12",
                generation_reason="demo_seed_cs",
                confidence=0.97,
                content_hash=f"cs_seed_{uuid.uuid4().hex}",
            )
            session.add(node)
            session.flush()
            if cls == OutlineNodeType.CHAPTER:
                chapter = node
            elif cls == OutlineNodeType.SECTION:
                section = node
            else:
                kp_nodes.append(node)

        # 讲稿版本（纯文本）
        script_version = TeachingScriptVersion(
            course_id=course.id,
            outline_version_id=outline.outline_version_id,
            version=1,
            lifecycle_status=OutlineLifecycleStatus.PUBLISHED,
            generation_source="demo_seed_cs",
            review_status="approved",
            created_by=teacher.id,
        )
        session.add(script_version)
        session.flush()
        for node in kp_nodes:
            content = SCRIPT_MAP.get(node.knowledge_graph_node_id, "")
            session.add(TeachingScriptNode(
                script_version_id=script_version.script_version_id,
                course_id=course.id,
                outline_node_id=node.outline_node_id,
                content=content,
                style="beginner",
                evidence_refs=[f"ev_{uuid.uuid4().hex[:12]}"],
                source_block_refs=node.source_block_refs,
                content_hash=f"cs_script_{uuid.uuid4().hex}",
            ))

        # 稳定知识节点身份（供六维认知/学习轨迹解析）
        for node in kp_nodes:
            session.add(CourseKnowledgeNode(
                course_id=course.id,
                node_key=node.knowledge_graph_node_id,
                title=node.title,
                kind="concept",
                status=CourseKnowledgeNodeStatus.PUBLISHED,
                source_anchor_ids=[],
                extra_data={"demo_seed": True},
            ))

        # 能力开关
        session.add(CourseCapability(
            course_id=course.id,
            learning=True,
            course_building=True,
            knowledge_graph=True,
            evidence=True,
            experiment=False,
            coding_sandbox=False,
            cognitive_analysis=True,   # 提问功能走 TeachingAgent 的能力开关
            safety_policy=True,
        ))

        # 成员：教师 + 学生
        session.add(CourseMembership(
            course_id=course.id, user_id=teacher.id,
            role=CourseRole.OWNER, status=MembershipStatus.ACTIVE,
            analytics_excluded=True,
        ))
        for student in students:
            session.add(CourseMembership(
                course_id=course.id, user_id=student.id,
                role=CourseRole.STUDENT, status=MembershipStatus.ACTIVE,
                analytics_excluded=False,
            ))

        # 发布（学生侧内容选择器）
        release = CourseRelease(
            course_id=course.id,
            version=1,
            status=ReleaseStatus.PUBLISHED,
            is_active=True,
            structure_snapshot={"outline_version_id": outline.outline_version_id},
            scripts_snapshot={"script_version_id": script_version.script_version_id},
            page_mappings_snapshot={},
            media_snapshot={},
            outline_version_id=outline.outline_version_id,
            script_version_id=script_version.script_version_id,
            label="数据结构与算法基础 v1（本地样例）",
            release_notes="本地 Demo 学习侧闭环",
            quality_gate_passed=True,
            published_by=teacher.id,
            published_at=utcnow_aware(),
            created_by=teacher.id,
        )
        session.add(release)

        session.commit()
        print(f"[seed] 完成：course_id={course.id} 章/节/知识点 = "
              f"{sum(1 for n in TREE if n[0]=='chapter')}/"
              f"{sum(1 for n in TREE if n[0]=='section')}/{len(kp_nodes)}")
        print(f"[seed] 课程已发布（status=PUBLISHED, release 已激活），学生可打开学习")
        print(f"[seed] 成员：教师={teacher.id} 学生={[s.id for s in students]}")


if __name__ == "__main__":
    _seed()
