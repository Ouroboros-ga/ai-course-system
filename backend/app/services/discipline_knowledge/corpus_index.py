"""CR3 语料索引发布：版本组装、FTS 构建、校验、激活与引用回读。

数据模型（复用，无新表）：
- ``discipline_releases``（``scope="corpus:cs"``）：一次索引版本；
  ``building → ready``，``active`` 由 head 指针表达（历史 active 保持
  ready，可回切）。此 scope 的发布是**索引版本**，不是知识卡/课程快照。
- ``discipline_corpus_index_members``：版本冻结成员（chunk 清单 +
  展示元数据快照）；``embedding_id`` 可空（FTS-only 成员合法）。
- ``discipline_release_items``（``item_type="manifest"``）：发布 manifest
  快照（§4.2 字段），READY 后不可变。
- ``discipline_heads``（``scope="corpus:cs"``）：CAS 发布指针。
- FTS 文件：按 release 的确定性 object_key 存对象存储（只读打开，
  永不覆盖使用中文件；同内容重建幂等复用）。

FTS 文件格式（``FTS_SCHEMA_VERSION = "discipline-fts/1"``）：
``meta(release_id, schema_version, tokenizer, tokenizer_hash,
input_manifest_hash)``、``paragraph(rowid, chunk_id, title, body,
source)``、contentless ``corpus_fts``（rowid 仅文件内有效）。
``input_manifest_hash`` 只覆盖构建前冻结的输入/配置/成员清单，
不含 FTS 文件 hash（避免循环依赖）；发布 manifest 再记录 FTS hash。
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from sqlmodel import Session, select

from app.core.time_utils import utcnow_aware
from app.models.discipline_corpus_index_model import (
    DisciplineCorpusIndexMember,
    DisciplineCorpusVector,
)
from app.models.discipline_knowledge_model import (
    DisciplineChunk,
    DisciplineDocumentVersion,
    DisciplineHead,
    DisciplineRelease,
    DisciplineReleaseItem,
    DisciplineWorkItem,
)

CORPUS_SCOPE = "corpus:cs"

FTS_SCHEMA_VERSION = "discipline-fts/1"

#: FTS 分词口径版本（``tokenize_for_fts`` 行为变化必须 bump，否则
#: 查询/索引两侧口径分裂）。
FTS_TOKENIZER_VERSION = "fts-tokenizer/1"

MANIFEST_VERSION = "corpus-release-manifest/1"


class CorpusIndexError(ValueError):
    """携带错误码的索引失败（INDEX_NOT_READY / RELEASE_CONFLICT / ...）。"""

    def __init__(self, error_code: str, message: str):
        super().__init__(f"{error_code}: {message}")
        self.error_code = error_code


def _new_release_id() -> str:
    return "dkr_" + uuid.uuid4().hex[:12]


def _canonical_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def fts_tokenizer_hash() -> str:
    """FTS 分词口径哈希（实现引用 + 版本常量共同决定）。"""
    from app.platform.knowledge.discipline_corpus import tokenize_for_fts

    return "sha256:" + hashlib.sha256(
        (FTS_TOKENIZER_VERSION + "|" + tokenize_for_fts("分词口径探针 probe")
         ).encode("utf-8")).hexdigest()[:32]


# ---------------------------------------------------------------------------
# FTS 文件存储与连接
# ---------------------------------------------------------------------------

_fts_lock = threading.Lock()
_fts_conns: dict[str, sqlite3.Connection] = {}


def resolve_fts_root(explicit: Any = None) -> Path:
    """FTS 根目录：显式参数 > 环境变量 > Settings > 默认相对目录。"""
    if explicit:
        return Path(str(explicit))
    env_root = os.environ.get("DISCIPLINE_FTS_ROOT", "").strip()
    if env_root:
        return Path(env_root)
    try:
        from app.core.config import settings

        configured = str(getattr(settings, "DISCIPLINE_FTS_ROOT", "") or "")
        if configured.strip():
            return Path(configured)
    except Exception:  # noqa: BLE001 - 无配置环境回退默认目录
        pass
    backend_root = Path(__file__).resolve().parents[3]
    return backend_root / "media" / "discipline_fts"


def fts_object_key_for(release_id: str) -> str:
    """确定性对象 key：同 release 恒同一 key（重建幂等，不覆盖读中文件）。"""
    safe = "".join(c if (c.isalnum() or c in "-_") else "_"
                   for c in str(release_id or "unknown"))
    return f"corpus-fts/v1/{safe}.sqlite3"


def _fts_path(object_key: str, root: Any = None) -> Path:
    return resolve_fts_root(root) / object_key


def get_fts_store(root: Any = None):
    """FTS 文件的对象存储 provider（复用本地实现，按 key 隔离）。"""
    from app.services.object_storage import LocalStorageProvider

    resolved = resolve_fts_root(root)
    resolved.mkdir(parents=True, exist_ok=True)
    return LocalStorageProvider(str(resolved))


def open_fts_readonly(object_key: str, *, expected_release_id: str = "",
                       root: Any = None) -> sqlite3.Connection:
    """只读打开 FTS 文件（进程内按 key 缓存连接），并校验 meta。

    meta 不匹配（错版本文件）直接抛 ``FTS_META_MISMATCH``，不降级假装命中。
    """
    cache_key = str(_fts_path(object_key, root))
    with _fts_lock:
        conn = _fts_conns.get(cache_key)
        if conn is None:
            path = _fts_path(object_key, root)
            if not path.is_file():
                raise CorpusIndexError(
                    "FTS_UNAVAILABLE", f"FTS 文件缺失：{object_key}")
            conn = sqlite3.connect(
                f"file:{path.as_posix()}?mode=ro", uri=True,
                check_same_thread=False)
            _fts_conns[cache_key] = conn
    with _fts_lock:
        try:
            row = conn.execute(
                "SELECT release_id, schema_version, input_manifest_hash "
                "FROM meta LIMIT 1").fetchone()
        except sqlite3.Error as exc:
            raise CorpusIndexError(
                "FTS_META_MISMATCH", f"FTS 缺 meta 表：{object_key}") from exc
    if not row:
        raise CorpusIndexError(
            "FTS_META_MISMATCH", f"FTS meta 为空：{object_key}")
    meta = dict(zip(
        ("release_id", "schema_version", "input_manifest_hash"), row))
    if meta.get("schema_version") != FTS_SCHEMA_VERSION:
        raise CorpusIndexError(
            "FTS_META_MISMATCH",
            f"FTS schema {meta.get('schema_version')} != {FTS_SCHEMA_VERSION}")
    if expected_release_id and meta.get("release_id") != expected_release_id:
        raise CorpusIndexError(
            "FTS_META_MISMATCH",
            f"FTS 属于 {meta.get('release_id')}，不是 {expected_release_id}")
    return conn


def close_fts_connections() -> None:
    """关闭缓存的只读连接（测试/文件替换场景）。"""
    global _fts_conns
    with _fts_lock:
        for conn in _fts_conns.values():
            try:
                conn.close()
            except Exception:  # noqa: BLE001 - 只读连接关闭失败无需处理
                pass
        _fts_conns = {}


# ---------------------------------------------------------------------------
# 发布组装
# ---------------------------------------------------------------------------


def _display_metadata(chunk: DisciplineChunk,
                      version: DisciplineDocumentVersion) -> dict[str, Any]:
    return {
        "title": version.title or version.external_id,
        "source_kind": version.source_kind,
        "source_url": version.source_url,
        "license": version.license_code,
        "language": version.language,
        "section_path": chunk.section_path,
        "version_id": version.version_id,
        "external_id": version.external_id,
        "chunk_no": chunk.chunk_no,
        "char_start": chunk.char_start,
        "char_end": chunk.char_end,
    }


def create_release(
    session: Session,
    *,
    chunk_ids: list[str],
    model_fingerprint: str,
    dimension: int,
    scope: str = CORPUS_SCOPE,
    source_manifest_hash: str = "",
    build_id: str = "",
    title: str = "",
) -> dict[str, Any]:
    """组装索引版本（status=building）：冻结成员 + 展示元数据快照。

    - 撤回版本（withdrawn）的 chunk 当场排除并记 ``excluded_withdrawn``
     （查询时仍实时检查，见 ``get_chunk_reference``）；
    - ``embedding_id`` 有缓存即填、无即空（FTS-only 合法，向量覆盖率
      如实记录，不伪装）；
    - ``build_id`` 非空时，把该构建的 fts/validate 单件 payload 指向本
      release（worker 侧接线，CR3 worker 认领执行）。
    """
    from app.platform.knowledge.corpus_embedding import (
        VectorCache,
        input_hash_for,
    )
    from app.services.discipline_knowledge.corpus_text import read_chunk_text

    if not chunk_ids:
        raise CorpusIndexError("SCHEMA_INVALID", "chunk 清单为空")
    if not model_fingerprint:
        raise CorpusIndexError("SCHEMA_INVALID", "model_fingerprint 必填")
    try:
        dimension = int(dimension or 0)
    except (TypeError, ValueError):
        dimension = 0
    if dimension <= 0:
        raise CorpusIndexError("SCHEMA_INVALID", "dimension 必填")

    now = utcnow_aware()
    release_id = _new_release_id()
    members: list[DisciplineCorpusIndexMember] = []
    excluded_withdrawn = 0
    cache = VectorCache(session)
    for chunk_id in dict.fromkeys(chunk_ids):
        chunk = session.exec(
            select(DisciplineChunk).where(
                DisciplineChunk.chunk_id == chunk_id)
        ).first()
        if chunk is None:
            raise CorpusIndexError(
                "CHUNK_NOT_FOUND", f"chunk 不存在：{chunk_id}")
        version = session.exec(
            select(DisciplineDocumentVersion).where(
                DisciplineDocumentVersion.version_id == chunk.version_id)
        ).first()
        if version is None:
            raise CorpusIndexError(
                "VERSION_NOT_FOUND", f"chunk 所属版本缺失：{chunk_id}")
        if version.status == "withdrawn":
            excluded_withdrawn += 1
            continue
        try:
            text = read_chunk_text(session, chunk_id)
        except Exception as exc:
            raise CorpusIndexError(
                "TEXT_UNAVAILABLE", f"成员原文不可读：{chunk_id}") from exc
        key = input_hash_for(text, "passage", model_fingerprint)
        hit = cache.get(model_fingerprint, key)
        members.append(DisciplineCorpusIndexMember(
            release_id=release_id,
            chunk_id=chunk_id,
            embedding_id=hit.embedding_id if hit is not None else None,
            display_metadata=_display_metadata(chunk, version),
        ))
    if not members:
        raise CorpusIndexError(
            "SCHEMA_INVALID", "有效成员为空（全部撤回或清单无效）")
    embedded = sum(1 for m in members if m.embedding_id)

    input_manifest_hash = "sha256:" + _canonical_hash({
        "members": sorted(m.chunk_id for m in members),
        "normalizer": "corpus-norm/2",
        "chunker": "corpus-chunk/1",
        "model_fingerprint": model_fingerprint,
        "dimension": dimension,
    })
    release = DisciplineRelease(
        release_id=release_id,
        scope=scope,
        status="building",
        parent_id=None,
        manifest_key="",
        source_policy_version="corpus-sources/1",
        counts={
            "manifest_version": MANIFEST_VERSION,
            "title": title,
            "members": len(members),
            "embedded": embedded,
            "fts_only": len(members) - embedded,
            "excluded_withdrawn": excluded_withdrawn,
            "model_fingerprint": model_fingerprint,
            "dimension": dimension,
            "input_manifest_hash": input_manifest_hash,
            "source_manifest_hash": source_manifest_hash,
            "build_id": build_id,
            "fts_object_key": "",
            "fts_sha256": "",
        },
        created_at=now,
    )
    session.add(release)
    for member in members:
        session.add(member)
    session.commit()

    if build_id:
        patched = 0
        for item in session.exec(
            select(DisciplineWorkItem).where(
                DisciplineWorkItem.build_id == build_id,
                DisciplineWorkItem.stage.in_(["fts", "validate"]),
            )
        ).all():
            item.payload_ref = json.dumps(
                {"release_id": release_id}, ensure_ascii=False)
            item.updated_at = now
            session.add(item)
            patched += 1
        if patched:
            session.commit()
    return {"release_id": release_id, "status": "building",
            "members": len(members), "embedded": embedded,
            "excluded_withdrawn": excluded_withdrawn,
            "input_manifest_hash": input_manifest_hash}


def get_release(session: Session, release_id: str) -> dict[str, Any]:
    """发布视图（含成员/向量覆盖计数，行为真源）。"""
    release = session.exec(
        select(DisciplineRelease).where(
            DisciplineRelease.release_id == release_id)
    ).first()
    if release is None:
        raise CorpusIndexError("RELEASE_NOT_FOUND", f"版本不存在：{release_id}")
    members = session.exec(
        select(DisciplineCorpusIndexMember).where(
            DisciplineCorpusIndexMember.release_id == release_id)
    ).all()
    by_stage: dict[str, int] = {}
    embedded = sum(1 for m in members if m.embedding_id)
    return {"release_id": release.release_id, "scope": release.scope,
            "status": release.status, "parent_id": release.parent_id,
            "counts": dict(release.counts or {}),
            "members": len(members), "embedded": embedded,
            "manifest_key": release.manifest_key,
            "published_at": release.published_at.isoformat()
            if release.published_at else None,
            "created_at": release.created_at.isoformat()
            if release.created_at else None}


def read_head(session: Session, scope: str = CORPUS_SCOPE) -> dict[str, Any]:
    """读当前发布指针（无指针即空，不伪造默认版本）。"""
    head = session.exec(
        select(DisciplineHead).where(DisciplineHead.scope == scope)
    ).first()
    if head is None:
        return {"scope": scope, "release_id": "", "revision": 0}
    return {"scope": head.scope, "release_id": head.release_id,
            "revision": head.revision}


# ---------------------------------------------------------------------------
# FTS 构建
# ---------------------------------------------------------------------------


def build_fts(session: Session, release_id: str) -> dict[str, Any]:
    """为版本构建 FTS 文件（staging 构建 → 校验 → 入库，幂等复用）。

    - 同 release 重复调用直接复用已入库文件（meta 校验通过才算）；
    - staging 文件关闭后才入库；入库 key 确定性，永不覆盖使用中文件
      （已存在即校验复用）；
    - 文本不可读即 ``TEXT_UNAVAILABLE``，不跳过凑数。
    """
    from app.platform.knowledge.discipline_corpus import tokenize_for_fts
    from app.services.discipline_knowledge.corpus_text import read_chunk_text

    release = session.exec(
        select(DisciplineRelease).where(
            DisciplineRelease.release_id == release_id)
    ).first()
    if release is None:
        raise CorpusIndexError("RELEASE_NOT_FOUND", f"版本不存在：{release_id}")
    counts = dict(release.counts or {})
    object_key = fts_object_key_for(release_id)
    expected_hash = counts.get("input_manifest_hash") or ""

    store = get_fts_store()
    if store.exists(object_key):
        try:
            open_fts_readonly(object_key, expected_release_id=release_id)
        except CorpusIndexError:
            pass
        else:
            paragraphs = _fts_paragraph_count(object_key)
            return {"release_id": release_id, "object_key": object_key,
                    "sha256": counts.get("fts_sha256") or "",
                    "paragraphs": paragraphs, "reused": True}

    members = session.exec(
        select(DisciplineCorpusIndexMember).where(
            DisciplineCorpusIndexMember.release_id == release_id)
        .order_by(DisciplineCorpusIndexMember.id)
    ).all()
    if not members:
        raise CorpusIndexError("SCHEMA_INVALID", "版本成员为空")

    staging = _fts_path(object_key).parent / f".staging-{release_id}.sqlite3"
    staging.parent.mkdir(parents=True, exist_ok=True)
    if staging.exists():
        staging.unlink()
    conn = sqlite3.connect(staging)
    try:
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute(
            "CREATE TABLE meta(release_id TEXT PRIMARY KEY, "
            "schema_version TEXT NOT NULL, tokenizer TEXT NOT NULL, "
            "tokenizer_hash TEXT NOT NULL, input_manifest_hash TEXT NOT NULL)")
        conn.execute(
            "CREATE TABLE paragraph(rowid INTEGER PRIMARY KEY, "
            "chunk_id TEXT NOT NULL, title TEXT NOT NULL DEFAULT '', "
            "body TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT '')")
        conn.execute(
            "CREATE VIRTUAL TABLE corpus_fts USING fts5("
            "title, body, tokenize='unicode61', content='')")
        rows = []
        for member in members:
            meta = dict(member.display_metadata or {})
            try:
                body = read_chunk_text(session, member.chunk_id)
            except Exception as exc:
                raise CorpusIndexError(
                    "TEXT_UNAVAILABLE",
                    f"成员原文不可读：{member.chunk_id}") from exc
            rows.append((member.chunk_id, str(meta.get("title") or ""),
                         body, str(meta.get("source_kind") or "")))
        conn.executemany(
            "INSERT INTO paragraph(chunk_id, title, body, source) "
            "VALUES (?, ?, ?, ?)", rows)
        conn.executemany(
            "INSERT INTO corpus_fts(rowid, title, body) "
            "SELECT rowid, ?, ? FROM paragraph WHERE chunk_id = ?",
            [(tokenize_for_fts(title), tokenize_for_fts(body), cid)
             for cid, title, body, _ in rows])
        conn.execute(
            "INSERT INTO meta(release_id, schema_version, tokenizer, "
            "tokenizer_hash, input_manifest_hash) VALUES (?, ?, ?, ?, ?)",
            (release_id, FTS_SCHEMA_VERSION, FTS_TOKENIZER_VERSION,
             fts_tokenizer_hash(), expected_hash))
        conn.commit()
        probe = conn.execute(
            "SELECT COUNT(*) FROM paragraph").fetchone()[0]
        if probe != len(members):
            raise CorpusIndexError(
                "INDEX_CORRUPT",
                f"FTS 段落数 {probe} != 成员数 {len(members)}")
    finally:
        conn.close()

    digest = hashlib.sha256(staging.read_bytes()).hexdigest()
    with staging.open("rb") as fh:
        store.put(object_key, fh, mime_type="application/x-sqlite3")
    staging.unlink()
    counts["fts_object_key"] = object_key
    counts["fts_sha256"] = "sha256:" + digest
    release.counts = counts
    session.add(release)
    session.commit()
    close_fts_connections()
    return {"release_id": release_id, "object_key": object_key,
            "sha256": "sha256:" + digest, "paragraphs": len(members),
            "reused": False}


def _fts_paragraph_count(object_key: str) -> int:
    conn = open_fts_readonly(object_key)
    with _fts_lock:
        return int(conn.execute("SELECT COUNT(*) FROM paragraph").fetchone()[0])


# ---------------------------------------------------------------------------
# 校验与发布
# ---------------------------------------------------------------------------


def validate_index(session: Session, release_id: str) -> dict[str, Any]:
    """发布前校验：成员/定位/维度/模型身份/FTS/向量探针，全部通过才 ready。

    返回 ``{ready, checks, error_code, reasons}``；半成品永不标 ready。
    服务不可读取 building 数据（查询只认 active head）。
    """
    from app.platform.knowledge.corpus_embedding import validate_vectors

    release = session.exec(
        select(DisciplineRelease).where(
            DisciplineRelease.release_id == release_id)
    ).first()
    if release is None:
        raise CorpusIndexError("RELEASE_NOT_FOUND", f"版本不存在：{release_id}")
    counts = dict(release.counts or {})
    reasons: list[str] = []
    checks: dict[str, Any] = {}
    members = session.exec(
        select(DisciplineCorpusIndexMember).where(
            DisciplineCorpusIndexMember.release_id == release_id)
    ).all()

    # -- 1. 成员非空 --
    checks["members_non_empty"] = len(members) > 0
    if not members:
        reasons.append("empty_members")

    # -- 2. 引用定位：chunk 行存在、版本可见 --
    bad_refs = 0
    for member in members:
        chunk = session.exec(
            select(DisciplineChunk).where(
                DisciplineChunk.chunk_id == member.chunk_id)
        ).first()
        if chunk is None:
            bad_refs += 1
            continue
        version = session.exec(
            select(DisciplineDocumentVersion).where(
                DisciplineDocumentVersion.version_id == chunk.version_id)
        ).first()
        if version is None or version.status == "withdrawn":
            bad_refs += 1
    checks["references_resolvable"] = bad_refs == 0
    if bad_refs:
        reasons.append(f"unresolvable_refs:{bad_refs}")

    # -- 3. 向量身份：模型分区一致、维度一致 --
    model_fp = counts.get("model_fingerprint") or ""
    dimension = int(counts.get("dimension") or 0)
    embedded_ids = [m.embedding_id for m in members if m.embedding_id]
    mismatched = 0
    if embedded_ids:
        rows = session.exec(
            select(DisciplineCorpusVector).where(
                DisciplineCorpusVector.embedding_id.in_(embedded_ids))
        ).all()
        found = {row.embedding_id: row for row in rows}
        for eid in embedded_ids:
            row = found.get(eid)
            if row is None or row.model_fingerprint != model_fp \
                    or row.dimension != dimension:
                mismatched += 1
    checks["vector_identity"] = mismatched == 0
    if mismatched:
        reasons.append(f"vector_identity_mismatch:{mismatched}")

    # -- 4. FTS 文件：存在、meta 一致、数量一致、探测命中 --
    fts_ok = False
    fts_detail = ""
    object_key = counts.get("fts_object_key") or fts_object_key_for(release_id)
    try:
        conn = open_fts_readonly(object_key, expected_release_id=release_id)
        with _fts_lock:
            total = int(conn.execute(
                "SELECT COUNT(*) FROM paragraph").fetchone()[0])
            meta_hash = conn.execute(
                "SELECT input_manifest_hash FROM meta LIMIT 1").fetchone()[0]
        if total != len(members):
            fts_detail = f"paragraph {total} != members {len(members)}"
        elif meta_hash != counts.get("input_manifest_hash"):
            fts_detail = "input_manifest_hash mismatch"
        else:
            # 探针词取自本 release 自己的首段落（原文经同一分词口径处理）：
            # 索引行为空/错位时零命中，必须判不 ready（旧实现 probe>=0 恒真）。
            from app.platform.knowledge.discipline_corpus import tokenize_for_fts

            with _fts_lock:
                probe_row = conn.execute(
                    "SELECT title, body FROM paragraph LIMIT 1").fetchone()
                probe_token = ""
                for column in (probe_row[1] if probe_row else "",
                               probe_row[0] if probe_row else ""):
                    tokens = tokenize_for_fts(str(column or "")).split()
                    if tokens:
                        probe_token = tokens[0]
                        break
                hits = 0
                if probe_token:
                    quoted = '"' + probe_token.replace('"', '""') + '"'
                    hits = int(conn.execute(
                        "SELECT COUNT(*) FROM corpus_fts "
                        "WHERE corpus_fts MATCH ?", (quoted,)).fetchone()[0])
            if not probe_token:
                fts_detail = "empty_probe_source"
            elif hits <= 0:
                fts_detail = f"probe_miss:{probe_token}"
            else:
                fts_ok = True
                fts_detail = f"paragraphs={total} probe_hits={hits}"
    except CorpusIndexError as exc:
        fts_detail = f"{exc.error_code}: {exc}"
    checks["fts"] = fts_ok
    if not fts_ok:
        reasons.append(f"fts:{fts_detail}")

    # -- 5. 向量探针：抽样可载入、有限、维度对 --
    vec_ok = True
    vec_detail = f"embedded={len(embedded_ids)}"
    if embedded_ids:
        try:
            sample = session.exec(
                select(DisciplineCorpusVector).where(
                    DisciplineCorpusVector.embedding_id.in_(
                        embedded_ids[:5]))
            ).all()
            validate_vectors(
                [list(r.embedding or []) for r in sample],
                expected_dimension=dimension, expected_count=len(sample))
            vec_detail += f" probe={len(sample)}"
        except Exception as exc:  # noqa: BLE001 - 探针失败即未就绪
            vec_ok = False
            vec_detail = f"probe_failed: {exc}"
    checks["vector_probe"] = vec_ok
    if not vec_ok:
        reasons.append(f"vector_probe:{vec_detail}")

    # -- 6. ANN/后端信息（声明式，不伪装性能） --
    try:
        dialect = session.get_bind().dialect.name \
            if session.get_bind() is not None else "unknown"
    except Exception:  # noqa: BLE001 - 方言探测失败即未知
        dialect = "unknown"
    checks["ann"] = {"backend": dialect, "ann_index": "none",
                     "mode": "exact-member-filtered"}

    ready = not reasons
    if ready:
        release.status = "ready"
        counts["validated_at"] = utcnow_aware().isoformat()
        counts["ann"] = checks["ann"]
        release.counts = counts
        session.add(release)
        _write_manifest_item(session, release, members)
        session.commit()
        return {"ready": True, "checks": checks, "error_code": "",
                "reasons": []}
    return {"ready": False, "checks": checks,
            "error_code": "INDEX_NOT_READY", "reasons": reasons}


def _write_manifest_item(session: Session, release: DisciplineRelease,
                         members: list[DisciplineCorpusIndexMember]) -> None:
    """冻结发布 manifest（READY 后不可变；内容见 §4.2）。"""
    counts = dict(release.counts or {})
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "release_id": release.release_id,
        "scope": release.scope,
        "source_manifest_hash": counts.get("source_manifest_hash") or "",
        "chunker": "corpus-chunk/1",
        "normalizer": "corpus-norm/2",
        "model_fingerprint": counts.get("model_fingerprint") or "",
        "dimension": counts.get("dimension") or 0,
        "fts_object_key": counts.get("fts_object_key") or "",
        "fts_sha256": counts.get("fts_sha256") or "",
        "input_manifest_hash": counts.get("input_manifest_hash") or "",
        "members": len(members),
        "embedded": sum(1 for m in members if m.embedding_id),
        "excluded_withdrawn": counts.get("excluded_withdrawn") or 0,
        "build_id": counts.get("build_id") or "",
        "created_at": release.created_at.isoformat()
        if release.created_at else "",
        "validated_at": counts.get("validated_at") or "",
        "retrieval": {"lexical_k": 30, "vector_k": 30, "top_k": 6,
                      "context_budget_tokens": 3000, "fusion": "rrf-k60"},
        "ann": counts.get("ann") or {},
    }
    payload_hash = "sha256:" + _canonical_hash(manifest)
    existing = session.exec(
        select(DisciplineReleaseItem).where(
            DisciplineReleaseItem.release_id == release.release_id,
            DisciplineReleaseItem.item_type == "manifest",
            DisciplineReleaseItem.stable_id == release.release_id,
        )
    ).first()
    if existing is not None:
        return  # manifest 已冻结，不覆盖
    session.add(DisciplineReleaseItem(
        release_id=release.release_id,
        item_type="manifest",
        stable_id=release.release_id,
        content_hash=payload_hash,
        payload=manifest,
    ))


def get_release_manifest(session: Session, release_id: str) -> dict[str, Any]:
    """读冻结 manifest（不存在即版本未 ready）。"""
    item = session.exec(
        select(DisciplineReleaseItem).where(
            DisciplineReleaseItem.release_id == release_id,
            DisciplineReleaseItem.item_type == "manifest",
            DisciplineReleaseItem.stable_id == release_id,
        )
    ).first()
    if item is None:
        raise CorpusIndexError(
            "INDEX_NOT_READY", f"版本 {release_id} 尚未发布冻结 manifest")
    return dict(item.payload or {})


def activate_index(session: Session, release_id: str,
                   expected_revision: int) -> dict[str, Any]:
    """CAS 激活发布指针：ready 校验 + 条件更新（数据库层比较并交换）。

    - 非 ready 版本拒绝（``INDEX_NOT_READY``），旧 head 不变；
    - revision 失配拒绝（``RELEASE_CONFLICT``），旧 head 不变；
    - 成功返回新 revision；以前 active 的版本保持 ready，可回切。

    原子性：指针推进是单条 ``UPDATE ... WHERE scope=? AND revision=?``，
    以数据库当前值为准；检查与写入之间他方提交会使 rowcount=0 而非覆盖。
    首次发布（无指针行）走 INSERT，由 ``scope`` 唯一约束兜底并发插入。
    """
    from sqlalchemy import update
    from sqlalchemy.exc import IntegrityError

    release = session.exec(
        select(DisciplineRelease).where(
            DisciplineRelease.release_id == release_id)
    ).first()
    if release is None:
        return {"error_code": "RELEASE_NOT_FOUND", "release_id": release_id}
    if release.status != "ready":
        return {"error_code": "INDEX_NOT_READY", "release_id": release_id,
                "status": release.status, **read_head(session)}
    now = utcnow_aware()
    expected = int(expected_revision)
    updated = session.execute(
        update(DisciplineHead)
        .where(DisciplineHead.scope == release.scope,
               DisciplineHead.revision == expected)
        .values(release_id=release_id, revision=expected + 1, updated_at=now))
    if updated.rowcount == 1:
        session.commit()
        return {"error_code": "", "release_id": release_id,
                "revision": expected + 1}
    session.rollback()
    if expected == 0:
        session.add(DisciplineHead(scope=release.scope, release_id=release_id,
                                   revision=1, updated_at=now))
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
        else:
            return {"error_code": "", "release_id": release_id, "revision": 1}
    head = read_head(session)
    return {"error_code": "RELEASE_CONFLICT", "release_id": release_id,
            "head_release_id": head["release_id"],
            "head_revision": head["revision"]}


# ---------------------------------------------------------------------------
# 引用回读
# ---------------------------------------------------------------------------


def get_chunk_reference(session: Session, chunk_id: str,
                        release_id: str) -> dict[str, Any]:
    """返回该版本限定的 chunk 原文与定位；越版本/撤回/不可见一律拒绝。

    不接受磁盘路径；引用身份 ``reference_id = {release_id}:{chunk_id}``。
    """
    member = session.exec(
        select(DisciplineCorpusIndexMember).where(
            DisciplineCorpusIndexMember.release_id == release_id,
            DisciplineCorpusIndexMember.chunk_id == chunk_id,
        )
    ).first()
    if member is None:
        raise CorpusIndexError(
            "NOT_IN_RELEASE", f"chunk 不属于版本 {release_id}：{chunk_id}")
    chunk = session.exec(
        select(DisciplineChunk).where(DisciplineChunk.chunk_id == chunk_id)
    ).first()
    version = None
    if chunk is not None:
        version = session.exec(
            select(DisciplineDocumentVersion).where(
                DisciplineDocumentVersion.version_id == chunk.version_id)
        ).first()
    if chunk is None or version is None:
        raise CorpusIndexError("NOT_FOUND", f"chunk 已缺失：{chunk_id}")
    if version.status == "withdrawn":
        raise CorpusIndexError(
            "SOURCE_WITHDRAWN", f"来源已撤回，不再展示：{chunk_id}")
    from app.services.discipline_knowledge.corpus_text import read_chunk_text

    try:
        text = read_chunk_text(session, chunk_id)
    except Exception as exc:
        raise CorpusIndexError(
            "TEXT_UNAVAILABLE", f"原文不可读：{chunk_id}") from exc
    meta = dict(member.display_metadata or {})
    return {
        "reference_id": f"{release_id}:{chunk_id}",
        "release_id": release_id,
        "chunk_id": chunk_id,
        "doc_id": version.external_id,
        "chunk_no": chunk.chunk_no,
        "title": meta.get("title") or version.title,
        "source_kind": version.source_kind,
        "source_url": version.source_url,
        "license": version.license_code,
        "language": version.language,
        "section_path": meta.get("section_path") or "",
        "char_start": chunk.char_start,
        "char_end": chunk.char_end,
        "text": text,
        "embedding_id": member.embedding_id,
        "is_supplementary": True,
    }
