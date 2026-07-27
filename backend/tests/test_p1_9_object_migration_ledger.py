"""P1-9 验收测试：object_storage.py 实现可恢复任务账本+逐对象 SHA 校验

验证约束：
- ObjectMigrationLedger 持久化到 JSON 文件，记录每个 object_key 的迁移状态
- 状态机：pending → in_progress → migrated → verified（或 failed）
- 重新运行 migrate_object_keys_resumable 跳过 verified，重试 failed
- 逐对象 byte SHA 校验：source_sha256 与 target_sha256 必须一致
- 单对象失败不阻断整批
- 启动时清理上次中断的 in_progress 条目

约束来源：
- Hard Constraints: "Object storage migration must implement resumable task ledger
  with per-object migration status and byte SHA verification"
- Lessons Learned: "Synchronous batch operations for object storage migration lack
  resiliency; implement resumable task ledger"
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.services.object_storage import (
    LocalStorageProvider,
    ObjectMigrationLedger,
    migrate_object_keys_resumable,
)


@pytest.fixture
def source_provider(tmp_path: Path) -> LocalStorageProvider:
    return LocalStorageProvider(str(tmp_path / "source"))


@pytest.fixture
def target_provider(tmp_path: Path) -> LocalStorageProvider:
    return LocalStorageProvider(str(tmp_path / "target"))


@pytest.fixture
def ledger(tmp_path: Path) -> ObjectMigrationLedger:
    return ObjectMigrationLedger(str(tmp_path / "ledger" / "migration.json"))


class TestObjectMigrationLedger:
    """测试1: 账本基础读写"""

    def test_empty_ledger_when_file_missing(self, tmp_path: Path) -> None:
        ledger = ObjectMigrationLedger(str(tmp_path / "nonexistent.json"))
        assert ledger.summary()["total"] == 0

    def test_mark_pending_persists_to_disk(self, tmp_path: Path) -> None:
        ledger_path = tmp_path / "ledger" / "m.json"
        ledger = ObjectMigrationLedger(str(ledger_path))
        ledger.mark_pending("avatars/u_1/portrait.mp4", source_sha256="sha_src")

        # 重新加载，数据持久化
        ledger2 = ObjectMigrationLedger(str(ledger_path))
        entry = ledger2.get("avatars/u_1/portrait.mp4")
        assert entry is not None
        assert entry["status"] == "pending"
        assert entry["source_sha256"] == "sha_src"

    def test_status_transitions(self, tmp_path: Path) -> None:
        ledger = ObjectMigrationLedger(str(tmp_path / "m.json"))
        ledger.mark_pending("k1")
        assert ledger.status("k1") == "pending"

        ledger.mark_in_progress("k1", source_sha256="sha")
        assert ledger.status("k1") == "in_progress"
        # mark_in_progress 应自增 attempts
        assert ledger.get("k1")["attempts"] == 1

        ledger.mark_verified("k1")
        assert ledger.status("k1") == "verified"

    def test_mark_failed_records_error(self, tmp_path: Path) -> None:
        ledger = ObjectMigrationLedger(str(tmp_path / "m.json"))
        ledger.mark_pending("k2")
        ledger.mark_failed("k2", error="network timeout")
        entry = ledger.get("k2")
        assert entry["status"] == "failed"
        assert "network timeout" in entry["last_error"]

    def test_reset_in_progress_to_pending(self, tmp_path: Path) -> None:
        ledger = ObjectMigrationLedger(str(tmp_path / "m.json"))
        ledger.mark_pending("k1")
        ledger.mark_pending("k2")
        ledger.mark_in_progress("k1")
        # 模拟中断：k1 仍是 in_progress
        assert ledger.status("k1") == "in_progress"

        # 重新加载（模拟重启）
        ledger2 = ObjectMigrationLedger(str(tmp_path / "m.json"))
        reset_count = ledger2.reset_in_progress_to_pending()
        assert reset_count == 1
        assert ledger2.status("k1") == "pending"

    def test_summary_counts_by_status(self, tmp_path: Path) -> None:
        ledger = ObjectMigrationLedger(str(tmp_path / "m.json"))
        ledger.mark_pending("k1")
        ledger.mark_pending("k2")
        ledger.mark_pending("k3")
        ledger.mark_verified("k2")
        ledger.mark_failed("k3", error="x")
        summary = ledger.summary()
        assert summary["pending"] == 1
        assert summary["verified"] == 1
        assert summary["failed"] == 1
        assert summary["total"] == 3

    def test_corrupted_ledger_does_not_block(self, tmp_path: Path) -> None:
        """损坏的账本文件不阻断迁移；从空账本开始"""
        ledger_path = tmp_path / "m.json"
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        ledger_path.write_text("not valid json {{{", encoding="utf-8")
        ledger = ObjectMigrationLedger(str(ledger_path))
        assert ledger.summary()["total"] == 0


class TestMigrateResumableBasic:
    """测试2: 基本迁移流程"""

    def test_migrate_single_object_verifies_sha(
        self, source_provider, target_provider, ledger
    ) -> None:
        source_provider.put("k1", b"hello world", mime_type="text/plain")

        result = migrate_object_keys_resumable(
            source_provider, target_provider, ["k1"], ledger=ledger
        )

        assert result["processed"]["verified"] == 1
        assert result["processed"]["failed"] == 0
        assert ledger.status("k1") == "verified"
        # 目标实际写入
        assert target_provider.exists("k1")
        assert target_provider.get("k1") == b"hello world"

    def test_migrate_skips_already_verified(
        self, source_provider, target_provider, ledger
    ) -> None:
        source_provider.put("k1", b"data")
        # 第一次迁移
        migrate_object_keys_resumable(
            source_provider, target_provider, ["k1"], ledger=ledger
        )
        assert ledger.status("k1") == "verified"

        # 第二次运行：应跳过 verified
        result = migrate_object_keys_resumable(
            source_provider, target_provider, ["k1"], ledger=ledger
        )
        assert result["processed"]["skipped"] == 1
        assert result["processed"]["verified"] == 0

    def test_migrate_multiple_objects_all_verified(
        self, source_provider, target_provider, ledger
    ) -> None:
        for i in range(5):
            source_provider.put(f"k{i}", f"content_{i}".encode())

        result = migrate_object_keys_resumable(
            source_provider, target_provider,
            [f"k{i}" for i in range(5)],
            ledger=ledger,
        )

        assert result["processed"]["verified"] == 5
        assert result["processed"]["failed"] == 0
        for i in range(5):
            assert ledger.status(f"k{i}") == "verified"


class TestMigrateResumableShaVerification:
    """测试3: 逐对象 SHA 校验"""

    def test_sha_mismatch_marks_failed(
        self, source_provider, target_provider, ledger
    ) -> None:
        # 源写入内容
        source_provider.put("k1", b"source content")
        # 目标已存在不同内容（模拟冲突）
        target_provider.put("k1", b"different content")

        result = migrate_object_keys_resumable(
            source_provider, target_provider, ["k1"], ledger=ledger
        )

        assert result["processed"]["failed"] == 1
        assert ledger.status("k1") == "failed"
        # 错误信息包含 SHA mismatch
        entry = ledger.get("k1")
        assert "SHA" in entry["last_error"] or "different SHA" in entry["last_error"]

    def test_target_exists_same_sha_marks_verified(
        self, source_provider, target_provider, ledger
    ) -> None:
        # 源和目标都有相同内容
        source_provider.put("k1", b"same content")
        target_provider.put("k1", b"same content")

        result = migrate_object_keys_resumable(
            source_provider, target_provider, ["k1"], ledger=ledger
        )

        assert result["processed"]["verified"] == 1
        assert ledger.status("k1") == "verified"

    def test_byte_level_sha_not_just_size(
        self, source_provider, target_provider, ledger, tmp_path
    ) -> None:
        """SHA 校验是 byte 级别，而非仅 size"""
        # 两个文件大小相同但内容不同
        source_provider.put("k1", b"AAAA")
        target_provider.put("k1", b"BBBB")  # 同样 4 字节但内容不同

        result = migrate_object_keys_resumable(
            source_provider, target_provider, ["k1"], ledger=ledger
        )

        assert result["processed"]["failed"] == 1
        assert ledger.status("k1") == "failed"


class TestMigrateResumableFailureRecovery:
    """测试4: 失败恢复与重试"""

    def test_source_missing_marks_not_found(
        self, source_provider, target_provider, ledger
    ) -> None:
        result = migrate_object_keys_resumable(
            source_provider, target_provider, ["missing_key"], ledger=ledger
        )
        assert result["processed"]["not_found"] == 1
        assert ledger.status("missing_key") == "failed"
        assert "not found" in ledger.get("missing_key")["last_error"]

    def test_failed_object_can_be_retried(
        self, source_provider, target_provider, ledger
    ) -> None:
        """failed 状态的对象在重新运行时可重试"""
        source_provider.put("k1", b"content")

        # 第一次：模拟 source.get 抛异常
        original_get = source_provider.get
        source_provider.get = MagicMock(side_effect=RuntimeError("simulated read failure"))
        result1 = migrate_object_keys_resumable(
            source_provider, target_provider, ["k1"], ledger=ledger
        )
        assert result1["processed"]["failed"] == 1
        assert ledger.status("k1") == "failed"
        source_provider.get = original_get  # 恢复

        # 第二次：source.get 恢复正常，应能迁移成功
        result2 = migrate_object_keys_resumable(
            source_provider, target_provider, ["k1"], ledger=ledger
        )
        assert result2["processed"]["verified"] == 1
        assert ledger.status("k1") == "verified"

    def test_max_attempts_limit(
        self, source_provider, target_provider, ledger
    ) -> None:
        """超过 max_attempts 的对象不再重试"""
        source_provider.put("k1", b"content")
        # 模拟持续失败
        original_get = source_provider.get
        source_provider.get = MagicMock(side_effect=RuntimeError("persistent failure"))

        # 运行 5 次（max_attempts=3）
        for _ in range(5):
            migrate_object_keys_resumable(
                source_provider, target_provider, ["k1"], ledger=ledger, max_attempts=3
            )

        source_provider.get = original_get
        # 第 6 次运行：超过 max_attempts，应跳过不再尝试
        result = migrate_object_keys_resumable(
            source_provider, target_provider, ["k1"], ledger=ledger, max_attempts=3
        )
        # attempts=3 已达到上限，应记 failed 不再重试
        assert result["processed"]["failed"] >= 1
        assert ledger.get("k1")["attempts"] == 3

    def test_single_object_failure_does_not_block_batch(
        self, source_provider, target_provider, ledger
    ) -> None:
        """单对象失败不阻断整批"""
        source_provider.put("k_good", b"good content")
        source_provider.put("k_bad", b"bad content")
        # k_bad 模拟失败：让 source.get 在 k_bad 上抛异常
        original_get = source_provider.get

        def selective_get(key: str) -> bytes:
            if key == "k_bad":
                raise RuntimeError("simulated failure for k_bad")
            return original_get(key)

        source_provider.get = MagicMock(side_effect=selective_get)
        result = migrate_object_keys_resumable(
            source_provider, target_provider,
            ["k_good", "k_bad"],
            ledger=ledger,
        )
        source_provider.get = original_get

        # k_good 成功，k_bad 失败
        assert result["processed"]["verified"] == 1
        assert result["processed"]["failed"] == 1
        assert ledger.status("k_good") == "verified"
        assert ledger.status("k_bad") == "failed"


class TestMigrateResumableInterrupted:
    """测试5: 中断恢复"""

    def test_interrupted_in_progress_resets_on_restart(
        self, source_provider, target_provider, tmp_path
    ) -> None:
        """模拟迁移中断后重启：in_progress 重置为 pending 并重试"""
        source_provider.put("k1", b"content")
        ledger_path = str(tmp_path / "ledger" / "m.json")
        ledger1 = ObjectMigrationLedger(ledger_path)
        ledger1.mark_pending("k1")
        ledger1.mark_in_progress("k1", source_sha256="sha")
        # 此时进程崩溃，k1 留在 in_progress

        # 重启：新 ledger 实例加载磁盘状态
        ledger2 = ObjectMigrationLedger(ledger_path)
        assert ledger2.status("k1") == "in_progress"

        # migrate 应自动 reset_in_progress_to_pending
        result = migrate_object_keys_resumable(
            source_provider, target_provider, ["k1"], ledger=ledger2
        )
        assert result["interrupted_reset"] == 1
        assert result["processed"]["verified"] == 1
        assert ledger2.status("k1") == "verified"


class TestMigrateResumableDeleteSource:
    """测试6: delete_source 语义"""

    def test_delete_source_only_after_verified(
        self, source_provider, target_provider, ledger
    ) -> None:
        source_provider.put("k1", b"content")
        result = migrate_object_keys_resumable(
            source_provider, target_provider, ["k1"], ledger=ledger, delete_source=True
        )
        assert result["processed"]["verified"] == 1
        # verified 后源被删除
        assert not source_provider.exists("k1")
        assert target_provider.exists("k1")

    def test_delete_source_not_done_on_failure(
        self, source_provider, target_provider, ledger
    ) -> None:
        source_provider.put("k1", b"content")
        # 制造失败：target 已存在但 SHA 不同
        target_provider.put("k1", b"different content")

        result = migrate_object_keys_resumable(
            source_provider, target_provider, ["k1"], ledger=ledger, delete_source=True
        )
        assert result["processed"]["failed"] == 1
        # 失败时源不删除
        assert source_provider.exists("k1")
