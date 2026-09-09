"""学科知识库构建管线测试共享 fixture（DK0/DK1）。

- 合成文档只用 ``synth-*`` ID，不读取真实学生数据与生产库。
- 真实模型网络访问已被仓库根 ``conftest.py`` 的 ``block_external_network``
  默认阻断；本目录不调用任何外部服务。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
KNOWLEDGE_DATA_DIR = REPO_ROOT / "knowledge_data"
PIPELINE_DIR = KNOWLEDGE_DATA_DIR / "pipeline"
BENCHMARK_DIR = PIPELINE_DIR / "benchmark"


def load_prepare_sample():
    """从脚本路径加载 prepare_sample（knowledge_data 下脚本不是可导入包）。"""
    script = KNOWLEDGE_DATA_DIR / "corpus" / "prepare_knowledge_sample.py"
    spec = importlib.util.spec_from_file_location("prepare_knowledge_sample", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def make_synthetic_manifest(
    kinds=("textbook", "zhwiki", "enwiki", "rfc", "arxiv"),
    families_per_kind: int = 3,
    docs_per_family: int = 2,
    chunks_per_doc: int = 5,
) -> dict:
    """构造合成五来源文档登记清单（chunk 为 {chunk_id, chars} 字典）。"""
    documents = []
    for kind in kinds:
        for f in range(families_per_kind):
            for d in range(docs_per_family):
                documents.append({
                    "document_id": f"synth-test-{kind}-f{f}d{d}",
                    "source_kind": kind,
                    "family_id": f"synth-test-{kind}-fam{f}",
                    "version": "v1",
                    "chunks": [
                        {
                            "chunk_id": f"synth-test-{kind}-f{f}d{d}c{n}",
                            "chars": 500 + ((f * 7 + d * 13 + n * 29) % 400),
                        }
                        for n in range(chunks_per_doc)
                    ],
                })
    return {"documents": documents}


@pytest.fixture
def sample_fixture(tmp_path):
    """DK0 抽样验收用的 kwargs：合成五来源文档 + 固定种子 + 小配额。"""
    return {
        "manifest": make_synthetic_manifest(),
        "seed": 20260908,
        "per_source": 6,
        "output_dir": str(tmp_path / "sample"),
    }


@pytest.fixture
def public_doc():
    """DK1 导入验收用的合成公开文档记录（非生产数据）。"""
    body = (
        "合成教材样例第一章\n\n"
        "栈是只允许在一端进行插入与删除操作的线性表，遵循后进先出原则。"
        "压栈与弹栈的时间复杂度均为 O(1)。\n\n"
        "队列是只允许在一端插入、另一端删除的线性表，遵循先进先出原则。"
        "循环队列用取模运算实现队首队尾回绕。\n\n"
        "二分查找要求搜索空间有序，每次比较后缩小一半区间，时间复杂度 O(log n)。"
    )
    return {
        "source_kind": "textbook",
        "external_id": "synth-textbook-sample-001",
        "source_family_id": "synth-textbook-sample",
        "language": "zh",
        "domains": ["data_structures"],
        "license_code": "CC-BY-SA-4.0",
        "title": "合成教材样例",
        "text": body,
    }


@pytest.fixture(autouse=True)
def _isolate_corpus_text_store(tmp_path, monkeypatch):
    """CR1 原文存储隔离：所有导入写入临时目录，不碰仓库 media/。

    ingest 写入规范化正文是必经步骤；本 fixture 保证新旧导入测试
    都落到一次性目录（含历史 test_ingest.py）。目录首次写入时创建，
    不污染“空目录”类断言。
    """
    store = tmp_path / "corpus_texts"
    monkeypatch.setenv("DISCIPLINE_TEXT_STORE_ROOT", str(store))
    return store


@pytest.fixture(autouse=True)
def _preserve_corpus_head(session):
    """CR5：head 是全局指针，任何用例激活后必须恢复。

    版本化检索按 head 路由；残留 head 会把后续用例（尤其旧索引
    fixture 测试）带入版本化路径，属于跨用例污染。失败也不掩盖原结果。
    """
    from app.services.discipline_knowledge import corpus_index as index_svc

    try:
        previous = index_svc.read_head(session)
    except Exception:  # noqa: BLE001 - 表不存在时无 head 可保
        previous = {"release_id": "", "revision": 0}
    yield
    try:
        from sqlmodel import select as _select

        from app.models.discipline_knowledge_model import (
            DisciplineHead as _Head,
        )

        current = index_svc.read_head(session)
        if current["release_id"] != previous["release_id"]:
            row = session.exec(
                _select(_Head).where(_Head.scope == "corpus:cs")).first()
            if row is not None:
                session.delete(row)
                session.commit()
            if previous["release_id"]:
                session.add(_Head(
                    scope="corpus:cs", release_id=previous["release_id"],
                    revision=previous["revision"]))
                session.commit()
    except Exception:  # noqa: BLE001 - 恢复失败不掩盖测试本身结果
        try:
            session.rollback()
        except Exception:  # noqa: BLE001
            pass


@pytest.fixture(autouse=True)
def _isolate_discipline_builds(session):
    """测试隔离：认领是全局的，teardown 时取消本库中遗留的 queued/running 构建。

    避免一个测试的 pending 工作项被后一个测试认领走（同库共享的
    session 级测试数据库）。running 残留项随其构建取消后不再被认领，
    过期后由回收器置 cancelled。
    """
    yield
    from sqlmodel import select as _select

    from app.models.discipline_knowledge_model import (
        DisciplineBuild as _Build,
    )
    from app.services.discipline_knowledge import builds as _builds

    leftovers = session.exec(
        _select(_Build).where(_Build.status.in_(["queued", "running"]))
    ).all()
    for build in leftovers:
        try:
            _builds.cancel_build(session, build.build_id, reason="test isolation")
        except Exception:  # noqa: BLE001 - 隔离清理不掩盖测试本身结果
            session.rollback()
