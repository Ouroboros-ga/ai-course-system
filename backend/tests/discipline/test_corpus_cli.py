"""P0-1 CLI 验收：create-build 入口、build --from-build 推导与状态查询。

importlib 加载脚本模块（与 ``test_corpus_preflight.py::_load_script`` 同模式），
走真实 ``session_factory``（隔离测试库）；不下载模型、不调网络。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "backend" / "scripts"

TEST_FP = "emfp_cli_test_001"
TEST_DIM = 8

CORPUS_CHUNKER = {
    "normalizer": "corpus-norm/2",
    "chunker": "corpus-chunk/1",
    "target_tokens": 320,
    "overlap_tokens": 32,
    "max_tokens": 512,
}

DOC_A = "合成 CLI 文档甲：页表记录虚拟页与物理页的映射，缺页时换入换出。"
DOC_B = "合成 CLI 文档乙：TCP 通过三次握手建立连接，用序号确认可靠交付。"


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _ingest_docs(session, tag: str, texts: list[str]) -> list[str]:
    from app.services.discipline_knowledge.ingest import ingest_document

    version_ids: list[str] = []
    for i, text in enumerate(texts):
        result = ingest_document(session, {
            "source_kind": "textbook",
            "external_id": f"synth-cli-{tag}-{i}",
            "source_family_id": f"synth-cli-{tag}",
            "title": f"合成 CLI 标题{tag}-{i}",
            "language": "zh",
            "domains": ["os"],
            "license_code": "CC-BY-SA-4.0",
            "text": text,
        }, chunker_config=CORPUS_CHUNKER)
        version_ids.append(result["version_id"])
    return version_ids


def test_create_build_from_version_ids(session, capsys):
    """P0-1：无入口 → 现在可按版本清单创建 corpus_rag 构建并规划分片。"""
    from app.services.discipline_knowledge import builds as build_svc

    module = _load_script("manage_corpus_index")
    version_ids = _ingest_docs(session, "a", [DOC_A, DOC_B])
    code = module.main([
        "create-build", "--version-ids", *version_ids,
        "--model-fingerprint", TEST_FP, "--dimension", str(TEST_DIM),
    ])
    assert code == 0, capsys.readouterr().err
    out = json.loads(capsys.readouterr().out)
    assert out["created"] is True
    assert out["planned_shards"] >= 1
    assert out["model_fingerprint"] == TEST_FP
    assert set(out["document_version_ids"]) == set(version_ids)
    view = build_svc.get_build(session, out["build_id"])
    assert view["pipeline_kind"] == "corpus_rag"
    assert view["items_by_stage"]["embed"] == {
        "pending": out["planned_shards"]}
    assert view["stages"] == ["embed", "fts", "validate"]


def test_create_build_from_source_set(session, tmp_path, capsys):
    """按命名来源集建构建：流式登记 + 回传版本清单。"""
    module = _load_script("manage_corpus_index")
    source_root = tmp_path / "sources"
    source_root.mkdir()
    rows = [{"id": f"synth-cli-set-{i}", "title": f"合成教材{i}",
             "text": text, "license": "CC-BY-SA-4.0"}
            for i, text in enumerate([DOC_A, DOC_B])]
    (source_root / "corpus_textbooks.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8")
    code = module.main([
        "create-build", "--scope", "cs-textbooks",
        "--source-root", str(source_root),
        "--model-fingerprint", TEST_FP, "--dimension", str(TEST_DIM),
    ])
    assert code == 0, capsys.readouterr().err
    out = json.loads(capsys.readouterr().out)
    assert len(out["document_version_ids"]) == 2
    assert out["planned_shards"] >= 1


def test_build_from_build_derives_versions(session, capsys):
    """build --from-build 可省略范围参数：从构建 scope 推导版本清单。"""
    module = _load_script("manage_corpus_index")
    version_ids = _ingest_docs(session, "c", [DOC_A])
    assert module.main([
        "create-build", "--version-ids", *version_ids,
        "--model-fingerprint", TEST_FP, "--dimension", str(TEST_DIM),
    ]) == 0
    build_id = json.loads(capsys.readouterr().out)["build_id"]
    code = module.main([
        "build", "--from-build", build_id,
        "--model-fingerprint", TEST_FP, "--dimension", str(TEST_DIM),
    ])
    assert code == 0, capsys.readouterr().err
    out = json.loads(capsys.readouterr().out)
    assert out["release_id"]
    assert out["members"] >= 1
    assert out["fts"]["paragraphs"] >= 1


def test_status_by_build_id(session, capsys):
    """§7.3：status --build-id 查看构建分片进度（C1）。"""
    module = _load_script("manage_corpus_index")
    version_ids = _ingest_docs(session, "e", [DOC_A, DOC_B])
    assert module.main([
        "create-build", "--version-ids", *version_ids,
        "--model-fingerprint", TEST_FP, "--dimension", str(TEST_DIM),
    ]) == 0
    build_id = json.loads(capsys.readouterr().out)["build_id"]
    code = module.main(["status", "--build-id", build_id])
    assert code == 0
    view = json.loads(capsys.readouterr().out)
    assert view["build_id"] == build_id
    assert view["pipeline_kind"] == "corpus_rag"
    assert view["items_by_stage"]["embed"]["pending"] >= 1


def test_status_unknown_build_id_fails_closed(session, capsys):
    module = _load_script("manage_corpus_index")
    assert module.main(["status", "--build-id", "bld_不存在"]) == 2
    assert "BUILD_NOT_FOUND" in capsys.readouterr().err


def test_worker_accepts_max_batches_alias(capsys):
    """§7.3：run_discipline_worker --max-batches 别名（C2）。"""
    module = _load_script("run_discipline_worker")
    with pytest.raises(SystemExit) as exc_info:
        module.main(["--help"])
    assert exc_info.value.code == 0
    assert "--max-batches" in capsys.readouterr().out


def test_build_without_scope_or_from_build_rejected(session, capsys):
    module = _load_script("manage_corpus_index")
    code = module.main([
        "build", "--model-fingerprint", TEST_FP, "--dimension", str(TEST_DIM)])
    assert code == 2
    assert "SCHEMA_INVALID" in capsys.readouterr().err


def test_create_build_requires_fingerprint(session, capsys):
    """未冻结指纹不得建构建（拒绝不补默认）。"""
    module = _load_script("manage_corpus_index")
    version_ids = _ingest_docs(session, "d", [DOC_A])
    with pytest.raises(SystemExit) as exc_info:
        module.main([
            "create-build", "--version-ids", *version_ids,
            "--dimension", str(TEST_DIM)])
    assert exc_info.value.code == 2  # argparse: --model-fingerprint 必填


def test_hf_tokenizer_adapter_delegates_and_names():
    """导入分块必须能用真实 tokenizer（字符回退低估英文 token 会超模型上限）。"""
    module = _load_script("import_discipline_corpus")

    class _Tok:
        def encode(self, text, truncation=False):
            return [0] * len(str(text))

    adapter = module._HfTokenizerAdapter(_Tok(), "bge-small-zh-v1.5/1")
    assert adapter.name == "bge-small-zh-v1.5/1"
    assert adapter.count("abcd") == 4
    assert adapter.count("") == 0
    # 名称合法（进入 chunker 身份，非法名会被 _resolve_chunker 拒绝）
    import re
    assert re.fullmatch(r"[A-Za-z0-9._+/-]+", adapter.name)


def test_create_build_pins_chunker_version_and_filters_chunks(session):
    """同版本存在多套分块时，构建必须只索引冻结口径的块（2026-09-09 实测缺陷）。"""
    from sqlmodel import select

    from app.models.discipline_knowledge_model import DisciplineChunk
    from app.services.discipline_knowledge import builds as build_svc

    for i, chunker in enumerate((
            "corpus-chunk/1+char-fallback/1+t320+o32+m512",
            "corpus-chunk/1+bge-small-zh-v1.5/1+t320+o32+m512")):
        session.add(DisciplineChunk(
            chunk_id=f"dkch_pin_{i}", version_id="dkdv_pin_1",
            chunker_version=chunker, chunk_no=i, locator=f"p{i}:0-10",
            content_hash=f"h{i}", text_object_key="", char_start=0,
            char_end=10, char_count=10, token_estimate=5,
            token_count=5, section_path=""))
    session.commit()
    pinned = "corpus-chunk/1+bge-small-zh-v1.5/1+t320+o32+m512"
    created = build_svc.create_corpus_build(
        session, owner_user_id=1,
        scope={"document_version_ids": ["dkdv_pin_1"]},
        config={"model_fingerprint": TEST_FP, "dimension": TEST_DIM,
                "chunker_version": pinned})
    build = build_svc.get_build(session, created["build_id"])
    assert (build.get("scope") or {}).get("chunker_version") == pinned
    assert created["planned_chunks"] == 1, "只应规划冻结口径的 1 块"
    assert session.exec(select(DisciplineChunk.chunk_id).where(
        DisciplineChunk.chunk_id.like("dkch_pin_%"))).all() == [
        "dkch_pin_0", "dkch_pin_1"], "测试数据自检"
