"""NX-A1 附件服务：元数据 + 配额 + 生命周期 + 解析编排。

数据域（AGENTS.md §4.1.7/§4.1.11）：
- 文件字节 → 既有对象存储（前缀 ``nexus-attachments/``），元数据只存
  ``object_key``；解析产物（parsed.json）同样进对象存储，不进业务表；
- 元数据 → ``nexus_checkpoints.nexus_attachments``（Nexus 域）；
- 内容永不进入课程知识域/LearningEvidence/Course Graph（只进会话上下文）。

可移植性说明：本表用 TEXT/INTEGER/REAL(epoch 秒)/JSON-as-TEXT，SQLite 与
PG 双兼容——恢复语义必须本地可测（与 nexus_artifacts 的 PG-only 不同，
见 E1 验收"刷新/换设备可恢复"）。时间比较一律用 epoch 秒，避免方言日期函数。

生命周期（v1.3 C2）：uploading → parsing → ready/partial/failed；
未绑定会话 24h、已绑定 7d 过期（惰性判定：读时标记，不靠 cron）；
删除立即撤销读取并尽力清对象/索引，迟到任务不写回（parse 在请求内完成，
无后台写回路径）。
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any

from sqlalchemy import text
from sqlmodel import Session

from app.services.nexus_attachment_parse import (
    ALLOWED_EXTENSIONS,
    MAX_PARSED_BYTES,
    AttachmentParseError,
    ParsedAttachment,
    parse_bytes,
)
from app.services.object_storage import get_object_storage

_SCHEMA = "nexus_checkpoints"
_TABLE = f"{_SCHEMA}.nexus_attachments"

_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS {table} (
    attachment_id VARCHAR(16) PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT '',
    session_id TEXT NOT NULL DEFAULT '',
    filename TEXT NOT NULL DEFAULT '',
    ext TEXT NOT NULL DEFAULT '',
    mime TEXT NOT NULL DEFAULT '',
    size_bytes INTEGER NOT NULL DEFAULT 0,
    sha256 TEXT NOT NULL DEFAULT '',
    object_key TEXT NOT NULL DEFAULT '',
    parsed_key TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'uploading',
    error_code TEXT NOT NULL DEFAULT '',
    error_detail TEXT NOT NULL DEFAULT '',
    stats TEXT NOT NULL DEFAULT '{{}}',
    created_at REAL NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL DEFAULT 0,
    expires_at REAL NOT NULL DEFAULT 0
)
"""

# v1.3 C2 首版预算。
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_USER_ACTIVE_BYTES = 50 * 1024 * 1024
MAX_USER_ACTIVE_FILES = 20
MAX_CHAT_ATTACHMENTS = 5  # 每次对话最多引用附件数
UNBOUND_TTL_S = 24 * 3600
BOUND_TTL_S = 7 * 24 * 3600

_MIME_BY_EXT = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "ppt": "application/msword", "doc": "application/msword",
}

_table_ready = False


def ensure_table(session: Session) -> None:
    global _table_ready
    if _table_ready:
        return
    bind = session.connection()
    if bind.dialect.name != "sqlite":
        bind.execute(text(f"CREATE SCHEMA IF NOT EXISTS {_SCHEMA}"))
    bind.execute(text(_TABLE_DDL.format(table=_TABLE if bind.dialect.name != "sqlite" else "nexus_attachments")))
    session.commit()
    _table_ready = True


def _table(session: Session) -> str:
    return _TABLE if session.connection().dialect.name != "sqlite" else "nexus_attachments"


def _now() -> float:
    return time.time()


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "attachment_id": row[0], "user_id": row[1], "session_id": row[2],
        "filename": row[3], "ext": row[4], "mime": row[5],
        "size_bytes": row[6], "sha256": row[7],
        "object_key": row[8], "parsed_key": row[9],
        "status": row[10], "error_code": row[11], "error_detail": row[12],
        "stats": json.loads(row[13] or "{}"),
        "created_at": row[14], "updated_at": row[15], "expires_at": row[16],
    }


_COLUMNS = ("attachment_id, user_id, session_id, filename, ext, mime, size_bytes,"
            " sha256, object_key, parsed_key, status, error_code, error_detail,"
            " stats, created_at, updated_at, expires_at")


def _is_expired(row: dict[str, Any], now: float | None = None) -> bool:
    return (now if now is not None else _now()) >= float(row["expires_at"] or 0)


def _apply_expiry(session: Session, row: dict[str, Any]) -> dict[str, Any]:
    """惰性过期：读到过期行即标记 expired（终态内容不可读，元数据保留）。"""
    if row["status"] in ("deleted", "expired") or not _is_expired(row):
        return row
    session.connection().execute(
        text(f"UPDATE {_table(session)} SET status='expired', updated_at=:now "
             "WHERE attachment_id=:aid"),
        {"now": _now(), "aid": row["attachment_id"]},
    )
    session.commit()
    row["status"] = "expired"
    return row


def get_owned_attachment(
    session: Session, *, user_id: str, attachment_id: str
) -> dict[str, Any] | None:
    """按 owner 取附件；非 owner 与不存在同等 None（防枚举）；读时惰性过期。"""
    ensure_table(session)
    row = session.connection().execute(
        text(f"SELECT {_COLUMNS} FROM {_table(session)} "
             "WHERE attachment_id=:aid AND user_id=:uid"),
        {"aid": attachment_id, "uid": user_id},
    ).first()
    if row is None:
        return None
    return _apply_expiry(session, _row_to_dict(row))


def list_attachments(
    session: Session, *, user_id: str, session_id: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    """我的附件（更新时间倒序；可选按会话过滤；惰性过期逐行标记）。"""
    ensure_table(session)
    sql = (f"SELECT {_COLUMNS} FROM {_table(session)} WHERE user_id=:uid"
           " AND status != 'deleted'")
    params: dict[str, Any] = {"uid": user_id}
    if session_id:
        sql += " AND (session_id='' OR session_id=:sid)"
        params["sid"] = session_id
    sql += " ORDER BY updated_at DESC LIMIT :limit"
    params["limit"] = max(1, min(int(limit), 100))
    rows = session.connection().execute(text(sql), params).all()
    return [_apply_expiry(session, _row_to_dict(r)) for r in rows]


def _active_usage(session: Session, user_id: str) -> tuple[int, int]:
    """活跃占用（未删除未过期）：(bytes, files)，配额依据。"""
    rows = session.connection().execute(
        text(f"SELECT size_bytes, expires_at, status FROM {_table(session)} "
             "WHERE user_id=:uid AND status NOT IN ('deleted','expired','failed')"),
        {"uid": user_id},
    ).all()
    now = _now()
    total = sum(r[0] for r in rows if float(r[1] or 0) > now)
    count = sum(1 for r in rows if float(r[1] or 0) > now)
    return total, count


def _ocr_backfill(data: bytes, parsed: ParsedAttachment) -> None:
    """图片/扫描页 OCR 回填（PaddleOCR HTTP，best-effort，失败如实标注）。

    无服务/失败 → ocr=unavailable（不阻塞 ready，消费侧诚实降级）。
    有文本的视觉降级标注 vision=unavailable（无视觉模型配置）。
    """
    needs_ocr = parsed.kind == "image" or any(b.get("needs_ocr") for b in parsed.blocks)
    if not needs_ocr:
        return
    try:
        from app.platform.document_intelligence.ocr_port import get_ocr_port
        from app.core.config import settings
    except Exception:
        _mark_ocr(parsed, "unavailable", "OCR 端口不可用")
        return
    try:
        port = get_ocr_port()
    except Exception:
        _mark_ocr(parsed, "unavailable", "OCR 服务未配置")
        return
    if not getattr(port, "is_available", False):
        _mark_ocr(parsed, "unavailable", "OCR 服务未配置或不可达")
        return
    try:
        if parsed.kind == "image":
            result = port.ocr_image(data, lang="ch", page=1)
            texts = [b.text for p in result.pages for b in p.blocks if b.text.strip()]
            _mark_ocr(parsed, "ready" if texts else "empty",
                      "" if texts else "图片中未识别出文字")
            if texts:
                parsed.blocks.append({"kind": "text", "locator": "img1:ocr",
                                      "text": "\n".join(texts)[:4000]})
        else:
            _mark_ocr(parsed, "unavailable", "扫描页 OCR 按需触发（read 时分段）")
    except Exception as error:
        _mark_ocr(parsed, "unavailable", f"OCR 失败（{type(error).__name__}）")


def _mark_ocr(parsed: ParsedAttachment, status: str, note: str) -> None:
    parsed.stats["ocr"] = status
    if note:
        parsed.warnings.append(note)


def submit_attachment(
    session: Session, *, user_id: str, filename: str, data: bytes,
    session_id: str = "",
) -> dict[str, Any]:
    """提交附件：校验→配额→落对象存储→解析→落 parsed.json→ready/partial/failed。

    同步完成（解析预算内输入均为秒级；超限输入在解析层截断为 partial）。
    DOC/PPT 无 LibreOffice 时 failed(CONVERT_UNAVAILABLE)——目标保留。
    """
    ensure_table(session)
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise AttachmentParseError("ATTACHMENT_TYPE_UNSUPPORTED", f"不支持的格式：{ext or '（无扩展名）'}")
    if len(data) == 0:
        raise AttachmentParseError("ATTACHMENT_EMPTY", "空文件")
    if len(data) > MAX_FILE_BYTES:
        raise AttachmentParseError(
            "ATTACHMENT_TOO_LARGE", f"文件超过 {MAX_FILE_BYTES // 1024 // 1024}MiB 上限")
    used_bytes, used_files = _active_usage(session, user_id)
    if used_files >= MAX_USER_ACTIVE_FILES:
        raise AttachmentParseError("ATTACHMENT_QUOTA_FILES", "活跃附件数超限，请先删除")
    if used_bytes + len(data) > MAX_USER_ACTIVE_BYTES:
        raise AttachmentParseError("ATTACHMENT_QUOTA_BYTES", "附件总容量超限（50MiB），请先删除")
    # 嗅探前置（落盘前）：扩展名/魔数不符、容器损坏一律 422 无行；
    # 只有服务端侧失败（转换缺失/超时/意外）才落 failed 行供用户查看。
    from app.services.nexus_attachment_parse import sniff_kind
    sniff_kind(data, filename)

    now = _now()
    attachment_id = uuid.uuid4().hex[:12]
    sha256 = hashlib.sha256(data).hexdigest()
    object_key = f"nexus-attachments/u{user_id}/{attachment_id}.{ext}"
    storage = get_object_storage()
    storage.put(object_key, data, mime_type=_MIME_BY_EXT.get(ext, "application/octet-stream"))

    status, error_code, error_detail = "ready", "", ""
    parsed_key = ""
    stats: dict[str, Any] = {}
    try:
        parsed = parse_bytes(data, filename)
        _ocr_backfill(data, parsed)
        if parsed.truncated:
            status = "partial"
        payload = json.dumps({
            "kind": parsed.kind, "blocks": parsed.blocks,
            "truncated": parsed.truncated, "warnings": parsed.warnings,
            "stats": parsed.stats,
        }, ensure_ascii=False)
        raw = payload.encode("utf-8")
        if len(raw) > MAX_PARSED_BYTES:
            # 解析产物超限：截断 blocks（定位不断），标记 partial。
            # 注意：局部变量不得命名 text（会遮蔽 sqlalchemy.text）。
            kept, size = [], 0
            for block in parsed.blocks:
                btext = block.get("text", "")
                if size + len(btext.encode("utf-8")) > MAX_PARSED_BYTES // 2:
                    break
                kept.append(block)
                size += len(btext.encode("utf-8"))
            payload = json.dumps({
                "kind": parsed.kind, "blocks": kept, "truncated": True,
                "warnings": [*parsed.warnings, "解析产物超限，已截断"],
                "stats": parsed.stats,
            }, ensure_ascii=False)
            status = "partial"
        parsed_key = f"nexus-attachments/u{user_id}/{attachment_id}.parsed.json"
        storage.put(parsed_key, payload.encode("utf-8"), mime_type="application/json")
        stats = parsed.stats
        if parsed.warnings:
            stats = {**stats, "warnings": parsed.warnings}
    except AttachmentParseError as error:
        status, error_code, error_detail = "failed", error.code, error.detail
    expires_at = now + (BOUND_TTL_S if session_id else UNBOUND_TTL_S)
    session.connection().execute(
        text(f"INSERT INTO {_table(session)} ({_COLUMNS}) VALUES ("
             ":aid,:uid,:sid,:fn,:ext,:mime,:size,:sha,:okey,:pkey,"
             ":status,:ecode,:edetail,:stats,:now,:now,:exp)"),
        {"aid": attachment_id, "uid": user_id, "sid": session_id, "fn": filename[:200],
         "ext": ext, "mime": _MIME_BY_EXT.get(ext, "application/octet-stream"),
         "size": len(data), "sha": sha256, "okey": object_key, "pkey": parsed_key,
         "status": status, "ecode": error_code, "edetail": error_detail,
         "stats": json.dumps(stats, ensure_ascii=False), "now": now, "exp": expires_at},
    )
    session.commit()
    row = get_owned_attachment(session, user_id=user_id, attachment_id=attachment_id)
    assert row is not None
    return row


def bind_session(
    session: Session, *, user_id: str, attachment_id: str, session_id: str
) -> dict[str, Any]:
    """原子绑定会话：owner +（未绑定→绑定并续 7d | 已绑同会话→幂等）；
    已绑他会话 → SESSION_MISMATCH（调用方 403，不泄露他会话 id）。"""
    row = get_owned_attachment(session, user_id=user_id, attachment_id=attachment_id)
    if row is None:
        raise AttachmentParseError("ATTACHMENT_NOT_FOUND", "附件不存在")
    if row["status"] in ("deleted", "expired"):
        raise AttachmentParseError("ATTACHMENT_UNAVAILABLE", f"附件不可用（{row['status']}）")
    if row["session_id"] and row["session_id"] != session_id:
        raise AttachmentParseError("ATTACHMENT_SESSION_MISMATCH", "附件已绑定其他会话")
    if not row["session_id"]:
        now = _now()
        session.connection().execute(
            text(f"UPDATE {_table(session)} SET session_id=:sid, updated_at=:now,"
                 " expires_at=:exp WHERE attachment_id=:aid"),
            {"sid": session_id, "now": now, "exp": now + BOUND_TTL_S, "aid": attachment_id},
        )
        session.commit()
        row = get_owned_attachment(session, user_id=user_id, attachment_id=attachment_id)
        assert row is not None
    return row


def delete_attachment(session: Session, *, user_id: str, attachment_id: str) -> bool:
    """删除：行标记 deleted（立即撤销读取）+ 尽力清对象；不存在/非 owner 返回 False。"""
    row = get_owned_attachment(session, user_id=user_id, attachment_id=attachment_id)
    if row is None or row["status"] == "deleted":
        return False
    session.connection().execute(
        text(f"UPDATE {_table(session)} SET status='deleted', updated_at=:now "
             "WHERE attachment_id=:aid"),
        {"now": _now(), "aid": attachment_id},
    )
    session.commit()
    storage = get_object_storage()
    for key in (row["object_key"], row["parsed_key"]):
        if key:
            try:
                storage.delete(key)
            except Exception:
                pass  # 对象清理 best-effort；行已标记，读取已撤销
    return True


def load_parsed_blocks(
    session: Session, *, user_id: str, attachment_id: str, max_chars: int = 24_000,
    locator: str = ""
) -> dict[str, Any]:
    """取解析 blocks（Runtime 消费入口）：owner + 可用状态 + 会话绑定由调用方保证。

    locator 非空时只返回该定位 block（页/slide/sheet/段落精读）；否则按预算
    顺序截取并标记 truncated。content 永不含原图字节（vision 预留）。
    """
    row = get_owned_attachment(session, user_id=user_id, attachment_id=attachment_id)
    if row is None:
        raise AttachmentParseError("ATTACHMENT_NOT_FOUND", "附件不存在")
    if row["status"] not in ("ready", "partial"):
        raise AttachmentParseError("ATTACHMENT_UNAVAILABLE",
                                   f"附件不可读（{row['status']}）")
    if not row["parsed_key"]:
        raise AttachmentParseError("ATTACHMENT_UNAVAILABLE", "附件无解析产物")
    storage = get_object_storage()
    try:
        payload = json.loads(storage.get(row["parsed_key"]).decode("utf-8"))
    except Exception as error:
        raise AttachmentParseError("ATTACHMENT_UNAVAILABLE", "解析产物读取失败") from error
    blocks = payload.get("blocks", [])
    if locator:
        blocks = [b for b in blocks if b.get("locator") == locator]
        if not blocks:
            raise AttachmentParseError("ATTACHMENT_LOCATOR_NOT_FOUND", f"无此定位：{locator}")
    out, size, cut = [], 0, False
    for block in blocks:
        text = block.get("text", "")
        if size + len(text) > max_chars:
            cut = True
            break
        out.append(block)
        size += len(text)
    return {
        "attachment_id": attachment_id, "filename": row["filename"],
        "kind": payload.get("kind", row["ext"]),
        "status": row["status"], "blocks": out,
        "truncated": bool(cut or payload.get("truncated")),
        "total_blocks": len(payload.get("blocks", [])),
    }
