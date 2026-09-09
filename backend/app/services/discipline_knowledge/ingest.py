"""文档导入：DK1 确定性登记 + CR1 可回读的原文/分块改造。

- ``ingest_document(session, record)``：旧调用兼容（norm/1 + chunk/1）。
- ``ingest_document(session, record, *, chunker_config={...})``：新路线
  （corpus-norm/2 + corpus-chunk/1 + tokenizer 计数），同文档新 chunker
  生成新块（旧实现命中版本即返回旧块的遗漏已修复）。
- 规范化正文先写对象存储、读回验 hash 通过才登记；``read_chunk_text``
  见 ``corpus_text.py``（回读验 hash，无兜底）。
- 纯元数据变化（标题/链接/许可等）更新版本行，不建新版本/新块；
  进入新发布 manifest 的快照语义由 CR3 承担。

输入目录来自受信任部署配置；公开 API 不接收任意本机路径。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Optional

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core.time_utils import utcnow_aware
from app.models.discipline_knowledge_model import (
    DisciplineAlias,
    DisciplineAssertion,
    DisciplineChunk,
    DisciplineConcept,
    DisciplineDocumentVersion,
)
from app.services.discipline_knowledge.corpus_text import (
    CORPUS_CHUNKER_BASE,
    CORPUS_NORMALIZER_VERSION,
    CharFallbackTokenizer,
    chunk_document,
    metadata_hash_for,
    normalize_corpus_text,
    put_normalized_text,
)
from app.services.discipline_knowledge.identity import (
    CHUNKER_VERSION,
    NORMALIZER_VERSION,
    assertion_id_for_legacy,
    chunk_id_for,
    chunk_spans,
    concept_id_for_legacy,
    content_hash_for,
    estimate_tokens,
    normalize_alias,
    normalize_text,
    version_id_for,
)

#: 与 app/platform/knowledge/discipline_kb.py::NODE_FILES 同源的 seed 文件清单
#: （此处为数据导入侧镜像，避免服务层反向依赖检索实现）。
LEGACY_NODE_FILES = (
    "data_structures.json", "algorithms.json", "os.json", "net.json",
    "db.json", "se.json", "ml.json", "compiler.json", "arch.json",
    "discrete.json", "graphics.json",
)
LEGACY_RELATION_FILE = "relations.json"

#: legacy 关系类型到 V1 谓词白名单的映射；未知类型降级为 related_to，
#: 原类型恒保留在 qualifiers.legacy_relation_type，不丢失信息。
LEGACY_PREDICATE_MAP = {
    "defines": "defines",
    "uses": "uses",
    "prerequisite_of": "prerequisite_candidate",
    "contrasts_with": "contrasts_with",
    "related_to": "related_to",
    "derives_from": "part_of",
}

SOURCE_KINDS = ("textbook", "zhwiki", "enwiki", "rfc", "arxiv")


class DisciplineIngestError(ValueError):
    """携带错误码的导入校验失败（错误码见 ontology.json error_codes）。"""

    def __init__(self, error_code: str, message: str):
        super().__init__(f"{error_code}: {message}")
        self.error_code = error_code


def _detect_language(normalized: str) -> str:
    if any("\u4e00" <= ch <= "\u9fff" for ch in normalized):
        return "zh"
    if normalized.strip().isascii():
        return "en"
    return "mixed"


def _alias_language(raw_alias: str) -> str:
    return "en" if raw_alias.strip().isascii() else "zh"


def _resolve_chunker(chunker_config: Any) -> tuple[str, str, Any, dict]:
    """解析 chunker 配置 → (normalizer_version, chunker_version, tokenizer, cfg)。

    ``chunker_config=None`` 走 DK1 旧口径；字典走新路线。tokenizer 为
    实例（``.count/.name``）或 None（字符回退，明示名称）；字符串注册
    表由 CR2 接真实模型时提供。
    """
    if chunker_config is None:
        return NORMALIZER_VERSION, CHUNKER_VERSION, None, {}
    if not isinstance(chunker_config, dict):
        raise DisciplineIngestError("SCHEMA_INVALID", "chunker_config must be an object")
    normalizer_version = str(
        chunker_config.get("normalizer") or CORPUS_NORMALIZER_VERSION)
    if normalizer_version != CORPUS_NORMALIZER_VERSION:
        raise DisciplineIngestError(
            "SCHEMA_INVALID",
            f"unknown corpus normalizer '{normalizer_version}'",
        )
    base = str(chunker_config.get("chunker") or CORPUS_CHUNKER_BASE)
    if base != CORPUS_CHUNKER_BASE:
        raise DisciplineIngestError("SCHEMA_INVALID", f"unknown chunker '{base}'")
    tokenizer = chunker_config.get("tokenizer") or CharFallbackTokenizer()
    if isinstance(tokenizer, str):
        raise DisciplineIngestError(
            "SCHEMA_INVALID",
            f"命名 tokenizer 注册表由 CR2 提供，当前只接受实例或省略：{tokenizer}",
        )
    if not hasattr(tokenizer, "count") or not getattr(tokenizer, "name", ""):
        raise DisciplineIngestError(
            "SCHEMA_INVALID", "tokenizer 需要 .count(text) 与 .name")
    name = str(tokenizer.name)
    if not re.fullmatch(r"[A-Za-z0-9._+/-]+", name):
        raise DisciplineIngestError(
            "SCHEMA_INVALID", f"tokenizer 名称非法：{name}")
    cfg = {
        "target_tokens": chunker_config.get("target_tokens", 320),
        "overlap_tokens": chunker_config.get("overlap_tokens", 32),
        "max_tokens": chunker_config.get("max_tokens", 512),
    }
    # 分块参数参与身份：只改 target/overlap/max 也必须生成新块，否则同文档
    # 改参数会静默复用旧块（2026-09-08 全量审核 P2-13 实测确认的缺陷）。
    return (normalizer_version,
            f"{base}+{name}+t{cfg['target_tokens']}"
            f"+o{cfg['overlap_tokens']}+m{cfg['max_tokens']}",
            tokenizer, cfg)


def preview_document(record: dict, chunker_config: Any = None) -> dict[str, Any]:
    """无库校验 + 分块估算，返回规范化后的中间表示（导入与 dry-run 共用）。"""
    if not isinstance(record, dict):
        raise DisciplineIngestError("SCHEMA_INVALID", "record must be an object")
    source_kind = str(record.get("source_kind") or "").strip()
    if source_kind not in SOURCE_KINDS:
        raise DisciplineIngestError(
            "SCHEMA_INVALID",
            f"unknown source_kind '{source_kind}' (expected one of {', '.join(SOURCE_KINDS)})",
        )
    external_id = str(record.get("external_id") or "").strip()
    if not external_id:
        raise DisciplineIngestError("SCHEMA_INVALID", "record missing 'external_id'")
    raw_text = record.get("text") or ""
    if not str(raw_text).strip():
        raise DisciplineIngestError(
            "SCHEMA_INVALID",
            f"document '{external_id}' has empty text "
            "(DK1 requires inline text; object_key-only references are DK4 scope)",
        )
    if chunker_config is None:
        normalizer_version = str(record.get("normalizer_version") or NORMALIZER_VERSION)
        chunker_version = str(record.get("chunker_version") or CHUNKER_VERSION)
        normalized = normalize_text(raw_text, normalizer_version)
    else:
        normalizer_version, chunker_version, tokenizer, cfg = _resolve_chunker(
            chunker_config)
        normalized = normalize_corpus_text(raw_text, normalizer_version)
    raw_hash = hashlib.sha256(str(raw_text).encode("utf-8")).hexdigest()
    normalized_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    version_id = version_id_for(source_kind, external_id, raw_hash, normalizer_version)
    if chunker_config is None:
        spans = chunk_spans(normalized)
        if not spans:
            raise DisciplineIngestError(
                "SCHEMA_INVALID",
                f"document '{external_id}' yields no chunks "
                f"(text too short after normalization, {len(normalized)} chars)",
            )
        chunks = []
        for chunk_no, start, end, piece in spans:
            content_hash = content_hash_for(piece)
            locator = f"p{chunk_no}:{start}-{end}"
            chunks.append({
                "chunk_id": chunk_id_for(version_id, chunker_version, locator, content_hash),
                "chunk_no": chunk_no,
                "locator": locator,
                "content_hash": content_hash,
                "char_start": start,
                "char_end": end,
                "char_count": len(piece),
                "token_estimate": estimate_tokens(piece),
                "token_count": None,
                "section_path": str(record.get("section_path") or ""),
                "text_object_key": "",
            })
    else:
        pieces = chunk_document(normalized, tokenizer, cfg)
        if not pieces:
            raise DisciplineIngestError(
                "SCHEMA_INVALID",
                f"document '{external_id}' yields no chunks",
            )
        chunks = []
        for piece in pieces:
            content_hash = content_hash_for(piece["text"])
            locator = f"p{piece['chunk_no']}:{piece['char_start']}-{piece['char_end']}"
            chunks.append({
                "chunk_id": chunk_id_for(version_id, chunker_version, locator, content_hash),
                "chunk_no": piece["chunk_no"],
                "locator": locator,
                "content_hash": content_hash,
                "char_start": piece["char_start"],
                "char_end": piece["char_end"],
                "char_count": len(piece["text"]),
                "token_estimate": estimate_tokens(piece["text"]),
                "token_count": piece["token_count"],
                "section_path": str(record.get("section_path") or ""),
                "text_object_key": "",
            })
    object_key = str(record.get("object_key") or "")
    language = str(record.get("language") or "") or _detect_language(normalized)
    domains = record.get("domains") or []
    if not isinstance(domains, list):
        raise DisciplineIngestError("SCHEMA_INVALID", "'domains' must be a list")
    title = str(record.get("title") or "")
    metadata = {
        "title": title,
        "source_url": str(record.get("source_url") or ""),
        "license_code": str(record.get("license_code") or "unknown"),
        "language": language,
        "domains": domains,
        "source_family_id": str(
            record.get("source_family_id") or f"{source_kind}:{external_id}"),
    }
    return {
        "source_kind": source_kind,
        "external_id": external_id,
        **metadata,
        "raw_hash": raw_hash,
        "normalized_hash": normalized_hash,
        "metadata_hash": metadata_hash_for(metadata),
        "normalizer_version": normalizer_version,
        "chunker_version": chunker_version,
        "object_key": object_key,
        "version_id": version_id,
        "normalized": normalized,
        "char_count": len(normalized),
        "token_estimate": estimate_tokens(normalized),
        "chunks": chunks,
    }


def _find_version(session: Session, preview: dict) -> Optional[DisciplineDocumentVersion]:
    return session.exec(
        select(DisciplineDocumentVersion)
        .where(DisciplineDocumentVersion.source_kind == preview["source_kind"])
        .where(DisciplineDocumentVersion.external_id == preview["external_id"])
        .where(DisciplineDocumentVersion.raw_hash == preview["raw_hash"])
        .where(DisciplineDocumentVersion.normalizer_version == preview["normalizer_version"])
    ).first()


def _chunks_for(session: Session, version_id: str, chunker_version: str) -> list[str]:
    rows = session.exec(
        select(DisciplineChunk.chunk_id)
        .where(DisciplineChunk.version_id == version_id)
        .where(DisciplineChunk.chunker_version == chunker_version)
        .order_by(DisciplineChunk.chunk_no)
    ).all()
    return list(rows)


def _ensure_stored(preview: dict, object_key: str) -> str:
    """正文落存储并读回验 hash；DK1 历史行（object_key 为空）在此回填。"""
    from app.services.discipline_knowledge.corpus_text import get_store

    key = object_key or put_normalized_text(
        preview["version_id"], preview["source_kind"], preview["normalized"])
    if object_key:
        try:
            exists = get_store().exists(key)
        except OSError:
            exists = False
        if not exists:
            key = put_normalized_text(
                preview["version_id"], preview["source_kind"], preview["normalized"])
    return key


def _metadata_fields(preview: dict) -> dict[str, Any]:
    return {
        "title": preview["title"],
        "source_url": preview["source_url"],
        "source_family_id": preview["source_family_id"],
        "language": preview["language"],
        "domains": preview["domains"],
        "license_code": preview["license_code"],
        "metadata_hash": preview["metadata_hash"],
    }


def ingest_document(
    session: Session, record: dict, *, chunker_config: Any = None,
) -> dict[str, Any]:
    """登记文档版本并分块；重复导入幂等，同文档新 chunker 生成新块。

    - 正文先写对象存储、读回验 hash 通过才登记；
    - 纯元数据变化更新版本行（``metadata_updated=True``），不建新版本/新块；
    - ``chunker_config=None`` 走 DK1 旧口径（兼容旧调用与旧测试）。
    """
    preview = preview_document(record, chunker_config)
    existing = _find_version(session, preview)
    if existing is None:
        now = utcnow_aware()
        object_key = _ensure_stored(preview, preview["object_key"])
        session.add(DisciplineDocumentVersion(
            version_id=preview["version_id"],
            source_kind=preview["source_kind"],
            external_id=preview["external_id"],
            title=preview["title"],
            source_url=preview["source_url"],
            source_family_id=preview["source_family_id"],
            language=preview["language"],
            domains=preview["domains"],
            license_code=preview["license_code"],
            raw_hash=preview["raw_hash"],
            normalized_hash=preview["normalized_hash"],
            metadata_hash=preview["metadata_hash"],
            normalizer_version=preview["normalizer_version"],
            object_key=object_key,
            status="active",
            char_count=preview["char_count"],
            token_estimate=preview["token_estimate"],
            created_at=now,
            updated_at=now,
        ))
        _insert_chunks(session, preview)
        try:
            session.commit()
        except IntegrityError:
            # 并发重复导入：回滚后按已存在走后续分支，不抛错。
            session.rollback()
            existing = _find_version(session, preview)
            if existing is None:
                raise
        else:
            return _result(preview, object_key, created=True,
                           chunks_created=True, metadata_updated=False)

    object_key = _ensure_stored(preview, existing.object_key or preview["object_key"])
    metadata_updated = False
    fields = _metadata_fields(preview)
    if (existing.title != fields["title"]
            or existing.metadata_hash != fields["metadata_hash"]):
        for key, value in fields.items():
            setattr(existing, key, value)
        existing.object_key = object_key
        existing.updated_at = utcnow_aware()
        session.add(existing)
        metadata_updated = True
    elif not existing.object_key:
        existing.object_key = object_key
        existing.updated_at = utcnow_aware()
        session.add(existing)
    present = _chunks_for(session, existing.version_id, preview["chunker_version"])
    chunks_created = False
    if not present:
        _insert_chunks(session, preview)
        chunks_created = True
    session.commit()
    present = _chunks_for(session, existing.version_id, preview["chunker_version"])
    return _result(preview, object_key, created=False,
                   chunks_created=chunks_created, metadata_updated=metadata_updated,
                   chunk_ids=present)


def _insert_chunks(session: Session, preview: dict) -> None:
    for chunk in preview["chunks"]:
        session.add(DisciplineChunk(
            chunk_id=chunk["chunk_id"],
            version_id=preview["version_id"],
            chunker_version=preview["chunker_version"],
            chunk_no=chunk["chunk_no"],
            locator=chunk["locator"],
            content_hash=chunk["content_hash"],
            text_object_key=chunk["text_object_key"],
            char_start=chunk["char_start"],
            char_end=chunk["char_end"],
            char_count=chunk["char_count"],
            token_estimate=chunk["token_estimate"],
            token_count=chunk["token_count"],
            section_path=chunk["section_path"],
        ))


def _result(preview: dict, object_key: str, *, created: bool,
            chunks_created: bool, metadata_updated: bool,
            chunk_ids: Optional[list[str]] = None) -> dict[str, Any]:
    return {
        "version_id": preview["version_id"],
        "chunk_ids": chunk_ids if chunk_ids is not None
        else [c["chunk_id"] for c in preview["chunks"]],
        "chunk_count": len(chunk_ids) if chunk_ids is not None
        else len(preview["chunks"]),
        "created": created,
        "chunks_created": chunks_created,
        "metadata_updated": metadata_updated,
        "raw_hash": preview["raw_hash"],
        "normalized_hash": preview["normalized_hash"],
        "metadata_hash": preview["metadata_hash"],
        "object_key": object_key,
        "chunker_version": preview["chunker_version"],
        "title": preview["title"],
        "char_count": preview["char_count"],
        "token_estimate": preview["token_estimate"],
        "source_kind": preview["source_kind"],
        "external_id": preview["external_id"],
    }


def _resolve_knowledge_data_dir(explicit: Optional[str] = None) -> Path:
    if explicit:
        return Path(explicit)
    override = os.environ.get("KNOWLEDGE_DATA_DIR")
    if override:
        return Path(override)
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        candidate = parent / "knowledge_data"
        if candidate.is_dir():
            return candidate
    raise DisciplineIngestError(
        "SOURCE_UNAVAILABLE",
        "找不到 knowledge_data/ 目录（可传 directory 参数或设置 KNOWLEDGE_DATA_DIR）",
    )


def import_legacy_seed(session: Session, directory: Any = None) -> dict[str, Any]:
    """导入 legacy seed（112 节点/106 关系）为 legacy_unverified 锚点。

    - 概念：新 ``concept_id`` 稳定派生，旧 ID 存 ``legacy_id``；重复导入幂等；
    - 别名：按 ASCII 猜语言（en/zh），basis=legacy_seed；
    - 关系：转写为无 supports 的 assertion（旧书目无逐句证据，不得伪装 span）；
    - 坏 JSON 文件隔离（记入 errors）后继续，不中断其余文件。
    """
    kb_dir = _resolve_knowledge_data_dir(directory)
    mapping: dict[str, str] = {}
    skipped: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    alias_count = 0
    assertion_count = 0

    for filename in LEGACY_NODE_FILES:
        path = kb_dir / filename
        if not path.is_file():
            errors.append({"file": filename, "error_code": "SOURCE_UNAVAILABLE"})
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            errors.append({"file": filename, "error_code": "SCHEMA_INVALID", "detail": str(exc)[:200]})
            continue
        course = str(data.get("course") or "")
        for node in data.get("nodes", []):
            legacy_id = str(node.get("id") or "").strip()
            if not legacy_id:
                skipped.append({"file": filename, "reason": "missing node id"})
                continue
            concept_id = concept_id_for_legacy(legacy_id)
            mapping[legacy_id] = concept_id
            concept = session.exec(
                select(DisciplineConcept).where(DisciplineConcept.legacy_id == legacy_id)
            ).first()
            if concept is None:
                now = utcnow_aware()
                concept = DisciplineConcept(
                    concept_id=concept_id,
                    canonical_name=str(node.get("name") or legacy_id),
                    domain=course,
                    node_type=str(node.get("node_type") or "concept"),
                    status="legacy_unverified",
                    legacy_id=legacy_id,
                    revision=1,
                    created_at=now,
                    updated_at=now,
                )
                session.add(concept)
            for raw_alias in node.get("aliases", []) or []:
                raw_alias = str(raw_alias or "").strip()
                if not raw_alias:
                    continue
                language = _alias_language(raw_alias)
                normalized = normalize_alias(raw_alias)
                if not normalized:
                    continue
                exists = session.exec(
                    select(DisciplineAlias)
                    .where(DisciplineAlias.concept_id == concept.concept_id)
                    .where(DisciplineAlias.language == language)
                    .where(DisciplineAlias.normalized_alias == normalized)
                ).first()
                if exists is None:
                    session.add(DisciplineAlias(
                        concept_id=concept.concept_id,
                        language=language,
                        normalized_alias=normalized,
                        raw_alias=raw_alias,
                        domain=course,
                        basis="legacy_seed",
                    ))
                    alias_count += 1

    rel_path = kb_dir / LEGACY_RELATION_FILE
    if not rel_path.is_file():
        errors.append({"file": LEGACY_RELATION_FILE, "error_code": "SOURCE_UNAVAILABLE"})
    else:
        try:
            rel_data = json.loads(rel_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            errors.append({
                "file": LEGACY_RELATION_FILE,
                "error_code": "SCHEMA_INVALID",
                "detail": str(exc)[:200],
            })
            rel_data = {"relations": []}
        for rel in rel_data.get("relations", []):
            from_legacy = str(rel.get("from") or "").strip()
            to_legacy = str(rel.get("to") or "").strip()
            legacy_type = str(rel.get("relation_type") or "").strip()
            subject_id = mapping.get(from_legacy)
            object_id = mapping.get(to_legacy)
            if subject_id is None or object_id is None:
                skipped.append({
                    "from": from_legacy, "to": to_legacy,
                    "reason": "endpoint not in legacy seed",
                })
                continue
            predicate = LEGACY_PREDICATE_MAP.get(legacy_type, "related_to")
            assertion_id = assertion_id_for_legacy(subject_id, predicate, object_id)
            exists = session.exec(
                select(DisciplineAssertion).where(
                    DisciplineAssertion.assertion_id == assertion_id
                )
            ).first()
            if exists is None:
                now = utcnow_aware()
                session.add(DisciplineAssertion(
                    assertion_id=assertion_id,
                    subject_id=subject_id,
                    predicate=predicate,
                    object_id=object_id,
                    literal=None,
                    qualifiers={
                        "legacy": True,
                        "legacy_relation_type": legacy_type,
                        "note": str(rel.get("note") or ""),
                    },
                    status="legacy_unverified",
                    revision=1,
                    created_at=now,
                    updated_at=now,
                ))
                assertion_count += 1

    session.commit()
    legacy_unverified = len(mapping)
    return {
        "concepts": len(mapping),
        "aliases": alias_count,
        "assertions": assertion_count,
        "mapping": mapping,
        "legacy_unverified": legacy_unverified,
        "skipped": skipped,
        "errors": errors,
    }
