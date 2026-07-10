"""Prepare deterministic M7 fallback accounts and course data.

The CLI refuses the production-default database unless the operator explicitly
passes --allow-default-database. It never calls external services.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from sqlmodel import Session, select

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings  # noqa: E402
from app.core.security import get_password_hash  # noqa: E402
from app.models.course_model import (  # noqa: E402
    Course,
    CourseScript,
    CourseStatus,
    DoclingDocument,
    DoclingText,
    ParseStatus,
    ScriptNode,
    ScriptNodeType,
)
from app.models.database import (  # noqa: E402
    DATABASE_URL,
    DEFAULT_DATABASE_URL,
    create_tables,
    engine,
)
from app.models.mapping_model import KnowledgePageMap  # noqa: E402
from app.models.user_model import User, UserRole  # noqa: E402
from app.models.video_generation_model import (  # noqa: E402
    GenerationStatus,
    VideoGenerationTask,
)

TEACHER_USERNAME = "DemoTeacher"
STUDENT_USERNAME = "DemoStudent"
DEFAULT_PASSWORD = "Demo123456"
DEMO_COURSE_KEY = "m7-demo-fallback"


def _upsert_user(session: Session, username: str, role: UserRole, password: str) -> User:
    user = session.exec(select(User).where(User.username == username)).first()
    if user is None:
        user = User(
            username=username,
            real_name="M7 Demo Teacher" if role == UserRole.TEACHER else "M7 Demo Student",
            email=f"{username.lower()}@demo.invalid",
            hashed_password=get_password_hash(password),
            role=role,
            is_active=True,
            school_id="m7-demo-school",
        )
    else:
        user.hashed_password = get_password_hash(password)
        user.role = role
        user.is_active = True
        user.school_id = user.school_id or "m7-demo-school"
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _ensure_course(session: Session, teacher: User) -> Course:
    sample_path = PROJECT_ROOT / "docs" / "phase1" / "demo" / "M7演示课件.md"
    course = session.exec(
        select(Course).where(Course.fanya_course_id == DEMO_COURSE_KEY)
    ).first()
    if course is None:
        course = Course(
            fanya_course_id=DEMO_COURSE_KEY,
            fanya_course_name="M7 决赛演示课程",
            title="M7 决赛演示：二分查找与递归",
            description="离线兜底课程；用于服务降级时继续演示教学主流程。",
            teacher_id=teacher.id,
            status=CourseStatus.PUBLISHED,
            is_ai_generated=True,
            total_duration=120,
            total_nodes=2,
            source_file_name=sample_path.name,
            source_file_path=str(sample_path),
            source_mimetype="text/markdown",
            total_pages=2,
        )
    else:
        course.teacher_id = teacher.id
        course.status = CourseStatus.PUBLISHED
        course.source_file_path = str(sample_path)
        course.total_nodes = 2
        course.total_duration = 120
    session.add(course)
    session.commit()
    session.refresh(course)
    return course


def _ensure_document(session: Session, course: Course) -> DoclingDocument:
    document = session.exec(
        select(DoclingDocument).where(DoclingDocument.course_id == course.id)
    ).first()
    if document is None:
        document = DoclingDocument(
            course_id=course.id,
            doc_name="M7演示课件.md",
            origin_filename="M7演示课件.md",
            origin_mimetype="text/markdown",
            source_file_path=course.source_file_path,
            status=ParseStatus.COMPLETED,
            total_texts=2,
            raw_json={"source": "M7 deterministic fallback seed"},
        )
        session.add(document)
        session.commit()
        session.refresh(document)

    texts = session.exec(select(DoclingText).where(DoclingText.doc_id == document.id)).all()
    if not texts:
        for index, text_value in enumerate(
            [
                "二分查找通过比较中点把有序搜索区间缩小一半。",
                "递归必须定义基本情况，并在每次调用时缩小问题规模。",
            ]
        ):
            session.add(
                DoclingText(
                    doc_id=document.id,
                    self_ref=f"#/texts/{index}",
                    label="text",
                    text=text_value,
                    page_no=index + 1,
                    sort_order=index,
                )
            )
        session.commit()
    return document


def _ensure_script_and_nodes(
    session: Session,
    course: Course,
    teacher: User,
) -> tuple[CourseScript, list[ScriptNode]]:
    script = session.exec(
        select(CourseScript).where(
            CourseScript.course_id == course.id,
            CourseScript.is_active == True,
        )
    ).first()
    if script is None:
        script = CourseScript(
            course_id=course.id,
            version=1,
            version_name="M7 fallback v1",
            script_content={
                "title": course.title,
                "nodes": ["二分查找", "递归与基本情况"],
            },
            summary_text="从问题分解理解二分查找和递归。",
            keywords=json.dumps(["二分查找", "递归", "基本情况"], ensure_ascii=False),
            is_active=True,
            created_by=teacher.id,
        )
        session.add(script)
        session.commit()
        session.refresh(script)

    nodes = list(
        session.exec(
            select(ScriptNode)
            .where(ScriptNode.script_id == script.id)
            .order_by(ScriptNode.node_index)
        ).all()
    )
    if not nodes:
        node_specs = [
            (
                "m7_binary_search",
                "二分查找",
                "二分查找适用于有序序列。比较区间中点后，只保留可能包含目标值的一半区间。",
            ),
            (
                "m7_recursion",
                "递归与基本情况",
                "递归通过调用自身处理更小的同类问题。基本情况负责终止调用并返回可组合的结果。",
            ),
        ]
        for index, (chapter_id, title, content) in enumerate(node_specs):
            node = ScriptNode(
                script_id=script.id,
                chapter_id=chapter_id,
                node_index=index,
                node_type=ScriptNodeType.LECTURE,
                title=title,
                content=content,
                page_start=index + 1,
                page_end=index + 1,
                timestamp_start=index * 60.0,
                timestamp_end=(index + 1) * 60.0,
                duration=60,
                is_key_point=True,
            )
            session.add(node)
        session.commit()
        nodes = list(
            session.exec(
                select(ScriptNode)
                .where(ScriptNode.script_id == script.id)
                .order_by(ScriptNode.node_index)
            ).all()
        )

    for node in nodes:
        mapping = session.exec(
            select(KnowledgePageMap).where(KnowledgePageMap.node_id == node.id)
        ).first()
        if mapping is None:
            session.add(
                KnowledgePageMap(
                    course_id=course.id,
                    script_id=script.id,
                    node_id=node.id,
                    page_start=node.page_start,
                    page_end=node.page_end,
                    confidence=1.0,
                    is_manual=True,
                )
            )
    session.commit()
    return script, nodes


def _install_video_fallback(
    session: Session,
    course: Course,
    script: CourseScript,
    nodes: list[ScriptNode],
    video_path: Path,
) -> Path:
    source = video_path.resolve()
    if not source.is_file() or source.suffix.lower() != ".mp4":
        raise ValueError("--video-path must point to an existing .mp4 file")

    configured_root = Path(settings.VIDEO_STORAGE_PATH)
    video_root = configured_root if configured_root.is_absolute() else PROJECT_ROOT / configured_root
    video_root.mkdir(parents=True, exist_ok=True)
    target = video_root / "m7_demo_fallback.mp4"
    if source != target.resolve():
        shutil.copy2(source, target)

    for node in nodes:
        task = session.exec(
            select(VideoGenerationTask).where(VideoGenerationTask.node_id == node.id)
        ).first()
        if task is None:
            task = VideoGenerationTask(
                course_id=course.id,
                script_id=script.id,
                node_id=node.id,
            )
        task.status = GenerationStatus.COMPLETED
        task.dh_video_path = str(target)
        task.dh_generation_time = "pre-generated"
        task.error_message = None
        session.add(task)
    session.commit()
    return target


def prepare_demo_data(
    session: Session,
    password: str = DEFAULT_PASSWORD,
    video_path: Path | None = None,
) -> dict:
    teacher = _upsert_user(session, TEACHER_USERNAME, UserRole.TEACHER, password)
    student = _upsert_user(session, STUDENT_USERNAME, UserRole.STUDENT, password)
    course = _ensure_course(session, teacher)
    _ensure_document(session, course)
    script, nodes = _ensure_script_and_nodes(session, course, teacher)

    installed_video = None
    if video_path is not None:
        installed_video = _install_video_fallback(
            session,
            course,
            script,
            nodes,
            video_path,
        )

    return {
        "database_url": DATABASE_URL,
        "teacher": {"username": teacher.username, "password": password},
        "student": {"username": student.username, "password": password},
        "course_id": course.id,
        "course_title": course.title,
        "script_id": script.id,
        "node_ids": [node.id for node in nodes],
        "video_fallback": str(installed_video) if installed_video else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare isolated M7 demo data")
    parser.add_argument(
        "--allow-default-database",
        action="store_true",
        help="Explicitly allow writing the normal smart_class.db database",
    )
    parser.add_argument("--video-path", type=Path, help="Existing pre-generated MP4")
    args = parser.parse_args()

    if DATABASE_URL == DEFAULT_DATABASE_URL and not args.allow_default_database:
        print(
            "Refusing to write the production-default database. "
            "Set AI_COURSE_DATABASE_URL to an isolated demo DB or pass "
            "--allow-default-database explicitly.",
            file=sys.stderr,
        )
        return 2

    if DATABASE_URL.startswith("sqlite:///"):
        db_path = Path(DATABASE_URL.removeprefix("sqlite:///"))
        if not db_path.is_absolute():
            db_path = PROJECT_ROOT / db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)

    create_tables()
    password = os.environ.get("M7_DEMO_PASSWORD", DEFAULT_PASSWORD)
    with Session(engine) as session:
        result = prepare_demo_data(session, password=password, video_path=args.video_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
