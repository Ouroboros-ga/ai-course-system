"""DK4 增量规划、取消/重试与范围校验验收测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlmodel import select

from app.models.discipline_knowledge_model import (
    DisciplineDocumentVersion,
    DisciplineWorkItem,
)
from app.services.discipline_knowledge import builds as build_svc
from app.services.discipline_knowledge import work_items as item_svc
from app.services.discipline_knowledge.ingest import ingest_document

DOC_A = (
    "合成增量文档甲：栈是后进先出表，压栈弹栈均为常数时间。"
    "队列是先进先出表，循环队列取模回绕。"
)
DOC_B = (
    "合成增量文档乙：二分查找要求搜索空间有序，每次比较缩小一半区间。"
    "时间复杂度为对数级别。"
)


def _write_manifest(tmp_path: Path, name: str, texts: list[str]) -> str:
    documents = [{
        "source_kind": "textbook",
        "external_id": f"synth-inc-{name}-{i}",
        "source_family_id": f"synth-inc-{name}",
        "version": "v1",
        "domains": ["data_structures"],
        "license_code": "CC-BY-SA-4.0",
        "text": text,
    } for i, text in enumerate(texts)]
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps({"documents": documents}, ensure_ascii=False),
                    encoding="utf-8")
    return str(path)


def test_create_build_and_initial_items(session, tmp_path):
    manifest = _write_manifest(tmp_path, "b1", [DOC_A, DOC_B])
    created = build_svc.create_build(
        session, owner_user_id=1, scope={"manifest_path": manifest})
    assert created["created"] is True
    assert created["planned_chunks"] == 2
    view = build_svc.get_build(session, created["build_id"])
    assert view["status"] == "queued"
    assert view["stages"] == ["resolve", "verify", "adjudicate"]
    # worker 靠 scope 取文本：get_build 必须带回 scope（回归：缺失曾致 TEXT_UNAVAILABLE）
    assert view["scope"]["manifest_path"] == manifest
    assert view["items_total"] == 6
    assert view["items_by_status"] == {"pending": 6}
    assert view["task_id"]


def test_create_build_idempotent(session, tmp_path):
    manifest = _write_manifest(tmp_path, "b2", [DOC_A])
    first = build_svc.create_build(
        session, owner_user_id=3, scope={"manifest_path": manifest})
    second = build_svc.create_build(
        session, owner_user_id=3, scope={"manifest_path": manifest})
    assert second["created"] is False
    assert second["build_id"] == first["build_id"]
    view = build_svc.get_build(session, first["build_id"])
    assert view["items_total"] == 3


def test_plan_delta_only_new_doc(session, tmp_path):
    manifest = _write_manifest(tmp_path, "b3", [DOC_A])
    created = build_svc.create_build(
        session, owner_user_id=4, scope={"manifest_path": manifest})
    build_id = created["build_id"]
    old_chunk = session.exec(
        select(DisciplineWorkItem.chunk_id).where(
            DisciplineWorkItem.build_id == build_id)
    ).first()
    before = session.exec(
        select(DisciplineWorkItem).where(
            DisciplineWorkItem.build_id == build_id,
            DisciplineWorkItem.chunk_id == old_chunk)
    ).all()
    assert len(before) == 3

    new_version = ingest_document(session, {
        "source_kind": "textbook", "external_id": "synth-inc-b3-new",
        "source_family_id": "synth-inc-b3", "language": "zh",
        "domains": ["data_structures"], "license_code": "CC-BY-SA-4.0",
        "text": DOC_B,
    })["version_id"]
    delta = build_svc.plan_delta(session, new_version, build_id)
    assert len(delta) == 1
    assert delta[0] != old_chunk
    # 旧 chunk 的工作项数不变（同 fingerprint 复用，不重复建项）
    after = session.exec(
        select(DisciplineWorkItem).where(
            DisciplineWorkItem.build_id == build_id,
            DisciplineWorkItem.chunk_id == old_chunk)
    ).all()
    assert len(after) == 3
    # 重跑 plan_delta 不新增
    assert build_svc.plan_delta(session, new_version, build_id) == delta
    total = session.exec(
        select(DisciplineWorkItem).where(DisciplineWorkItem.build_id == build_id)
    ).all()
    assert len(total) == 6


def test_withdrawn_version_cancels_pending(session, tmp_path):
    manifest = _write_manifest(tmp_path, "b4", [DOC_A])
    created = build_svc.create_build(
        session, owner_user_id=5, scope={"manifest_path": manifest})
    build_id = created["build_id"]
    version = session.exec(select(DisciplineDocumentVersion)).all()
    version_id = next(
        v.version_id for v in version if v.external_id == "synth-inc-b4-0")
    version_row = session.exec(
        select(DisciplineDocumentVersion).where(
            DisciplineDocumentVersion.version_id == version_id)
    ).one()
    version_row.status = "withdrawn"
    session.add(version_row)
    session.commit()
    assert build_svc.plan_delta(session, version_id, build_id) == []
    items = session.exec(
        select(DisciplineWorkItem).where(DisciplineWorkItem.build_id == build_id)
    ).all()
    assert items and {i.status for i in items} == {"cancelled"}


def test_cancel_and_retry_reuses_completed(session, tmp_path):
    manifest = _write_manifest(tmp_path, "b5", [DOC_A])
    created = build_svc.create_build(
        session, owner_user_id=6, scope={"manifest_path": manifest},
        stages=["resolve"])
    build_id = created["build_id"]
    build_svc.start_build(session, build_id)
    from app.core.time_utils import utcnow_aware

    claimed = item_svc.claim_item(session, "w1", utcnow_aware(), 180)
    assert claimed is not None
    assert item_svc.complete_item(session, claimed["item_id"],
                                  claimed["lease_token"], "{}") is True
    cancelled = build_svc.cancel_build(session, build_id, reason="test cancel")
    assert cancelled["status"] == "cancelled"
    # 取消后无新认领
    assert item_svc.claim_item(session, "w1", utcnow_aware(), 180) is None
    retried = build_svc.retry_build(session, build_id)
    assert retried["status"] == "queued"
    view = build_svc.get_build(session, build_id)
    # 已完成产物保留（succeeded 不动），其余回到 pending
    assert view["items_by_status"].get("succeeded", 0) == 1
    assert view["items_by_status"].get("pending", 0) == view["items_total"] - 1


def test_validate_build_scope(tmp_path):
    # 离线检查不产生任何变更：缺失清单时目录保持为空
    missing = build_svc.validate_build_scope(
        {"manifest_path": str(tmp_path / "absent.json"), "max_chunks": 10})
    assert missing["source_manifest_valid"] is False
    assert missing["error_code"] == "SOURCE_UNAVAILABLE"
    assert list(tmp_path.iterdir()) == []

    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    report = build_svc.validate_build_scope(
        {"manifest_path": str(bad), "max_chunks": 10})
    assert report["source_manifest_valid"] is False
    assert report["error_code"] == "SCHEMA_INVALID"

    manifest = _write_manifest(tmp_path, "b6", [DOC_A, DOC_B])
    report = build_svc.validate_build_scope(
        {"manifest_path": manifest, "max_chunks": 10})
    assert report["source_manifest_valid"] is True
    assert report["document_count"] == 2
    assert report["estimated_chunks"] == 2
    assert report["estimated_tokens"] > 0


def test_unsupported_stage_rejected(session, tmp_path):
    manifest = _write_manifest(tmp_path, "b7", [DOC_A])
    with pytest.raises(build_svc.DisciplineBuildError) as exc_info:
        build_svc.create_build(
            session, owner_user_id=8, scope={"manifest_path": manifest},
            stages=["extract"])
    assert exc_info.value.error_code == "STAGE_DEFERRED"
