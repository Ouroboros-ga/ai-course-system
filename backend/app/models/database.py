from sqlmodel import SQLModel, create_engine, Session
from typing import Generator
import os

from app.models.course_model import (
    Course,
    CourseScript,
    DoclingDocument,
    ChatSession,
    ChatMessage,
    User,
    LearningProgress,
    CourseNodeProgress,
)
from app.models.knowledge_model import (
    KnowledgeBase,
    KnowledgePoint,
    KnowledgeRelation,
    KnowledgeImportLog,
    KnowledgeSearchHistory,
)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DATABASE_DIR = os.path.join(PROJECT_ROOT, "database")
os.makedirs(DATABASE_DIR, exist_ok=True)

DATABASE_URL = f"sqlite:///{os.path.join(DATABASE_DIR, 'smart_class.db')}"

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
