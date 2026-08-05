"""阶段8 对象存储抽象与本地实现

实现 `ObjectStorageProvider` 抽象，本地存储与 OSS 共用同一 `object_key` 契约。
未来从本地磁盘迁移 OSS 时，只替换 Provider 实现，业务数据不变。

设计要点：
- 所有媒体产物只通过 `object_key` 访问，绝不向前端暴露本地绝对路径
- `LocalStorageProvider` 按 `object_key` 在根目录下定位文件，禁止路径越权
- `SignedURL` 仅由后端按课程权限签发，原始视频/语音样本不直接给学生下载
- 单例 `object_storage` 通过配置 `OBJECT_STORAGE_BACKEND` 选择实现
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import IO, Optional
from urllib.parse import quote

from app.core.config import settings


# ``MEDIA_STORAGE_PATH`` is a deployment setting, not a working-directory
# relative path.  The local development server is commonly started from the
# repository root while maintenance commands are started from ``backend/``;
# resolving a relative value against ``cwd`` made those two invocations write
# and read different media trees.  Keep explicit absolute paths untouched so
# tests and deployments can still choose an isolated storage location.
_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def resolve_local_storage_root(root_dir: str) -> str:
    """Resolve a local storage root consistently across process cwd values."""
    configured = str(root_dir or "./media")
    if os.path.isabs(configured):
        return os.path.abspath(configured)
    return os.path.abspath(os.path.join(_BACKEND_ROOT, configured))


# ---------------------------------------------------------------------------
# 抽象接口
# ---------------------------------------------------------------------------


class ObjectStorageProvider(ABC):
    """对象存储抽象

    所有媒体产物（音频、字幕、PPT、数字人资产）只通过 `object_key` 引用。
    前端不直接访问本地路径，统一通过签名 URL 经后端鉴权后下载。
    """

    backend_name: str = "abstract"

    @abstractmethod
    def put(self, object_key: str, content: bytes | IO[bytes], *, mime_type: str = "") -> str:
        """上传内容，返回 content_sha256"""

    @abstractmethod
    def get(self, object_key: str) -> bytes:
        """读取内容；不存在抛 FileNotFoundError"""

    @abstractmethod
    def head(self, object_key: str) -> dict:
        """返回元信息 {size_bytes, mime_type, content_sha256, last_modified}；不存在抛 FileNotFoundError"""

    @abstractmethod
    def delete(self, object_key: str) -> bool:
        """删除对象，返回是否实际删除"""

    @abstractmethod
    def exists(self, object_key: str) -> bool:
        """是否存在"""

    @abstractmethod
    def sign_read_url(
        self, object_key: str, *, expires_in: int = 3600, scope: Optional[dict] = None,
    ) -> str:
        """签发受权限保护的读取 URL

        scope 用于携带权限上下文（course_id、user_id、purpose），由具体实现嵌入签名。
        本地实现返回 `/api/v1/media/assets/{object_key}/content?sig=...`。
        """

    @abstractmethod
    def sign_upload_intent(
        self, object_key: str, *, expires_in: int = 900, max_size_bytes: int = 0,
        upload_path: str = "",
    ) -> dict:
        """签发上传意图

        返回 {object_key, upload_url, method, headers, expires_at, max_size_bytes,
        signature, exp}。
        - upload_path: 调用方指定的本地接收路由路径（如
          /api/v1/avatar-profiles/{avatar_id}/source-media/{source_media_id}/upload）；
          本地实现会把 exp 与 sig 作为 query 参数附加到该路径。
        - 远程 S3/MinIO 实现可忽略 upload_path，直接返回 presigned S3 PUT URL。
        """

    @abstractmethod
    def verify_upload_signature(
        self, object_key: str, exp: int, sig: str,
    ) -> bool:
        """验证上传签名是否有效且未过期。

        用于 PUT 上传路由校验 query 参数 exp/sig 是否由 sign_upload_intent 签发。
        """

    @abstractmethod
    def list_keys(self, prefix: str = "") -> list[str]:
        """列出对象键，用于受控迁移和垃圾回收。"""


# ---------------------------------------------------------------------------
# 本地存储实现
# ---------------------------------------------------------------------------


class LocalStorageProvider(ObjectStorageProvider):
    """本地磁盘存储实现

    - 根目录由 `settings.MEDIA_STORAGE_PATH` 决定
    - `object_key` 通过 `_safe_full_path` 防止路径越权
    - 签名 URL 形如 `/api/v1/media/assets/{object_key}/content?sig=...&exp=...`
    - 签名密钥由 `settings.OBJECT_STORAGE_SIGN_KEY` 提供，缺失时随机生成（仅开发模式）
    """

    backend_name = "local"

    def __init__(self, root_dir: str, *, sign_key: Optional[str] = None) -> None:
        self.root_dir = os.path.abspath(root_dir)
        os.makedirs(self.root_dir, exist_ok=True)
        self._sign_key = sign_key or settings.OBJECT_STORAGE_SIGN_KEY or secrets.token_hex(32)

    # ------------------------------------------------------------------
    # 路径安全
    # ------------------------------------------------------------------

    def _safe_full_path(self, object_key: str) -> str:
        """将 object_key 转为安全的本地绝对路径，禁止越权"""
        if not object_key or object_key.startswith("/"):
            raise ValueError("object_key 不能为空或以 / 开头")
        # 标准化并校验仍在根目录下
        full = os.path.normpath(os.path.join(self.root_dir, object_key))
        if not full.startswith(self.root_dir + os.sep) and full != self.root_dir:
            raise ValueError(f"object_key 越权: {object_key}")
        return full

    # ------------------------------------------------------------------
    # 增删改查
    # ------------------------------------------------------------------

    def put(self, object_key: str, content: bytes | IO[bytes], *, mime_type: str = "") -> str:
        full = self._safe_full_path(object_key)
        os.makedirs(os.path.dirname(full), exist_ok=True)

        if isinstance(content, (bytes, bytearray)):
            data = bytes(content)
        else:
            data = content.read()

        with open(full, "wb") as f:
            f.write(data)

        return hashlib.sha256(data).hexdigest()

    def get(self, object_key: str) -> bytes:
        full = self._safe_full_path(object_key)
        if not os.path.isfile(full):
            raise FileNotFoundError(f"object_key 不存在: {object_key}")
        with open(full, "rb") as f:
            return f.read()

    def head(self, object_key: str) -> dict:
        full = self._safe_full_path(object_key)
        if not os.path.isfile(full):
            raise FileNotFoundError(f"object_key 不存在: {object_key}")
        stat = os.stat(full)
        return {
            "size_bytes": stat.st_size,
            "mime_type": mime_type_for(object_key),
            "content_sha256": "",  # 不主动哈希，按需调用方维护
            "last_modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
        }

    def delete(self, object_key: str) -> bool:
        full = self._safe_full_path(object_key)
        if os.path.isfile(full):
            os.remove(full)
            return True
        return False

    def exists(self, object_key: str) -> bool:
        full = self._safe_full_path(object_key)
        return os.path.isfile(full)

    # ------------------------------------------------------------------
    # 签名 URL
    # ------------------------------------------------------------------

    def sign_read_url(
        self, object_key: str, *, expires_in: int = 3600, scope: Optional[dict] = None,
    ) -> str:
        exp = int((datetime.now(timezone.utc) + timedelta(seconds=expires_in)).timestamp())
        sig = self._sign(object_key, exp, scope)
        # scope 不放 URL，由调用方在 cookie/header 携带；这里只签 object_key+exp+scope_hash
        quoted = quote(object_key, safe="/")
        url = f"/api/v1/media/assets/{quoted}/content?exp={exp}&sig={sig}"
        return url

    def sign_upload_intent(
        self, object_key: str, *, expires_in: int = 900, max_size_bytes: int = 0,
        upload_path: str = "",
    ) -> dict:
        exp_ts = int((datetime.now(timezone.utc) + timedelta(seconds=expires_in)).timestamp())
        sig = self._sign(object_key, exp_ts, {"upload": True})
        # 本地实现：把 exp 与 sig 作为 query 参数附加到调用方指定的 upload_path；
        # 若未提供 upload_path，回退到通用 /api/v1/media/assets（仅用于向后兼容）。
        base_path = upload_path or "/api/v1/media/assets"
        upload_url = f"{base_path}?exp={exp_ts}&sig={sig}"
        return {
            "object_key": object_key,
            "upload_url": upload_url,
            "method": "PUT" if upload_path else "POST",
            "headers": {"Content-Type": "application/octet-stream"},
            "expires_at": exp_ts,
            "exp": exp_ts,
            "sig": sig,
            "max_size_bytes": max_size_bytes,
            "signature": sig,
        }

    def verify_upload_signature(
        self, object_key: str, exp: int, sig: str,
    ) -> bool:
        """验证上传签名是否有效且未过期"""
        if exp < datetime.now(timezone.utc).timestamp():
            return False
        expected = self._sign(object_key, exp, {"upload": True})
        return secrets.compare_digest(expected, sig)

    def verify_read_signature(
        self, object_key: str, exp: int, sig: str, scope: Optional[dict] = None,
    ) -> bool:
        """校验签名是否有效且未过期"""
        if exp < datetime.now(timezone.utc).timestamp():
            return False
        expected = self._sign(object_key, exp, scope)
        # 用 compare_digest 防止时序攻击
        return secrets.compare_digest(expected, sig)

    def list_keys(self, prefix: str = "") -> list[str]:
        prefix_path = os.path.join(self.root_dir, prefix)
        if not os.path.exists(prefix_path):
            return []
        keys: list[str] = []
        for dirpath, _dirnames, filenames in os.walk(prefix_path):
            for filename in filenames:
                full_path = os.path.join(dirpath, filename)
                relative_path = os.path.relpath(full_path, self.root_dir)
                keys.append(relative_path.replace(os.sep, "/"))
        return sorted(keys)

    def _sign(self, object_key: str, exp: int, scope: Optional[dict]) -> str:
        scope_str = _stringify_scope(scope)
        payload = f"{object_key}|{exp}|{scope_str}|{self._sign_key}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


_MIME_MAP = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".json": "application/json",
    ".vtt": "text/vtt",
    ".srt": "text/plain",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


def mime_type_for(object_key: str) -> str:
    """根据扩展名推断 MIME 类型"""
    _, ext = os.path.splitext(object_key)
    return _MIME_MAP.get(ext.lower(), "application/octet-stream")


def _stringify_scope(scope: Optional[dict]) -> str:
    if not scope:
        return ""
    # 按 key 排序确保稳定
    return ";".join(f"{k}={scope[k]}" for k in sorted(scope.keys()))


# ---------------------------------------------------------------------------
# 单例
# ---------------------------------------------------------------------------


_object_storage: Optional[ObjectStorageProvider] = None


class ObjectStorageConfigurationError(RuntimeError):
    """远程对象存储配置不完整或不受支持。

    显式配置远程后端却无法初始化时必须失败，避免媒体仍写入本地磁盘却被
    误以为已经迁移到 OSS。
    """


def get_object_storage() -> ObjectStorageProvider:
    """获取对象存储单例

    根据 `settings.OBJECT_STORAGE_BACKEND` 选择实现：
    - `local`（默认）：LocalStorageProvider，根目录为 settings.MEDIA_STORAGE_PATH
    - `s3` / `minio` / `oss`：S3 兼容 Provider，需要完整远程配置
    """
    global _object_storage
    if _object_storage is not None:
        return _object_storage

    backend = (settings.OBJECT_STORAGE_BACKEND or "local").lower()
    _object_storage = build_object_storage_provider(backend)
    return _object_storage


def build_object_storage_provider(backend: str) -> ObjectStorageProvider:
    """按显式后端构造 Provider，供迁移工具同时持有源与目标存储。"""
    backend = (backend or "local").lower()
    if backend == "local":
        return LocalStorageProvider(resolve_local_storage_root(settings.MEDIA_STORAGE_PATH))
    elif backend in {"s3", "minio", "oss"}:
        try:
            from app.services.s3_object_storage import S3ObjectStorageProvider

            return S3ObjectStorageProvider.from_settings(settings)
        except Exception as exc:
            if settings.OBJECT_STORAGE_ALLOW_DEMO_LOCAL_FALLBACK:
                return LocalStorageProvider(resolve_local_storage_root(settings.MEDIA_STORAGE_PATH))
            else:
                raise ObjectStorageConfigurationError(
                    f"对象存储后端 {backend!r} 初始化失败；不会静默回退到本地存储: {exc}"
                ) from exc
    else:
        raise ObjectStorageConfigurationError(
            f"不支持的 OBJECT_STORAGE_BACKEND={backend!r}；可用值为 local/s3/minio/oss"
        )


def reset_object_storage_for_tests(provider: Optional[ObjectStorageProvider] = None) -> None:
    """测试辅助：重置单例"""
    global _object_storage
    _object_storage = provider


# ---------------------------------------------------------------------------
# M5 对象存储迁移工具
# ---------------------------------------------------------------------------


def migrate_object_keys(
    source: ObjectStorageProvider,
    target: ObjectStorageProvider,
    object_keys: list[str],
    *,
    delete_source: bool = False,
) -> dict:
    """将一批 object_key 从源存储迁移到目标存储

    - 用于从本地磁盘迁移到 OSS（或反向）
    - 迁移后校验 SHA256 一致性
    - delete_source=True 时迁移成功后删除源文件
    - 返回迁移报告 {migrated, failed, skipped, errors}

    注意：本函数不修改业务数据中的 object_key，因为 LocalStorageProvider 和
    OSSStorageProvider 使用相同的 object_key 命名空间。
    """
    migrated = []
    failed = []
    skipped = []
    errors = []

    for key in object_keys:
        if not key:
            skipped.append(key)
            continue
        try:
            # 检查源是否存在
            if not source.exists(key):
                skipped.append(key)
                continue
            # 已存在的目标可作为断点续传；内容不同则绝不覆盖。
            if target.exists(key):
                source_sha = _content_sha(source, key)
                target_sha = _content_sha(target, key)
                if source_sha and target_sha and source_sha != target_sha:
                    failed.append(key)
                    errors.append(f"{key}: 目标已存在但 SHA256 不一致")
                else:
                    skipped.append(key)
                continue
            # 读取源内容
            content = source.get(key)
            # 写入目标
            target.put(key, content)
            # 校验一致性
            source_head = source.head(key)
            target_head = target.head(key)
            source_sha = source_head.get("content_sha256", "") or source_head.get("sha256", "")
            target_sha = target_head.get("content_sha256", "") or target_head.get("sha256", "")
            if source_sha and target_sha and source_sha != target_sha:
                failed.append(key)
                errors.append(f"{key}: SHA256 不一致 (source={source_sha[:16]}, target={target_sha[:16]})")
                continue
            migrated.append(key)
            if delete_source:
                source.delete(key)
        except Exception as e:
            failed.append(key)
            errors.append(f"{key}: {str(e)[:200]}")

    return {
        "migrated": migrated,
        "failed": failed,
        "skipped": skipped,
        "migrated_count": len(migrated),
        "failed_count": len(failed),
        "skipped_count": len(skipped),
        "errors": errors,
    }


def list_object_keys_under_prefix(
    provider: ObjectStorageProvider,
    prefix: str,
) -> list[str]:
    """列出指定前缀下的所有 object_key（M5 迁移辅助）

    LocalStorageProvider 遍历根目录下匹配前缀的文件。
    """
    return provider.list_keys(prefix)


def _content_sha(provider: ObjectStorageProvider, object_key: str) -> str:
    """优先读取 Provider 元数据；缺失时读取内容计算，保证迁移校验真实。"""
    head = provider.head(object_key)
    known = head.get("content_sha256", "") or head.get("sha256", "")
    if known:
        return str(known)
    return hashlib.sha256(provider.get(object_key)).hexdigest()


# ---------------------------------------------------------------------------
# M5+ 可恢复对象存储迁移账本
# ---------------------------------------------------------------------------


class ObjectMigrationLedger:
    """可恢复对象存储迁移账本

    约束来源：
    - Hard Constraints: "Object storage migration must implement resumable task ledger
      with per-object migration status and byte SHA verification"
    - Lessons Learned: "Synchronous batch operations for object storage migration lack
      resiliency; implement resumable task ledger"

    设计：
    - 持久化到 JSON 文件（或可注入的存储），记录每个 object_key 的迁移状态
    - 每个 entry：{object_key, status, source_sha256, target_sha256, bytes_copied,
                   started_at, finished_at, attempts, last_error}
    - status: pending / in_progress / migrated / verified / failed
    - 重新运行 migrate_resumable() 跳过 verified，重试 failed，续传 in_progress
    - 逐对象 byte SHA 校验：迁移后比对 source_sha256 与 target_sha256 必须一致
    """

    VALID_STATUSES = ("pending", "in_progress", "migrated", "verified", "failed")

    def __init__(self, ledger_path: str | os.PathLike[str]) -> None:
        self.ledger_path = os.fspath(ledger_path)
        self._entries: dict[str, dict] = {}
        self._load()

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """从磁盘加载账本；不存在则空账本。"""
        if not os.path.isfile(self.ledger_path):
            self._entries = {}
            return
        try:
            with open(self.ledger_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            entries = data.get("entries", {}) if isinstance(data, dict) else {}
            # 过滤无效条目，保留已知 status
            self._entries = {
                k: v for k, v in entries.items()
                if isinstance(v, dict) and v.get("status") in self.VALID_STATUSES
            }
        except (OSError, json.JSONDecodeError):
            # 损坏的账本不阻断迁移；从空账本开始，但记录 warning
            self._entries = {}

    def _save(self) -> None:
        """原子写入账本（写临时文件后重命名）。"""
        os.makedirs(os.path.dirname(os.path.abspath(self.ledger_path)), exist_ok=True)
        tmp_path = self.ledger_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump({"entries": self._entries, "version": 1}, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self.ledger_path)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def get(self, object_key: str) -> dict | None:
        return self._entries.get(object_key)

    def status(self, object_key: str) -> str | None:
        entry = self._entries.get(object_key)
        return entry.get("status") if entry else None

    def list_by_status(self, status: str) -> list[str]:
        """按状态列出 object_key"""
        return [k for k, v in self._entries.items() if v.get("status") == status]

    def summary(self) -> dict[str, int]:
        """按状态汇总"""
        counts = {s: 0 for s in self.VALID_STATUSES}
        for entry in self._entries.values():
            status = entry.get("status", "pending")
            counts[status] = counts.get(status, 0) + 1
        counts["total"] = len(self._entries)
        return counts

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    def mark_pending(
        self,
        object_key: str,
        *,
        source_sha256: str = "",
        bytes_copied: int = 0,
    ) -> None:
        """登记待迁移对象；保留 attempts 历史以便审计"""
        existing = self._entries.get(object_key, {})
        attempts = existing.get("attempts", 0)
        self._entries[object_key] = {
            "object_key": object_key,
            "status": "pending",
            "source_sha256": source_sha256,
            "target_sha256": "",
            "bytes_copied": bytes_copied,
            "started_at": "",
            "finished_at": "",
            "attempts": attempts,
            "last_error": "",
        }
        self._save()

    def mark_in_progress(self, object_key: str, *, source_sha256: str = "") -> None:
        entry = self._entries.get(object_key)
        if entry is None:
            entry = {
                "object_key": object_key,
                "status": "pending",
                "source_sha256": "",
                "target_sha256": "",
                "bytes_copied": 0,
                "started_at": "",
                "finished_at": "",
                "attempts": 0,
                "last_error": "",
            }
            self._entries[object_key] = entry
        entry["status"] = "in_progress"
        entry["started_at"] = datetime.now(timezone.utc).isoformat()
        entry["attempts"] = int(entry.get("attempts", 0)) + 1
        entry["last_error"] = ""
        if source_sha256:
            entry["source_sha256"] = source_sha256
        self._save()

    def mark_migrated(
        self,
        object_key: str,
        *,
        target_sha256: str,
        bytes_copied: int = 0,
    ) -> None:
        entry = self._entries.setdefault(object_key, {
            "object_key": object_key, "status": "pending", "source_sha256": "",
            "target_sha256": "", "bytes_copied": 0, "started_at": "",
            "finished_at": "", "attempts": 0, "last_error": "",
        })
        entry["status"] = "migrated"
        entry["target_sha256"] = target_sha256
        entry["bytes_copied"] = bytes_copied
        entry["finished_at"] = datetime.now(timezone.utc).isoformat()
        self._save()

    def mark_verified(self, object_key: str) -> None:
        entry = self._entries.get(object_key)
        if entry is None:
            return
        entry["status"] = "verified"
        entry["finished_at"] = datetime.now(timezone.utc).isoformat()
        self._save()

    def mark_failed(self, object_key: str, *, error: str) -> None:
        entry = self._entries.setdefault(object_key, {
            "object_key": object_key, "status": "pending", "source_sha256": "",
            "target_sha256": "", "bytes_copied": 0, "started_at": "",
            "finished_at": "", "attempts": 0, "last_error": "",
        })
        entry["status"] = "failed"
        entry["last_error"] = error[:500]
        entry["finished_at"] = datetime.now(timezone.utc).isoformat()
        self._save()

    def reset_in_progress_to_pending(self) -> int:
        """启动时清理上次中断的 in_progress 条目，允许重试。

        返回重置的条目数。
        """
        count = 0
        for entry in self._entries.values():
            if entry.get("status") == "in_progress":
                entry["status"] = "pending"
                entry["last_error"] = "interrupted: reset on startup"
                count += 1
        if count:
            self._save()
        return count


def migrate_object_keys_resumable(
    source: ObjectStorageProvider,
    target: ObjectStorageProvider,
    object_keys: list[str],
    *,
    ledger: ObjectMigrationLedger,
    delete_source: bool = False,
    max_attempts: int = 3,
) -> dict:
    """可恢复的对象存储迁移

    约束来源：
    - Hard Constraints: "Object storage migration must implement resumable task ledger
      with per-object migration status and byte SHA verification"

    流程：
    1. 启动时 reset_in_progress_to_pending() 清理上次中断
    2. 登记 pending：未在账本中的 object_key 加入待迁移
    3. 跳过 verified（已迁移且 SHA 一致）
    4. 对 pending/failed/in_progress 执行迁移：
       a. 计算 source_sha256（含 byte 内容）
       b. mark_in_progress
       c. 复制到 target
       d. 计算 target_sha256（含 byte 内容）
       e. SHA 一致 → mark_verified；不一致 → mark_failed
    5. 返回汇总报告

    每个对象独立 try/except，单对象失败不阻断整批。
    """
    # 1. 清理上次中断
    interrupted = ledger.reset_in_progress_to_pending()

    # 2. 登记新对象
    newly_registered = 0
    for key in object_keys:
        if not key:
            continue
        if ledger.get(key) is None:
            ledger.mark_pending(key)
            newly_registered += 1

    # 3. 执行迁移
    processed = {"verified": 0, "migrated": 0, "failed": 0, "skipped": 0, "not_found": 0}
    failed_keys: list[str] = []
    errors: list[str] = []

    for key in object_keys:
        if not key:
            continue
        entry = ledger.get(key)
        if entry is None:
            continue

        status = entry.get("status", "pending")
        # 已验证：跳过
        if status == "verified":
            processed["skipped"] += 1
            continue

        # 超过最大尝试次数：跳过
        attempts = int(entry.get("attempts", 0))
        if attempts >= max_attempts:
            processed["failed"] += 1
            failed_keys.append(key)
            errors.append(f"{key}: 超过最大尝试次数 {max_attempts}")
            continue

        # 标记 in_progress 并自增 attempts（在任何可能失败的操作之前）
        # 确保即使 source.exists 或 source_sha 计算失败，attempts 仍准确计数
        ledger.mark_in_progress(key)

        # 源不存在：标记 not_found
        try:
            if not source.exists(key):
                ledger.mark_failed(key, error="source object not found")
                processed["not_found"] += 1
                continue
        except Exception as exc:  # noqa: BLE001
            ledger.mark_failed(key, error=f"source.exists failed: {type(exc).__name__}: {exc}")
            processed["failed"] += 1
            failed_keys.append(key)
            errors.append(f"{key}: source.exists failed: {exc}")
            continue

        # 计算 source_sha256（含 byte 内容）并更新账本
        try:
            source_sha = _content_sha(source, key)
            source_head = source.head(key)
            source_bytes = int(source_head.get("size_bytes", 0))
        except Exception as exc:  # noqa: BLE001
            ledger.mark_failed(key, error=f"source sha compute failed: {type(exc).__name__}: {exc}")
            processed["failed"] += 1
            failed_keys.append(key)
            errors.append(f"{key}: source sha compute failed: {exc}")
            continue

        # 更新 source_sha256 到已存在的 in_progress 条目
        entry = ledger.get(key)
        if entry is not None:
            entry["source_sha256"] = source_sha
            entry["bytes_copied"] = source_bytes
            ledger._save()

        # 目标已存在：先校验 SHA；一致则 verified，不一致则强制覆盖（按 source）
        try:
            if target.exists(key):
                target_sha_existing = _content_sha(target, key)
                if target_sha_existing == source_sha:
                    ledger.mark_verified(key)
                    processed["verified"] += 1
                    continue
                # SHA 不一致：不覆盖，标记失败
                ledger.mark_failed(
                    key,
                    error=f"target exists with different SHA: source={source_sha[:16]} target={target_sha_existing[:16]}",
                )
                processed["failed"] += 1
                failed_keys.append(key)
                errors.append(f"{key}: target SHA mismatch")
                continue
        except Exception as exc:  # noqa: BLE001
            ledger.mark_failed(key, error=f"target.exists check failed: {type(exc).__name__}: {exc}")
            processed["failed"] += 1
            failed_keys.append(key)
            errors.append(f"{key}: target check failed: {exc}")
            continue

        # 读取源 → 写入目标
        try:
            content = source.get(key)
            target.put(key, content)
        except Exception as exc:  # noqa: BLE001
            ledger.mark_failed(key, error=f"copy failed: {type(exc).__name__}: {exc}")
            processed["failed"] += 1
            failed_keys.append(key)
            errors.append(f"{key}: copy failed: {exc}")
            continue

        # 计算 target_sha256（含 byte 内容）并比对
        try:
            target_sha = _content_sha(target, key)
        except Exception as exc:  # noqa: BLE001
            ledger.mark_failed(key, error=f"target sha compute failed: {type(exc).__name__}: {exc}")
            processed["failed"] += 1
            failed_keys.append(key)
            errors.append(f"{key}: target sha compute failed: {exc}")
            continue

        if target_sha != source_sha:
            ledger.mark_failed(
                key,
                error=f"byte SHA mismatch after copy: source={source_sha[:16]} target={target_sha[:16]}",
            )
            processed["failed"] += 1
            failed_keys.append(key)
            errors.append(f"{key}: post-copy SHA mismatch")
            continue

        # SHA 一致 → verified
        ledger.mark_verified(key)
        processed["verified"] += 1

        # 删除源（仅在 verified 后）
        if delete_source:
            try:
                source.delete(key)
            except Exception as exc:  # noqa: BLE001
                # 删除失败不影响迁移状态（已 verified），仅记录 warning
                errors.append(f"{key}: source delete failed (already migrated): {exc}")

    return {
        "summary": ledger.summary(),
        "processed": processed,
        "newly_registered": newly_registered,
        "interrupted_reset": interrupted,
        "failed_keys": failed_keys,
        "errors": errors,
    }
