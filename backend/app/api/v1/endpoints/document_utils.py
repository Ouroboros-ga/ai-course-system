"""
文档处理 API 共享工具模块
包含常量、辅助函数、共享状态
"""

import os
import tempfile
import logging
from pathlib import Path

from fastapi import HTTPException
from sqlmodel import Session, select
from app.schemas.common_schema import UnifiedResponse
from app.core.exceptions import unified_response
from app.models.course_model import Course, ScriptNode, StudentEnrollment
from app.services.document_service import document_service

logger = logging.getLogger(__name__)

# --------------------------
# 目录常量
# --------------------------
UPLOAD_DIR = Path(tempfile.gettempdir()) / "ai_course_uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

PPT_SLIDES_DIR = Path(tempfile.gettempdir()) / "ai_course_ppt_slides"
PPT_SLIDES_DIR.mkdir(exist_ok=True)

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
AUDIO_STORAGE_DIR = BASE_DIR / "audio_storage"
AUDIO_STORAGE_DIR.mkdir(exist_ok=True)

# --------------------------
# 共享状态（TTS 进度追踪）
# --------------------------
tts_generation_status: dict = {}
document_cache: dict = {}


def get_course_audio_dir(course_id: int) -> Path:
    """获取课程音频存储目录"""
    course_dir = AUDIO_STORAGE_DIR / str(course_id)
    course_dir.mkdir(parents=True, exist_ok=True)
    return course_dir


def cleanup_old_node_audio(node: ScriptNode, course_dir: Path):
    """清理节点旧音频文件"""
    if node.audio_url:
        old_filename = node.audio_url.split("/")[-1]
        if old_filename:
            old_path = course_dir / old_filename
            if old_path.exists():
                try:
                    old_path.unlink()
                    logger.info(f"Cleaned up old audio for node {node.id}: {old_filename}")
                except OSError as e:
                    logger.warning(f"Failed to delete old audio {old_path}: {e}")


async def _background_synthesize_audio(course_id: int, script_id: int):
    """后台异步合成所有节点音频"""
    import asyncio
    from app.models.database import engine
    from sqlmodel import Session as _Session

    status_key = str(course_id)
    tts_generation_status[status_key] = {
        "status": "processing",
        "total": 0,
        "completed": 0,
        "errors": [],
    }

    try:
        with _Session(engine) as session:
            nodes = session.exec(
                select(ScriptNode)
                .where(ScriptNode.script_id == script_id)
                .order_by(ScriptNode.node_index)
            ).all()

            course_audio_dir = get_course_audio_dir(course_id)
            total = len([n for n in nodes if n.content and len(n.content.strip()) >= 10])
            tts_generation_status[status_key]["total"] = total
            completed = 0

            for node in nodes:
                if not node.content or len(node.content.strip()) < 10:
                    continue

                try:
                    from app.common.tts_client import tts_client

                    cleanup_old_node_audio(node, course_audio_dir)

                    content = node.content.strip()
                    if len(content) > 2000:
                        segments = []
                        current = ""
                        for char in content:
                            current += char
                            if char in "。！？；" and len(current) >= 500:
                                segments.append(current)
                                current = ""
                        if current:
                            segments.append(current)
                    else:
                        segments = [content]

                    all_audio = b""
                    for seg in segments:
                        result = await tts_client.synthesize(seg, voice="zh_female_wanwanxiaohe_moon_bigtts", format="mp3")
                        if result and result.get("audio_data"):
                            all_audio += result["audio_data"]

                    if all_audio:
                        audio_filename = f"node_{node.id}_{uuid.uuid4().hex[:8]}.mp3"
                        audio_path = course_audio_dir / audio_filename
                        with open(audio_path, "wb") as f:
                            f.write(all_audio)

                        relative_path = f"audio_storage/{course_id}/{audio_filename}"
                        node.audio_url = relative_path
                        session.add(node)

                    completed += 1
                    tts_generation_status[status_key]["completed"] = completed

                except Exception as e:
                    tts_generation_status[status_key]["errors"].append(str(e))
                    logger.error(f"TTS failed for node {node.id}: {e}")

            session.commit()
            tts_generation_status[status_key]["status"] = "completed"
            logger.info(f"TTS synthesis complete for course {course_id}")

    except Exception as e:
        tts_generation_status[status_key]["status"] = "error"
        tts_generation_status[status_key]["errors"].append(str(e))
        logger.error(f"TTS background task failed for course {course_id}: {e}")


def verify_course_owner(session: Session, course_id: int, user_id: int) -> Course:
    """验证课程归属权，返回课程对象或抛出异常"""
    course = session.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="课程不存在")
    if str(course.teacher_id) != str(user_id):
        raise HTTPException(status_code=403, detail="无权操作此课程")
    return course


def get_enrolled_course(session: Session, course_id: int, user_id: int) -> Course:
    """验证用户已选课并返回课程对象"""
    enrollment = session.exec(
        select(StudentEnrollment).where(
            StudentEnrollment.course_id == course_id,
            StudentEnrollment.student_id == user_id,
        )
    ).first()
    if not enrollment:
        raise HTTPException(status_code=403, detail="您尚未选修此课程")
    course = session.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="课程不存在")
    return course
