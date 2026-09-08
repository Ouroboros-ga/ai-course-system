"""Nexus 产物（Artifact）元数据服务（M3 Artifact 真实化）。

数据域划分（AGENTS.md §4.1.11，按代码核定）：
- 文件字节 → 既有对象存储（同一存储根，前缀 ``nexus-artifacts/``），
  metadata 只存 ``object_key``（绝对路径不进业务数据，§4.1.7）；
- 元数据 → ``nexus_checkpoints.nexus_artifacts``（Nexus 域表，P1 验收时
  属主已为 ai_course_app，Backend 直读直写）；
- 列表/下载由 Backend 原生路由提供（JWT + require_nexus_use + 本人校验），
  文件字节不过 Runtime 进程——与 P2 计划 M3-B2 原文的偏离已记录在计划文档。

P0 支持类型：markdown / latex（纯文本对象）；DOCX 判 no-go（见计划文档）。

SR6：新增 word 类型（真正可编辑 .docx 二进制；旧 DOCX no-go 只属于历史
冻结范围，本阶段用户明确要求 Word，现提升为必做——见下阶段实施计划§10）。
word 经 content_b64（base64）写入字节，下载经对象存储直出，不经过文本编码。
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
    # SR6：原生可编辑 Word（.docx 二进制经 content_b64 写入；"docx" 仍为
    # 未知类型保持拒绝，旧契约不变）。
    "word": {"ext": "docx",
             "mime": "application/vnd.openxmlformats-officedocument"
                     ".wordprocessingml.document"},
}

_CONTENT_MAX_BYTES = 512 * 1024
_TITLE_MAX = 120
_LIST_LIMIT_MAX = 100

_SCHEMA = "nexus_checkpoints"

_TABLE_DDL_BODY_PG = """
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

# SQLite 仅本地测试（run 详情经 list_run_artifacts 触达本表）。
_TABLE_DDL_BODY_SQLITE = """
(
    artifact_id VARCHAR(16) PRIMARY KEY,
    user_id TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    title TEXT NOT NULL,
    object_key TEXT NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    sha256 TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL DEFAULT 0
)
"""

# NX-LB5：run 关联列（报告链/工具写入时可选带上；旧表经 _migrate 补列）。
_RUN_ID_DDL = "run_id VARCHAR(64) NOT NULL DEFAULT ''"

_table_ready = False
# 生产为 PostgreSQL 16，nexus_checkpoints 为 Nexus 独立 schema；SQLite 仅
# 用于本地测试（列表/详情端点测试需要可建表），涉表行为由测试＋线上验收覆盖。
_TABLE = f"{_SCHEMA}.nexus_artifacts"


def _is_sqlite(session: Session) -> bool:
    return session.connection().dialect.name == "sqlite"


def _table(session: Session) -> str:
    return "nexus_artifacts" if _is_sqlite(session) else _TABLE


def _existing_columns(session: Session, table: str) -> set[str]:
    bind = session.connection()
    if bind.dialect.name == "sqlite":
        rows = bind.execute(text(f"PRAGMA table_info({table})")).all()
        return {str(r[1]) for r in rows}
    rows = bind.execute(
        text("SELECT column_name FROM information_schema.columns "
             "WHERE table_schema=:schema AND table_name=:name"),
        {"schema": _SCHEMA, "name": table.split(".")[-1]},
    ).all()
    return {str(r[0]) for r in rows}


def ensure_table(session: Session) -> None:
    """幂等建表（进程内只执行一次；失败如实抛出由调用方转错误码）。

    NX-LB5：旧库补 run_id 列（可重入；回退=旧代码不 SELECT 该列）。
    """
    global _table_ready
    if _table_ready:
        return
    bind = session.connection()
    sqlite = _is_sqlite(session)
    if not sqlite:
        bind.execute(text(f"CREATE SCHEMA IF NOT EXISTS {_SCHEMA}"))
    table = _table(session)
    bind.execute(text(f"CREATE TABLE IF NOT EXISTS {table} "
                      f"{_TABLE_DDL_BODY_SQLITE if sqlite else _TABLE_DDL_BODY_PG}"))
    if "run_id" not in _existing_columns(session, table):
        bind.execute(text(f"ALTER TABLE {table} ADD COLUMN {_RUN_ID_DDL}"))
    bind.execute(
        text(
            f"CREATE INDEX IF NOT EXISTS idx_nexus_artifacts_user "
            f"ON {table} (user_id, created_at DESC)"
        )
    )
    session.commit()
    _table_ready = True


def _iso(ts: Any) -> str:
    return ts.isoformat() if hasattr(ts, "isoformat") else str(ts or "")


def validate_artifact_input(artifact_type: str, title: str, content: str) -> str | None:
    """返回错误码或 None（通过）。fail-closed 校验，两端同源。

    word 类型走二进制分支（见 validate_binary_input），此处仍拒绝
    content 形态的 word（字节必须经 base64，不经文本编码）。
    """
    if artifact_type not in ARTIFACT_TYPES:
        return "ARTIFACT_TYPE_UNSUPPORTED"
    if artifact_type == "word":
        return "ARTIFACT_CONTENT_INVALID"
    if not title or not title.strip() or len(title) > _TITLE_MAX:
        return "ARTIFACT_TITLE_INVALID"
    if not content:
        return "ARTIFACT_CONTENT_EMPTY"
    if len(content.encode("utf-8")) > _CONTENT_MAX_BYTES:
        return "ARTIFACT_CONTENT_TOO_LARGE"
    return None


def validate_binary_input(artifact_type: str, title: str, raw: bytes) -> str | None:
    """二进制产物校验（SR6 word）：类型必须为 word，字节非空且限大小。"""
    if artifact_type != "word" or artifact_type not in ARTIFACT_TYPES:
        return "ARTIFACT_TYPE_UNSUPPORTED"
    if not title or not title.strip() or len(title) > _TITLE_MAX:
        return "ARTIFACT_TITLE_INVALID"
    if not raw:
        return "ARTIFACT_CONTENT_EMPTY"
    if len(raw) > _CONTENT_MAX_BYTES:
        return "ARTIFACT_CONTENT_TOO_LARGE"
    return None


def _safe_filename(title: str, ext: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|\r\n]", "_", title.strip())[:60] or "artifact"
    return f"{cleaned}.{ext}"


def create_artifact(
    session: Session, *, user_id: str, artifact_type: str, title: str,
    content: str, run_id: str = "",
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
            f"INSERT INTO {_table(session)} "
            "(artifact_id, user_id, artifact_type, title, object_key, size_bytes, "
            "sha256, run_id) "
            "VALUES (:artifact_id, :user_id, :artifact_type, :title, :object_key, "
            ":size_bytes, :sha256, :run_id)"
        ),
        {
            "artifact_id": artifact_id,
            "user_id": user_id,
            "artifact_type": artifact_type,
            "title": title.strip(),
            "object_key": object_key,
            "size_bytes": size_bytes,
            "sha256": sha256 or hashlib.sha256(data).hexdigest(),
            "run_id": (run_id or "")[:64],
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


def create_binary_artifact(
    session: Session, *, user_id: str, artifact_type: str, title: str,
    data: bytes, run_id: str = "",
) -> dict[str, Any]:
    """二进制产物入库（SR6 word）：字节直接进对象存储，不经文本编码。

    调用方已过 validate_binary_input；此处不再二次限大小（与文本路径同源
    口径：大小在校验层裁决）。
    """
    ensure_table(session)
    spec = ARTIFACT_TYPES[artifact_type]
    artifact_id = uuid.uuid4().hex[:12]
    payload = bytes(data)
    object_key = f"nexus-artifacts/u{user_id}/{artifact_id}.{spec['ext']}"
    storage = get_object_storage()
    sha256 = storage.put(object_key, payload, mime_type=spec["mime"])
    size_bytes = len(payload)
    bind = session.connection()
    bind.execute(
        text(
            f"INSERT INTO {_table(session)} "
            "(artifact_id, user_id, artifact_type, title, object_key, size_bytes, "
            "sha256, run_id) "
            "VALUES (:artifact_id, :user_id, :artifact_type, :title, :object_key, "
            ":size_bytes, :sha256, :run_id)"
        ),
        {
            "artifact_id": artifact_id,
            "user_id": user_id,
            "artifact_type": artifact_type,
            "title": title.strip(),
            "object_key": object_key,
            "size_bytes": size_bytes,
            "sha256": sha256 or hashlib.sha256(payload).hexdigest(),
            "run_id": (run_id or "")[:64],
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


def list_run_artifacts(
    session: Session, *, user_id: str, run_id: str
) -> list[dict[str, Any]]:
    """NX-LB5：某 run 关联的本人产物（授权引用投影，含下载路径）。

    run 不存在/非本人 → 空列表（不可见即不存在）；Worker 工作目录文件
    清单不经此投影（不是可下载链接）。
    """
    ensure_table(session)
    rows = session.connection().execute(
        text(
            f"SELECT artifact_id, artifact_type, title, size_bytes, created_at "
            f"FROM {_table(session)} WHERE user_id = :user_id AND run_id = :run_id "
            "ORDER BY created_at ASC, artifact_id ASC LIMIT 50"
        ),
        {"user_id": user_id, "run_id": (run_id or "")[:64]},
    ).all()
    return [
        {
            "artifact_id": row[0],
            "artifact_type": row[1],
            "title": row[2],
            "size_bytes": row[3],
            "created_at": _iso(row[4]),
            "download_path": f"/api/v1/nexus/artifacts/{row[0]}/download",
        }
        for row in rows
    ]


def list_artifacts(session: Session, *, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
    ensure_table(session)
    rows = session.connection().execute(
        text(
            f"SELECT artifact_id, artifact_type, title, object_key, size_bytes, sha256, "
            f"created_at FROM {_table(session)} WHERE user_id = :user_id "
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
            f"FROM {_table(session)} WHERE artifact_id = :artifact_id AND user_id = :user_id"
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
