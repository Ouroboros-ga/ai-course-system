"""
视频生成服务
F5核心管线：脚本节点 → TTS合成语音 → 数字人视频生成

流程：
  1. 读取脚本节点的讲解文本和素材配置
  2. TTS合成语音（支持预置音色和克隆音色）
  3. 保存音频到本地
  4. 调用数字人API（音频+人脸视频→数字人视频）
  5. 保存视频路径到VideoGenerationTask
"""

import logging
import os
import uuid
from pathlib import Path
from typing import Optional
from datetime import datetime

from sqlmodel import Session, select

from app.core.config import settings
from app.models.course_model import Course, CourseScript, ScriptNode
from app.models.asset_model import TeacherAsset, AssetType
from app.models.video_generation_model import VideoGenerationTask, GenerationStatus
from app.common.tts_client import tts_client, TTSError
from app.common.digital_human_client import digital_human_client, DigitalHumanError
from app.platform.adapters.digital_human import DigitalHumanAdapter
from app.platform.adapters.errors import AdapterErrorCode
from app.platform.adapters.tts import TTSAdapter

logger = logging.getLogger(__name__)

# 视频生成输出目录
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
GENERATED_ROOT = BASE_DIR / settings.VIDEO_STORAGE_PATH / "generated"
AUDIO_ROOT = BASE_DIR / settings.VIDEO_STORAGE_PATH / "audio"


def _ensure_dirs():
    """确保输出目录存在"""
    GENERATED_ROOT.mkdir(parents=True, exist_ok=True)
    AUDIO_ROOT.mkdir(parents=True, exist_ok=True)


class VideoGenerationService:
    """视频生成服务"""

    async def generate_node_video(
        self,
        node_id: int,
        session: Session,
        force: bool = False,
    ) -> VideoGenerationTask:
        """
        为单个脚本节点生成数字人视频

        Args:
            node_id: 脚本节点ID
            session: 数据库会话
            force: 是否强制重新生成（忽略已有结果）

        Returns:
            VideoGenerationTask 生成任务记录
        """
        _ensure_dirs()

        # 1. 查询节点
        node = session.get(ScriptNode, node_id)
        if not node:
            raise ValueError(f"脚本节点不存在: {node_id}")

        # 2. 查询脚本和课程
        script = session.get(CourseScript, node.script_id)
        if not script:
            raise ValueError(f"脚本不存在: {node.script_id}")

        course_id = script.course_id

        # 3. 检查是否已有生成任务
        existing_task = session.exec(
            select(VideoGenerationTask).where(
                VideoGenerationTask.node_id == node_id
            )
        ).first()

        if existing_task and existing_task.status == GenerationStatus.COMPLETED and not force:
            logger.info(f"[视频生成] 节点{node_id}已有完成的生成任务，跳过")
            return existing_task

        # 4. 创建或更新生成任务
        if existing_task:
            task = existing_task
            task.status = GenerationStatus.PENDING
            task.error_message = None
            task.retry_count += 1
        else:
            task = VideoGenerationTask(
                course_id=course_id,
                script_id=node.script_id,
                node_id=node_id,
            )
        task.updated_at = datetime.utcnow()
        session.add(task)
        session.commit()
        session.refresh(task)

        # 5. 解析节点素材配置
        extra_data = node.extra_data or {}
        voice = extra_data.get("voice")
        face_video_asset_id = extra_data.get("face_video_asset_id")

        # 6. 获取人脸视频路径
        face_video_path = await self._resolve_face_video(
            face_video_asset_id, node, session
        )

        # 7. TTS合成语音
        task.status = GenerationStatus.TTS_SYNTHESIZING
        task.voice = voice
        task.face_video_asset_id = face_video_asset_id
        task.updated_at = datetime.utcnow()
        session.add(task)
        session.commit()

        try:
            audio_path = await self._synthesize_tts(node, voice, task, session)
        except TTSError as e:
            task.status = GenerationStatus.FAILED
            task.error_message = f"TTS合成失败: {str(e)}"
            task.updated_at = datetime.utcnow()
            session.add(task)
            session.commit()
            raise

        # 8. 数字人视频生成
        task.status = GenerationStatus.DH_GENERATING
        task.updated_at = datetime.utcnow()
        session.add(task)
        session.commit()

        try:
            dh_result = await DigitalHumanAdapter(digital_human_client).generate_video(
                audio_path=audio_path,
                video_path=face_video_path,
            )
            if not dh_result.success:
                task.status = GenerationStatus.FAILED
                task.error_message = f"Digital human generation failed: {dh_result.error_message}"
                task.updated_at = datetime.utcnow()
                session.add(task)
                session.commit()
                session.refresh(task)
                if dh_result.error_code == AdapterErrorCode.BUSINESS_FAILURE.value:
                    return task
                raise DigitalHumanError(dh_result.error_message or "Digital human generation failed")

            dh_response = dh_result.data
            dh_status = getattr(dh_response, "status", None)
            dh_error = getattr(dh_response, "error", None) or getattr(dh_response, "message", None)
            if dh_status and str(dh_status).lower() not in {"success", "succeeded", "done", "completed"}:
                task.status = GenerationStatus.FAILED
                task.error_message = f"Digital human generation failed: {dh_error or dh_status}"
                task.updated_at = datetime.utcnow()
                session.add(task)
                session.commit()
                session.refresh(task)
                return task
            if not getattr(dh_response, "video_path", None):
                task.status = GenerationStatus.FAILED
                task.error_message = f"Digital human generation failed: {dh_error or 'video_path is empty'}"
                task.updated_at = datetime.utcnow()
                session.add(task)
                session.commit()
                session.refresh(task)
                return task
            task.dh_video_path = dh_response.video_path
            task.dh_generation_time = dh_response.generation_time
        except DigitalHumanError as e:
            task.status = GenerationStatus.FAILED
            task.error_message = f"Digital human generation failed: {str(e)}"
            task.updated_at = datetime.utcnow()
            session.add(task)
            session.commit()
            raise
        except Exception as e:
            task.status = GenerationStatus.FAILED
            task.error_message = f"Digital human generation failed: {str(e)}"
            task.updated_at = datetime.utcnow()
            session.add(task)
            session.commit()
            raise
        # 9. 完成
        task.status = GenerationStatus.COMPLETED
        task.updated_at = datetime.utcnow()
        session.add(task)
        session.commit()
        session.refresh(task)

        logger.info(
            f"[视频生成] 节点{node_id}生成完成: "
            f"audio={task.audio_path}, video={task.dh_video_path}"
        )
        return task

    async def generate_course_videos(
        self,
        course_id: int,
        session: Session,
        node_ids: Optional[list[int]] = None,
        force: bool = False,
    ) -> list[VideoGenerationTask]:
        """
        为课程批量生成视频

        Args:
            course_id: 课程ID
            session: 数据库会话
            node_ids: 指定节点ID列表（为空则生成全部）
            force: 是否强制重新生成

        Returns:
            生成任务列表
        """
        # 查询激活脚本
        script = session.exec(
            select(CourseScript).where(
                CourseScript.course_id == course_id,
                CourseScript.is_active == True,
            )
        ).first()
        if not script:
            raise ValueError(f"课程{course_id}没有激活的脚本")

        # 查询节点
        query = select(ScriptNode).where(
            ScriptNode.script_id == script.id
        ).order_by(ScriptNode.node_index)

        if node_ids:
            query = query.where(ScriptNode.id.in_(node_ids))

        nodes = session.exec(query).all()
        if not nodes:
            raise ValueError(f"课程{course_id}没有可生成的脚本节点")

        logger.info(f"[视频生成] 开始批量生成: 课程{course_id}, {len(nodes)}个节点")

        tasks = []
        for node in nodes:
            try:
                task = await self.generate_node_video(
                    node_id=node.id,
                    session=session,
                    force=force,
                )
                tasks.append(task)
            except Exception as e:
                logger.error(f"[视频生成] 节点{node.id}生成失败: {e}")
                # 继续处理下一个节点
                continue

        completed = sum(1 for t in tasks if t.status == GenerationStatus.COMPLETED)
        failed = sum(1 for t in tasks if t.status == GenerationStatus.FAILED)
        logger.info(
            f"[视频生成] 批量生成完成: 成功{completed}, 失败{failed}, 总计{len(tasks)}"
        )

        # 更新精确时间戳（基于实际TTS音频总时长）
        if completed > 0:
            from app.services.mapping_service import MappingService
            total_audio_duration = sum(
                t.audio_duration for t in tasks 
                if t.status == GenerationStatus.COMPLETED and t.audio_duration
            )
            if total_audio_duration > 0:
                MappingService.calculate_timestamps_from_audio(
                    session, script.id, total_audio_duration
                )
                logger.info(f"[视频生成] 已基于TTS音频时长({total_audio_duration:.1f}秒)更新精确时间戳")

        return tasks

    async def _synthesize_tts(
        self,
        node: ScriptNode,
        voice: Optional[str],
        task: VideoGenerationTask,
        session: Session,
    ) -> str:
        """
        TTS合成语音并保存到文件

        Returns:
            音频文件路径
        """
        text = node.content
        if not text or not text.strip():
            raise TTSError(f"节点{node.id}的讲解文本为空")

        logger.info(f"[TTS] 合成节点{node.id}的语音: {len(text)}字, voice={voice}")

        # 调用TTS合成
        tts_result = await TTSAdapter(tts_client).synthesize(
            text=text,
            voice=voice,
            output_format="wav",  # Digital human API requires wav.
        )
        if not tts_result.success:
            raise TTSError(tts_result.error_message or "TTS synthesis failed")

        response = tts_result.data
        # 保存音频文件
        audio_filename = f"node_{node.id}_{uuid.uuid4().hex[:8]}.wav"
        audio_path = AUDIO_ROOT / audio_filename
        audio_path.write_bytes(response.audio_data)

        # 更新任务
        task.audio_path = str(audio_path)
        task.audio_duration = response.duration_ms / 1000 if response.duration_ms else 0
        task.status = GenerationStatus.TTS_COMPLETED
        task.updated_at = datetime.utcnow()
        session.add(task)
        session.commit()

        logger.info(f"[TTS] 节点{node.id}音频已保存: {audio_path}, {len(response.audio_data)}字节")
        return str(audio_path)

    async def _resolve_face_video(
        self,
        face_video_asset_id: Optional[int],
        node: ScriptNode,
        session: Session,
    ) -> str:
        """
        解析人脸视频路径

        优先使用节点指定的素材，否则使用老师默认人脸视频
        """
        # 尝试使用指定的人脸视频素材
        if face_video_asset_id:
            asset = session.get(TeacherAsset, face_video_asset_id)
            if asset and asset.asset_type == AssetType.FACE_VIDEO:
                if Path(asset.file_path).exists():
                    return asset.file_path
                logger.warning(f"[视频生成] 人脸视频文件不存在: {asset.file_path}")

        # 使用老师的默认人脸视频
        script = session.get(CourseScript, node.script_id)
        course = session.get(Course, script.course_id)

        default_face = session.exec(
            select(TeacherAsset).where(
                TeacherAsset.teacher_id == course.teacher_id,
                TeacherAsset.asset_type == AssetType.FACE_VIDEO,
                TeacherAsset.is_default == True,
            )
        ).first()

        if default_face and Path(default_face.file_path).exists():
            return default_face.file_path

        # 尝试任意一个老师的人脸视频
        any_face = session.exec(
            select(TeacherAsset).where(
                TeacherAsset.teacher_id == course.teacher_id,
                TeacherAsset.asset_type == AssetType.FACE_VIDEO,
            )
        ).first()

        if any_face and Path(any_face.file_path).exists():
            return any_face.file_path

        raise ValueError(
            f"老师(ID={course.teacher_id})没有人脸视频素材，请先上传人脸视频"
        )

    def get_task_status(
        self,
        task_id: int,
        session: Session,
    ) -> Optional[VideoGenerationTask]:
        """查询生成任务状态"""
        return session.get(VideoGenerationTask, task_id)

    def get_course_tasks(
        self,
        course_id: int,
        session: Session,
    ) -> list[VideoGenerationTask]:
        """查询课程所有生成任务"""
        return session.exec(
            select(VideoGenerationTask).where(
                VideoGenerationTask.course_id == course_id
            ).order_by(VideoGenerationTask.id)
        ).all()


# 单例
video_generation_service = VideoGenerationService()
