from sqlmodel import SQLModel, create_engine, Session
from typing import Generator
import os

from app.models.course_model import (
    Course,
    CourseScript,
    ScriptNode,
    DoclingDocument,
    DoclingGroup,
    DoclingTable,
    DoclingTableCell,
    DoclingText,
    DoclingPicture,
    StudentEnrollment,
)
from app.models.access_control_model import (
    CourseCapability,
    CourseMembership,
    PlatformPermissionAssignment,
)
from app.models.user_model import (
    User,
    ChatHistory,
    ChatMessage,
)
from app.models.progress_model import (
    LearningProgress,
    NodeProgress,
    UnderstandingAnalysis,
    LearningJumpHistory,
)
from app.models.knowledge_model import (
    KnowledgeBase,
    KnowledgePoint,
    KnowledgeRelation,
    KnowledgeImportLog,
    KnowledgeSearchHistory,
)
from app.models.mapping_model import (
    KnowledgePageMap,
)
from app.models.video_generation_model import (
    VideoGenerationTask,
)
from app.models.asset_model import (
    TeacherAsset,
)
from app.models.qa_model import (
    QASession,
    QAMessage,
    QAContext,
)
from app.models.document_artifact_model import DocumentArtifact
from app.models.note_model import Note
from app.models.confirmation_model import CourseConfirmation
from app.models.feedback_model import Feedback

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DATABASE_DIR = os.path.join(PROJECT_ROOT, "database")
os.makedirs(DATABASE_DIR, exist_ok=True)

PRODUCTION_DATABASE_PATH = os.path.join(DATABASE_DIR, "smart_class.db")
DEFAULT_DATABASE_URL = f"sqlite:///{PRODUCTION_DATABASE_PATH}"
DATABASE_URL = os.environ.get("AI_COURSE_DATABASE_URL", DEFAULT_DATABASE_URL)

engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
)


def create_tables():
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    """
    依赖注入函数：生成数据库会话。
    用法：在 FastAPI 路径操作函数中作为 Depends(get_session) 使用。

    yield 机制确保即使发生异常，session 也会在最后被正确关闭。
    """
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()
