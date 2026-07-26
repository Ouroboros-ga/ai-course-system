"""Alembic 运行环境配置。

职责：
1. 从 AI_COURSE_DATABASE_URL 读取数据库连接（同时支持 SQLite 与 PostgreSQL）。
2. 以 SQLModel.metadata 作为 autogenerate 的比较基线。
3. 在 online/offline 两种模式下都能执行迁移。

注意：
- 本文件不调用 create_all()；全新库必须通过 alembic upgrade head 建表。
- 测试 fixture 通过本 env 的 run_migrations_online 建库。
"""
from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# 确保 app 包可被导入（当从 backend/ 目录运行 alembic 时）
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 导入 SQLModel.metadata 作为 autogenerate 基线
# 这会触发所有模型文件的导入，确保 metadata 包含全部表定义
from app.models import database  # noqa: F401
from sqlmodel import SQLModel

# Alembic 配置对象
config = context.config

# 从环境变量读取数据库 URL（覆盖 alembic.ini 中的空值）
config.set_main_option("sqlalchemy.url", os.environ.get("AI_COURSE_DATABASE_URL", ""))

# 日志配置
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# autogenerate 的目标 metadata
target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    """离线模式：生成 SQL 脚本而不连接数据库。

    用于审计、Review 和无法直连数据库的环境。
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # 比较类型与服务器默认值，确保 autogenerate 准确
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：直接连接数据库执行迁移。

    测试 fixture 与部署脚本均通过此路径建库。
    """
    # SQLite 需要 check_same_thread=False；PostgreSQL 不需要
    db_url = config.get_main_option("sqlalchemy.url") or ""
    connect_args: dict = {}
    if db_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=connect_args,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
