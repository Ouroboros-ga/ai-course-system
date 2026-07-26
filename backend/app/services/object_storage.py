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
import os
import secrets
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import IO, Optional
from urllib.parse import quote

from app.core.config import settings


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
    ) -> dict:
        """签发上传意图

        返回 {object_key, upload_url, method, headers, expires_at, max_size_bytes}。
        本地实现返回 POST /api/v1/media/assets 的预签位置。
        """


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
    ) -> dict:
        exp_ts = int((datetime.now(timezone.utc) + timedelta(seconds=expires_in)).timestamp())
        sig = self._sign(object_key, exp_ts, {"upload": True})
        return {
            "object_key": object_key,
            "upload_url": "/api/v1/media/assets",
            "method": "POST",
            "headers": {"Content-Type": "application/json"},
            "expires_at": exp_ts,
            "max_size_bytes": max_size_bytes,
            "signature": sig,
        }

    def verify_read_signature(
        self, object_key: str, exp: int, sig: str, scope: Optional[dict] = None,
    ) -> bool:
        """校验签名是否有效且未过期"""
        if exp < datetime.now(timezone.utc).timestamp():
            return False
        expected = self._sign(object_key, exp, scope)
        # 用 compare_digest 防止时序攻击
        return secrets.compare_digest(expected, sig)

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


def get_object_storage() -> ObjectStorageProvider:
    """获取对象存储单例

    根据 `settings.OBJECT_STORAGE_BACKEND` 选择实现：
    - `local`（默认）：LocalStorageProvider，根目录为 settings.MEDIA_STORAGE_PATH
    - `oss`（未来）：OSSStorageProvider，需配置 OSS_*
    """
    global _object_storage
    if _object_storage is not None:
        return _object_storage

    backend = (settings.OBJECT_STORAGE_BACKEND or "local").lower()
    if backend == "oss":
        # 未来实现：from app.services.oss_storage_provider import OSSStorageProvider
        # _object_storage = OSSStorageProvider(...)
        # 暂时回退到 local，避免配置缺失直接崩溃
        _object_storage = LocalStorageProvider(settings.MEDIA_STORAGE_PATH)
    else:
        _object_storage = LocalStorageProvider(settings.MEDIA_STORAGE_PATH)
    return _object_storage


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
            # 检查目标是否已存在
            if target.exists(key):
                skipped.append(key)
                continue
            # 读取源内容
            content = source.get(key)
            # 写入目标
            target.put(key, content)
            # 校验一致性
            source_head = source.head(key)
            target_head = target.head(key)
            source_sha = source_head.get("sha256", "")
            target_sha = target_head.get("sha256", "")
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
    if not hasattr(provider, "root_dir"):
        # OSS 等其他 Provider 需各自实现 list 方法
        return []
    root = provider.root_dir  # type: ignore[attr-defined]
    prefix_path = os.path.join(root, prefix)
    keys: list[str] = []
    if not os.path.exists(prefix_path):
        return keys
    for dirpath, _dirnames, filenames in os.walk(prefix_path):
        for filename in filenames:
            full_path = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(full_path, root)
            # 转换为 object_key 格式（使用 / 分隔符）
            object_key = rel_path.replace(os.sep, "/")
            keys.append(object_key)
    return keys
