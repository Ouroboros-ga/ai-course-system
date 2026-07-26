"""G5 对象存储运维服务：引用登记 / GC 回收 / 回读校验 / 统计

设计原则：
- 仅平台管理员可调用（端点层强制 `PlatformPermission.ADMIN`）。
- GC 严格两阶段：先 reconcile 出软删除候选 → 等保留期过后才真正删除。
- 回读校验真实读取 Provider 字节并重算 SHA256；绝不凭记录伪装成功。
- 所有操作返回结构化报告，便于审计与运维查询。
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from sqlmodel import Session, select

from app.models.storage_object_ref_model import (
    StorageObjectRef,
    StorageVerifyStatus,
)
from app.services.object_storage import (
    ObjectStorageProvider,
    get_object_storage,
)


# ---------------------------------------------------------------------------
# 引用来源扫描配置
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ReferenceSource:
    """一个 DB 表中持有 object_key 的字段配置"""

    table_name: str
    columns: tuple[str, ...]


# 已知持有 object_key 的 DB 表与字段；reconcile 时遍历这些表收集引用集合。
# 不在此列表中的表不会被 GC 视为"被引用"，因此新增模型持有 object_key 时
# 必须同步登记到这里，避免误回收。
_KNOWN_REFERENCE_SOURCES: tuple[_ReferenceSource, ...] = (
    _ReferenceSource("source_material_versions", ("file_path",)),
    _ReferenceSource("media_assets", ("object_key",)),
    _ReferenceSource("media_timeline_cues", ("video_object_key", "audio_object_key")),
    _ReferenceSource("media_generation_jobs", ("output_object_key",)),
    _ReferenceSource(
        "media_releases",
        (
            "audio_object_key",
            "subtitle_manifest_object_key",
            "ppt_manifest_object_key",
            "digital_human_manifest_object_key",
        ),
    ),
    _ReferenceSource("media_release_cues", ("audio_object_key", "video_object_key")),
    _ReferenceSource("avatar_source_media", ("object_key",)),
    _ReferenceSource("avatar_asset_packages", ("manifest_object_key",)),
    _ReferenceSource("resource_versions", ("object_key",)),
    _ReferenceSource("question_import_runs", ("source_object_key",)),
    _ReferenceSource("experiment_definitions", ("statement_object_key",)),
    _ReferenceSource("experiment_run_artifacts", ("content_object_key",)),
)


@dataclass
class ReconcileReport:
    scanned_in_provider: int = 0
    referenced_in_db: int = 0
    new_refs_registered: int = 0
    refs_updated: int = 0
    orphans_marked: int = 0
    orphans_already_marked: int = 0
    refs_reactivated: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "scanned_in_provider": self.scanned_in_provider,
            "referenced_in_db": self.referenced_in_db,
            "new_refs_registered": self.new_refs_registered,
            "refs_updated": self.refs_updated,
            "orphans_marked": self.orphans_marked,
            "orphans_already_marked": self.orphans_already_marked,
            "refs_reactivated": self.refs_reactivated,
            "errors": self.errors,
        }


@dataclass
class GarbageCollectReport:
    candidates: int = 0
    deleted: int = 0
    retained_within_retention: int = 0
    retained_missing_in_provider: int = 0
    errors: list[str] = field(default_factory=list)
    deleted_keys: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "candidates": self.candidates,
            "deleted": self.deleted,
            "retained_within_retention": self.retained_within_retention,
            "retained_missing_in_provider": self.retained_missing_in_provider,
            "errors": self.errors,
            "deleted_keys": self.deleted_keys,
        }


@dataclass
class VerifyReadbackReport:
    sampled: int = 0
    ok: int = 0
    missing: int = 0
    hash_mismatch: int = 0
    mismatches: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "sampled": self.sampled,
            "ok": self.ok,
            "missing": self.missing,
            "hash_mismatch": self.hash_mismatch,
            "mismatches": self.mismatches,
        }


class StorageAdminService:
    """对象存储运维服务

    所有方法都在调用方传入的 session 内读写 `storage_object_refs` 表；
    Provider 通过 `get_object_storage()` 获取单例，便于在测试中替换。
    """

    def __init__(self, provider: Optional[ObjectStorageProvider] = None) -> None:
        self._provider_override = provider

    # ------------------------------------------------------------------
    # Provider 解析
    # ------------------------------------------------------------------

    def _provider(self) -> ObjectStorageProvider:
        return self._provider_override or get_object_storage()

    # ------------------------------------------------------------------
    # 引用来源扫描
    # ------------------------------------------------------------------

    def _scan_db_references(self, session: Session) -> dict[str, set[str]]:
        """返回 {table_name: {object_key, ...}}，跳过空字符串与 NULL。"""
        from sqlalchemy import text

        result: dict[str, set[str]] = {}
        bind = session.connection()
        for source in _KNOWN_REFERENCE_SOURCES:
            try:
                rows = bind.execute(
                    text(f"SELECT {', '.join(source.columns)} FROM {source.table_name}")
                ).fetchall()
            except Exception as exc:
                # 表可能不存在（旧库未迁移）；跳过并记录到 ReconcileReport.errors
                result[source.table_name] = set()
                result.setdefault("__errors__", set()).add(
                    f"{source.table_name}: {str(exc)[:120]}"
                )
                continue
            keys: set[str] = set()
            for row in rows:
                for value in row:
                    if value:
                        keys.add(str(value))
            result[source.table_name] = keys
        return result

    # ------------------------------------------------------------------
    # Reconcile
    # ------------------------------------------------------------------

    def reconcile(self, session: Session, *, prefix: str = "") -> ReconcileReport:
        """扫描 Provider 与 DB 引用，对齐 storage_object_refs 表

        - Provider 中存在但 DB 无引用 → 标记 soft_deleted_at（若尚未标记）
        - Provider 中存在且 DB 有引用 → 若已标记软删除则恢复
        - 新出现的对象 → 写入新 ref 行
        """
        report = ReconcileReport()
        provider = self._provider()

        provider_keys: list[str] = []
        try:
            provider_keys = provider.list_keys(prefix)
        except Exception as exc:
            report.errors.append(f"provider.list_keys: {str(exc)[:200]}")
            return report
        provider_key_set = set(provider_keys)
        report.scanned_in_provider = len(provider_key_set)

        db_refs = self._scan_db_references(session)
        # 把错误从 set 移到 list
        for err in db_refs.pop("__errors__", set()):
            report.errors.append(err)
        all_referenced: set[str] = set()
        for keys in db_refs.values():
            all_referenced |= keys
        report.referenced_in_db = len(all_referenced)

        # 加载现有 refs
        existing_refs: dict[str, StorageObjectRef] = {
            ref.object_key: ref
            for ref in session.exec(select(StorageObjectRef)).all()
        }

        now = datetime.utcnow()
        for key in provider_key_set:
            referenced_by = sorted(
                {table for table, keys in db_refs.items() if key in keys}
            )
            ref = existing_refs.get(key)
            if ref is None:
                # 新登记
                try:
                    head = provider.head(key)
                    new_ref = StorageObjectRef(
                        object_key=key,
                        content_sha256=head.get("content_sha256", ""),
                        size_bytes=int(head.get("size_bytes", 0)),
                        mime_type=head.get("mime_type", ""),
                        source_backend=provider.backend_name,
                        referenced_by=",".join(referenced_by),
                        last_verify_status=StorageVerifyStatus.NOT_VERIFIED.value,
                    )
                    if not referenced_by:
                        # 新对象且 DB 无引用 → 立即标记为孤儿
                        new_ref.soft_deleted_at = now
                        new_ref.soft_delete_reason = "reconcile:orphan"
                        report.orphans_marked += 1
                    session.add(new_ref)
                    report.new_refs_registered += 1
                except Exception as exc:
                    report.errors.append(f"register {key}: {str(exc)[:120]}")
            else:
                # 已存在；若引用来源变化或恢复引用，则更新
                new_ref_by = ",".join(referenced_by)
                needs_update = False
                if ref.referenced_by != new_ref_by:
                    ref.referenced_by = new_ref_by
                    needs_update = True
                if referenced_by and ref.soft_deleted_at is not None:
                    # DB 重新引用 → 恢复
                    ref.soft_deleted_at = None
                    ref.soft_delete_reason = ""
                    ref.updated_at = now
                    report.refs_reactivated += 1
                    needs_update = True
                if not referenced_by and ref.soft_deleted_at is None:
                    ref.soft_deleted_at = now
                    ref.soft_delete_reason = "reconcile:orphan"
                    ref.updated_at = now
                    report.orphans_marked += 1
                    needs_update = True
                elif not referenced_by and ref.soft_deleted_at is not None:
                    report.orphans_already_marked += 1
                if needs_update:
                    session.add(ref)
                    report.refs_updated += 1

        # 2) 处理 DB 引用但 Provider 不存在的 key（仅记录，不创建 ref）
        #    这类问题应在 verify_readback 阶段暴露，不在此重复登记。
        session.commit()
        return report

    # ------------------------------------------------------------------
    # 手动软删除 / 恢复
    # ------------------------------------------------------------------

    def mark_soft_deleted(
        self,
        session: Session,
        object_key: str,
        *,
        reason: str = "manual",
    ) -> bool:
        """手动标记一个 object_key 为软删除；下一次 GC 达到保留期后回收。"""
        ref = session.exec(
            select(StorageObjectRef).where(StorageObjectRef.object_key == object_key)
        ).first()
        if ref is None:
            return False
        ref.soft_deleted_at = datetime.utcnow()
        ref.soft_delete_reason = reason
        ref.updated_at = datetime.utcnow()
        session.add(ref)
        session.commit()
        return True

    def reactivate(self, session: Session, object_key: str) -> bool:
        """撤销软删除标记（在 GC 真正删除之前可恢复）。"""
        ref = session.exec(
            select(StorageObjectRef).where(StorageObjectRef.object_key == object_key)
        ).first()
        if ref is None or ref.soft_deleted_at is None:
            return False
        ref.soft_deleted_at = None
        ref.soft_delete_reason = ""
        ref.updated_at = datetime.utcnow()
        session.add(ref)
        session.commit()
        return True

    # ------------------------------------------------------------------
    # Garbage Collection
    # ------------------------------------------------------------------

    def run_gc(
        self,
        session: Session,
        *,
        retention_seconds: int = 86_400,
        dry_run: bool = False,
        max_deletions: int = 1_000,
    ) -> GarbageCollectReport:
        """回收 soft_deleted_at 早于 retention 的对象

        语义：
        - ``candidates`` = 所有已软删除的对象总数（不论是否过保留期），便于运维了解回收队列全貌。
        - ``retained_within_retention`` = 在保留期内、本次不回收的对象数。
        - ``retained_missing_in_provider`` = 过保留期但 Provider 中已缺失，仅清账本的对象数。
        - ``deleted`` = 本次真正（或 dry_run 模式下模拟）回收的对象数。
        - dry_run=True 只列出候选并模拟删除计数，不真正删除对象或 ref 行。
        - 删除失败不伪装成功；错误记录在 report.errors。
        """
        report = GarbageCollectReport()
        provider = self._provider()
        # 使用 naive UTC 与 SQLite 存储的 naive 字符串比较；SQLModel 写入时会剥离时区。
        cutoff = datetime.utcnow() - timedelta(seconds=retention_seconds)

        # 拉取全部已软删除的对象；candidates 反映回收队列全貌，不过滤保留期。
        all_soft_deleted = session.exec(
            select(StorageObjectRef).where(
                StorageObjectRef.soft_deleted_at.is_not(None),
            )
        ).all()
        report.candidates = len(all_soft_deleted)

        for ref in all_soft_deleted:
            if len(report.deleted_keys) >= max_deletions:
                break
            # 保留期内不回收
            if ref.soft_deleted_at is not None and ref.soft_deleted_at > cutoff:
                report.retained_within_retention += 1
                continue

            # 检查对象是否在 Provider 中真实存在
            try:
                exists = provider.exists(ref.object_key)
            except Exception as exc:
                report.errors.append(f"exists {ref.object_key}: {str(exc)[:120]}")
                continue

            if not exists:
                # Provider 中已无此对象；只清理 ref 行
                if not dry_run:
                    session.delete(ref)
                    session.commit()
                report.retained_missing_in_provider += 1
                continue

            if dry_run:
                report.deleted_keys.append(ref.object_key)
                report.deleted += 1
                continue

            try:
                deleted = provider.delete(ref.object_key)
                if not deleted:
                    report.errors.append(
                        f"{ref.object_key}: provider.delete returned False"
                    )
                    continue
                session.delete(ref)
                session.commit()
                report.deleted += 1
                report.deleted_keys.append(ref.object_key)
            except Exception as exc:
                report.errors.append(f"delete {ref.object_key}: {str(exc)[:120]}")
                # 失败不伪装成功；保留 ref 行，下次 GC 重试

        return report

    # ------------------------------------------------------------------
    # 回读校验
    # ------------------------------------------------------------------

    def verify_readback(
        self,
        session: Session,
        *,
        sample_size: int = 10,
        prefix: str = "",
    ) -> VerifyReadbackReport:
        """抽样读取 Provider 中的对象，重算 SHA256 与 refs 表对账

        - sample_size<=0 表示全量校验
        - 真实读取字节并哈希；不使用 Provider 自报的 sha
        - mismatch 不修改对象内容，只更新 last_verify_status
        - 同时检查 refs 表中登记但 Provider 已缺失的对象，标记 missing
        """
        report = VerifyReadbackReport()
        provider = self._provider()

        try:
            provider_keys = provider.list_keys(prefix)
        except Exception as exc:
            report.mismatches.append({"error": f"list_keys: {str(exc)[:120]}"})
            return report

        provider_key_set = set(provider_keys)
        if sample_size > 0 and len(provider_keys) > sample_size:
            provider_keys = random.sample(provider_keys, sample_size)
        else:
            provider_keys = list(provider_keys)

        now = datetime.utcnow()

        # 1) 检查 refs 表中登记但 Provider 已缺失的对象
        all_refs = session.exec(
            select(StorageObjectRef).where(
                StorageObjectRef.last_verify_status != StorageVerifyStatus.MISSING.value
            )
        ).all()
        for ref in all_refs:
            if ref.object_key not in provider_key_set:
                ref.last_verified_at = now
                ref.last_verify_status = StorageVerifyStatus.MISSING.value
                ref.updated_at = now
                session.add(ref)
                report.missing += 1
                report.sampled += 1

        # 2) 抽样读取 Provider 中存在的对象，重算 SHA256
        for key in provider_keys:
            report.sampled += 1
            ref = session.exec(
                select(StorageObjectRef).where(StorageObjectRef.object_key == key)
            ).first()
            try:
                content = provider.get(key)
                actual_sha = hashlib.sha256(content).hexdigest()
            except FileNotFoundError:
                if ref is not None:
                    ref.last_verified_at = now
                    ref.last_verify_status = StorageVerifyStatus.MISSING.value
                    ref.updated_at = now
                    session.add(ref)
                report.missing += 1
                continue
            except Exception as exc:
                report.mismatches.append(
                    {"object_key": key, "error": f"read: {str(exc)[:120]}"}
                )
                continue

            if ref is None:
                # Provider 中存在但 refs 表无记录；记录为 mismatch 供 reconcile 修复
                report.hash_mismatch += 1
                report.mismatches.append(
                    {
                        "object_key": key,
                        "error": "ref_not_registered",
                        "actual_sha256": actual_sha,
                    }
                )
                continue

            registered_sha = ref.content_sha256 or ""
            if not registered_sha:
                # refs 表没有 sha（旧数据）；用实际值补齐
                ref.content_sha256 = actual_sha
                ref.last_verified_at = now
                ref.last_verify_status = StorageVerifyStatus.OK.value
                ref.updated_at = now
                session.add(ref)
                report.ok += 1
                continue

            if registered_sha == actual_sha:
                ref.last_verified_at = now
                ref.last_verify_status = StorageVerifyStatus.OK.value
                ref.updated_at = now
                session.add(ref)
                report.ok += 1
            else:
                ref.last_verified_at = now
                ref.last_verify_status = StorageVerifyStatus.HASH_MISMATCH.value
                ref.updated_at = now
                session.add(ref)
                report.hash_mismatch += 1
                report.mismatches.append(
                    {
                        "object_key": key,
                        "registered_sha256": registered_sha,
                        "actual_sha256": actual_sha,
                    }
                )

        session.commit()
        return report

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------

    def get_stats(self, session: Session) -> dict:
        """返回存储总览：总数、总大小、按后端/状态分组"""
        refs = session.exec(select(StorageObjectRef)).all()
        total_size = sum(ref.size_bytes for ref in refs)
        by_backend: dict[str, int] = {}
        by_verify_status: dict[str, int] = {}
        soft_deleted_count = 0
        for ref in refs:
            by_backend[ref.source_backend] = by_backend.get(ref.source_backend, 0) + 1
            by_verify_status[ref.last_verify_status] = (
                by_verify_status.get(ref.last_verify_status, 0) + 1
            )
            if ref.soft_deleted_at is not None:
                soft_deleted_count += 1
        return {
            "total_objects": len(refs),
            "total_size_bytes": total_size,
            "soft_deleted_count": soft_deleted_count,
            "by_backend": by_backend,
            "by_verify_status": by_verify_status,
        }

    def list_refs(
        self,
        session: Session,
        *,
        soft_deleted_only: bool = False,
        prefix: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        """分页列出 refs"""
        stmt = select(StorageObjectRef)
        if soft_deleted_only:
            stmt = stmt.where(StorageObjectRef.soft_deleted_at.is_not(None))
        if prefix:
            stmt = stmt.where(StorageObjectRef.object_key.startswith(prefix))
        stmt = stmt.order_by(StorageObjectRef.object_key).offset(offset).limit(limit)
        items = session.exec(stmt).all()
        return {
            "items": [
                {
                    "object_key": ref.object_key,
                    "content_sha256": ref.content_sha256,
                    "size_bytes": ref.size_bytes,
                    "mime_type": ref.mime_type,
                    "source_backend": ref.source_backend,
                    "referenced_by": ref.referenced_by,
                    "soft_deleted_at": ref.soft_deleted_at.isoformat() if ref.soft_deleted_at else None,
                    "soft_delete_reason": ref.soft_delete_reason,
                    "last_verified_at": ref.last_verified_at.isoformat() if ref.last_verified_at else None,
                    "last_verify_status": ref.last_verify_status,
                }
                for ref in items
            ],
            "limit": limit,
            "offset": offset,
        }


# 单例
storage_admin_service = StorageAdminService()
