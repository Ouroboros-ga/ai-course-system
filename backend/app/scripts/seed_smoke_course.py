"""
[冒烟审查用] 最小种子：造 1 门课 + 1 条激活脚本 + 3 个节点。
目的：让 /api/v1/player/init/{courseId} 能过 3 个 404 关卡（课程/激活脚本/节点）。
不含视频任务与 PPT 源文件 -> 播放器能初始化，但视频/PPT 区域为空（符合"占位资源"语义）。

幂等：fanya_course_id 固定，已存在则只复用、不重建。

本脚本建立 Course Access v1 基线（OWNER 成员 + 默认能力），并将 SSS 学生
激活为 STUDENT 成员，使访问控制 resolver 不依赖 legacy teacher_id。

用法（在 backend 目录）：
    uv run python -m app.scripts.seed_smoke_course
前置：先跑 uv run python -m app.scripts.init_users  建 TTT/SSS 账号。
审查完可删除本文件，不影响业务代码。
"""
import sys

from sqlmodel import Session, select

from app.models.database import engine
from app.models.course_model import Course, CourseScript, ScriptNode, ScriptNodeType, CourseStatus
from app.models.user_model import User
from app.services.course_access_service import (
    establish_course_access_baseline,
    activate_student_membership,
)

FANYA_ID = "smoke-demo-001"
TITLE = "[冒烟演示] M5C测试课程"


def main():
    with Session(engine) as s:
        teacher = s.exec(select(User).where(User.username == "TTT")).first()
        if not teacher:
            print("[FAIL] 未找到教师账号 TTT。请先运行: uv run python -m app.scripts.init_users")
            sys.exit(1)

        student = s.exec(select(User).where(User.username == "SSS")).first()
        if not student:
            print("[FAIL] 未找到学生账号 SSS。请先运行: uv run python -m app.scripts.init_users")
            sys.exit(1)

        existing = s.exec(select(Course).where(Course.fanya_course_id == FANYA_ID)).first()
        if existing:
            # 补齐历史课程缺失的访问控制基线
            establish_course_access_baseline(s, course_id=existing.id, owner_user_id=teacher.id)
            activate_student_membership(s, course_id=existing.id, student_user_id=student.id)
            s.commit()
            print(f"[SKIP] 演示课程已存在，复用 course_id={existing.id}（已补齐访问控制基线）")
            print(f"       前端访问: http://localhost:5173/player/course/{existing.id}")
            sys.exit(0)

        course = Course(
            fanya_course_id=FANYA_ID,
            fanya_course_name=TITLE,
            title=TITLE,
            teacher_id=teacher.id,
            status=CourseStatus.PUBLISHED,
        )
        s.add(course)
        s.commit()
        s.refresh(course)

        # 建立 Course Access v1 基线：OWNER 成员 + 默认能力
        establish_course_access_baseline(s, course_id=course.id, owner_user_id=teacher.id)
        # 激活 SSS 学生为 STUDENT 成员
        activate_student_membership(s, course_id=course.id, student_user_id=student.id)
        s.commit()

        script = CourseScript(
            course_id=course.id,
            version=1,
            version_name="smoke-v1",
            script_content={"note": "smoke seed", "nodes": 3},
            is_active=True,
            audio_duration=90,
            created_by=teacher.id,
        )
        s.add(script)
        s.commit()
        s.refresh(script)

        seeds = [
            (1, "第一章 导论", 0.0, 30.0, 30, 1, 1),
            (2, "第二章 核心", 30.0, 60.0, 30, 2, 2),
            (3, "第三章 小结", 60.0, 90.0, 30, 3, 3),
        ]
        for idx, title, ts, te, dur, ps, pe in seeds:
            s.add(ScriptNode(
                script_id=script.id,
                node_index=idx,
                node_type=ScriptNodeType.LECTURE,
                title=title,
                content=f"{title} 占位讲解文本，用于冒烟测试 /player/init。",
                page_start=ps,
                page_end=pe,
                timestamp_start=ts,
                timestamp_end=te,
                duration=dur,
            ))
        s.commit()

        course.total_nodes = 3
        course.total_duration = 90
        s.add(course)
        s.commit()

        print("[OK] 已创建演示课程")
        print(f"     course_id  = {course.id}")
        print(f"     script_id  = {script.id} (is_active=True)")
        print(f"     nodes      = 3 (lecture)")
        print(f"     teacher    = TTT (id={teacher.id}, OWNER 成员)")
        print(f"     student    = SSS (id={student.id}, STUDENT 成员)")
        print()
        print(f"==> 前端访问: http://localhost:5173/player/course/{course.id}")
        print(f"==> 后端直测: curl -H \"Authorization: Bearer <TOKEN>\" http://localhost:8000/api/v1/player/init/{course.id}")


if __name__ == "__main__":
    main()
