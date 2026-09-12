"""只读巡检：课程15学习分析管道所需数据现状。

用途：定位"教师学习分析界面看不到数据"的根因，核对回填前状态。
不写任何数据。
"""
from __future__ import annotations

import os
import sys

ENV_FILES = [
    "/opt/smartcarb/shared/env/backend.env",
    "/opt/smartcarb/shared/env/database.env",
    "/opt/smartcarb/shared/env/runtime-paths.env",
]
for _env_file in ENV_FILES:
    if not os.path.exists(_env_file):
        continue
    with open(_env_file, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip().strip('"').strip("'")

BACKEND_DIR = "/opt/smartcarb/current/backend"
sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import func, text  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from app.models.database import engine  # noqa: E402
from app.models.course_build_model import CourseRelease  # noqa: E402
from app.models.course_outline_model import CourseOutlineNode, OutlineNodeType  # noqa: E402
from app.models.access_control_model import CourseMembership  # noqa: E402
from app.models.unified_learning_model import (  # noqa: E402
    StudentLearningProjection,
    CourseLearningStatsProjection,
)
from app.models.user_model import User  # noqa: E402

COURSE_ID = 15


def section(title: str) -> None:
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


with Session(engine) as s:
    section("1. 课程15的发布记录（course_releases）")
    for r in s.exec(select(CourseRelease).where(CourseRelease.course_id == COURSE_ID).order_by(CourseRelease.version)).all():
        print(f"  release_id={r.release_id}  version={r.version}  status={r.status.value}  "
              f"is_active={r.is_active}  outline_version_id={r.outline_version_id}")

    section("2. 活跃发布的大纲知识点节点（outline nodes, knowledge_point only）")
    rel = s.exec(select(CourseRelease).where(
        CourseRelease.course_id == COURSE_ID,
        CourseRelease.status.in_([__import__('app.models.course_build_model', fromlist=['ReleaseStatus']).ReleaseStatus.PUBLISHED]),
        CourseRelease.is_active == True,
    )).first()
    if rel is None:
        print("  [无活跃发布]")
    else:
        print(f"  活跃 release_id={rel.release_id}  outline_version_id={rel.outline_version_id}")
        nodes = s.exec(select(CourseOutlineNode).where(
            CourseOutlineNode.outline_version_id == rel.outline_version_id,
            CourseOutlineNode.node_type == OutlineNodeType.KNOWLEDGE_POINT,
        ).order_by(CourseOutlineNode.order_index, CourseOutlineNode.outline_node_id)).all()
        print(f"  知识点节点数 = {len(nodes)}")
        for n in nodes[:15]:
            print(f"    on_id={n.outline_node_id}  order={n.order_index}  kg_node_id={n.knowledge_graph_node_id}  title={n.title[:30]}")
        if len(nodes) > 15:
            print(f"    ... 共 {len(nodes)} 个")

    section("3. Demo 学生账号（user.id / username）")
    rows = s.exec(select(User.id, User.username).where(User.username.like("0417%") | User.username.like("0418%"))).all()
    demo = [(r[0], r[1]) for r in rows if len(r[1]) == 10 and r[1][:4] in ("0417", "0418")]
    print(f"  demo 学生数 = {len(demo)}")
    for uid, uname in demo[:10]:
        print(f"    user_id={uid}  username={uname}")
    if len(demo) > 10:
        print(f"    ... 共 {len(demo)} 人")

    section("4. 学习分析管道现状（course_id=15）")
    mem = s.exec(select(func.count()).select_from(CourseMembership).where(CourseMembership.course_id == COURSE_ID)).one()
    mem_student = s.exec(select(func.count()).select_from(CourseMembership).where(
        CourseMembership.course_id == COURSE_ID,
        CourseMembership.role == "student",
    )).one()
    proj = s.exec(select(func.count()).select_from(StudentLearningProjection).where(StudentLearningProjection.course_id == COURSE_ID)).one()
    stats = s.exec(select(func.count()).select_from(CourseLearningStatsProjection).where(CourseLearningStatsProjection.course_id == COURSE_ID)).one()
    print(f"  course_memberships 总数 = {mem}  其中 role=student = {mem_student}")
    print(f"  student_learning_projections = {proj}")
    print(f"  course_learning_stats_projections = {stats}")

    section("5. 现有 memberships 明细")
    for m in s.exec(select(CourseMembership).where(CourseMembership.course_id == COURSE_ID)).all():
        print(f"  user_id={m.user_id}  role={m.role.value}  status={m.status.value}  excluded={m.analytics_excluded}")
