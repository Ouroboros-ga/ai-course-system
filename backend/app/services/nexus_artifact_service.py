"""Nexus 产物（Artifact）元数据服务（M3 Artifact 真实化）。

数据域划分（AGENTS.md §4.1.11，按代码核定）：
- 文件字节 → 既有对象存储（同一存储根，前缀 ``nexus-artifacts/``），
  metadata 只存 ``object_key``（绝对路径不进业务数据，§4.1.7）；
- 元数据 → ``nexus_checkpoints.nexus_artifacts``（Nexus 域表，P1 验收时
  属主已为 ai_course_app，Backend 直读直写）；
- 列表/下载由 Backend 原生路由提供（JWT + require_nexus_use + 本人校验），
  文件字节不过 Runtime 进程——与 P2 计划 M3-B2 原文的偏离已记录在计划文档。

P0 支持类型：markdown / latex（纯文本对象）；DOCX 判 no-go（见计划文档）。
"""
from __future__ import annotations

import hashlib
import re
import uuid
from typing import Any

from sqlalchemy import text
from sqlmodel import Session

from app.services.object_storage import get_object_storage

ARTIFACT_TYPES: dict[str, dict[str, str]] = {
    "markdown": {"ext": "md", "mime": "text/markdown"},
    "latex": {"ext": "tex", "mime": "application/x-tex"},
}

_CONTENT_MAX_BYTES = 512 * 1024
_TITLE_MAX = 120
_LIST_LIMIT_MAX = 100

_SCHEMA = "nexus_checkpoints"

_TABLE_DDL_BODY = """
(
    artifact_id VARCHAR(16) PRIMARY KEY,
    user_id TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    title TEXT NOT NULL,
    object_key TEXT NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    sha256 TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

_table_ready = False
# PG-only（nexus_checkpoints 为 Nexus 独立 schema，生产即 PostgreSQL 16；
# 涉表行为由部署后线上验收覆盖，不为本仓库 SQLite 测试引擎做方言分支）。
_TABLE = f"{_SCHEMA}.nexus_artifacts"


def ensure_table(session: Session) -> None:
    """幂等建表（进程内只执行一次；失败如实抛出由调用方转错误码）。"""
    global _table_ready
    if _table_ready:
        return
    bind = session.connection()
    bind.execute(text(f"CREATE SCHEMA IF NOT EXISTS {_SCHEMA}"))
    bind.execute(text(f"CREATE TABLE IF NOT EXISTS {_TABLE} {_TABLE_DDL_BODY}"))
    bind.execute(
        text(
            f"CREATE INDEX IF NOT EXISTS idx_nexus_artifacts_user "
            f"ON {_TABLE} (user_id, created_at DESC)"
        )
    )
    session.commit()
    _table_ready = True


def validate_artifact_input(artifact_type: str, title: str, content: str) -> str | None:
    """返回错误码或 None（通过）。fail-closed 校验，两端同源。"""
    if artifact_type not in ARTIFACT_TYPES:
        return "ARTIFACT_TYPE_UNSUPPORTED"
    if not title or not title.strip() or len(title) > _TITLE_MAX:
        return "ARTIFACT_TITLE_INVALID"
    if not content:
        return "ARTIFACT_CONTENT_EMPTY"
    if len(content.encode("utf-8")) > _CONTENT_MAX_BYTES:
        return "ARTIFACT_CONTENT_TOO_LARGE"
    return None


def _safe_filename(title: str, ext: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|\r\n]", "_", title.strip())[:60] or "artifact"
    return f"{cleaned}.{ext}"


def create_artifact(
    session: Session, *, user_id: str, artifact_type: str, title: str, content: str
) -> dict[str, Any]:
    ensure_table(session)
    spec = ARTIFACT_TYPES[artifact_type]
    artifact_id = uuid.uuid4().hex[:12]
    data = content.encode("utf-8")
    object_key = f"nexus-artifacts/u{user_id}/{artifact_id}.{spec['ext']}"
    storage = get_object_storage()
    sha256 = storage.put(object_key, data, mime_type=spec["mime"])
    size_bytes = len(data)
    bind = session.connection()
    bind.execute(
        text(
            f"INSERT INTO {_TABLE} "
            "(artifact_id, user_id, artifact_type, title, object_key, size_bytes, sha256) "
            "VALUES (:artifact_id, :user_id, :artifact_type, :title, :object_key, "
            ":size_bytes, :sha256)"
        ),
        {
            "artifact_id": artifact_id,
            "user_id": user_id,
            "artifact_type": artifact_type,
            "title": title.strip(),
            "object_key": object_key,
            "size_bytes": size_bytes,
            "sha256": sha256 or hashlib.sha256(data).hexdigest(),
        },
    )
    session.commit()
    return {
        "artifact_id": artifact_id,
        "artifact_type": artifact_type,
        "title": title.strip(),
        "object_key": object_key,
        "size_bytes": size_bytes,
        "sha256": sha256,
    }


def list_artifacts(session: Session, *, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
    ensure_table(session)
    rows = session.connection().execute(
        text(
            f"SELECT artifact_id, artifact_type, title, object_key, size_bytes, sha256, "
            f"created_at FROM {_TABLE} WHERE user_id = :user_id "
            "ORDER BY created_at DESC LIMIT :limit"
        ),
        {"user_id": user_id, "limit": max(1, min(int(limit), _LIST_LIMIT_MAX))},
    ).all()
    return [
        {
            "artifact_id": row[0],
            "artifact_type": row[1],
            "title": row[2],
            "object_key": row[3],
            "size_bytes": row[4],
            "sha256": row[5],
            "created_at": row[6].isoformat() if row[6] else "",
        }
        for row in rows
    ]


def get_owned_artifact(session: Session, *, user_id: str, artifact_id: str) -> dict[str, Any] | None:
    """按 owner 取产物；非 owner 与不存在同等返回 None（列表不可见即不存在）。"""
    ensure_table(session)
    row = session.connection().execute(
        text(
            f"SELECT artifact_id, artifact_type, title, object_key, size_bytes, sha256, created_at "
            f"FROM {_TABLE} WHERE artifact_id = :artifact_id AND user_id = :user_id"
        ),
        {"artifact_id": artifact_id, "user_id": user_id},
    ).first()
    if row is None:
        return None
    return {
        "artifact_id": row[0],
        "artifact_type": row[1],
        "title": row[2],
        "object_key": row[3],
        "size_bytes": row[4],
        "sha256": row[5],
        "created_at": row[6].isoformat() if row[6] else "",
    }


def mime_and_filename(artifact: dict[str, Any]) -> tuple[str, str]:
    spec = ARTIFACT_TYPES.get(artifact["artifact_type"], {"ext": "txt", "mime": "text/plain"})
    return spec["mime"], _safe_filename(artifact["title"], spec["ext"])
