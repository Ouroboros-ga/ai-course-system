


from sqlmodel import SQLModel, create_engine, Session
from typing import Generator

DATABASE_URL = f"sqlite:///smart_class.db"

engine = create_engine(
    DATABASE_URL,
    echo=True,  # True: 在控制台打印 SQL 语句，方便调试；生产环境可改为 False
    connect_args={"check_same_thread": False}
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