"""CR6 上线工具验收：只读预检（corpus_preflight）与检索验收 CLI（verify_corpus_rag）。

- 预检用例运行**真实脚本模块**，只给隔离库与隔离目录；"没有写入"由运行前后
  数据库文件哈希 + 全表行数对比证明，不依赖脚本自报的 ``mutation_count``；
- verify 默认 retrieval-only：合成 release + loopback fake embedding 服务，
  生成问答必须显式开启且有调用预算（默认不调用回答模型）；
- 部署产物（systemd 单元 / 预检脚本 / 发布脚本）做静态契约断言，防止迁移与
  Nexus 独立发布步骤在后续修改中丢失。
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "backend" / "scripts"
DEPLOY_DIR = REPO_ROOT / "deploy"

TEST_FP = "emfp_cr6_test_001"
TEST_DIM = 8

CORPUS_CHUNKER = {
    "normalizer": "corpus-norm/2",
    "chunker": "corpus-chunk/1",
    "target_tokens": 320,
    "overlap_tokens": 32,
    "max_tokens": 512,
}

MODEL_CONFIG_BODY = {
    "id": "intfloat/multilingual-e5-small",
    "revision": "cr6-test-rev",
    "files_hash": "sha256:cr6-test-files",
    "tokenizer": "intfloat/multilingual-e5-small",
    "pooling": "attention-mask mean",
    "prefixes": {"query": "query: ", "passage": "passage: "},
    "dimension": TEST_DIM,
    "max_length": 512,
}

DOC_OS = (
    "合成预检文档甲：页表记录虚拟页与物理页的映射，缺页时触发换入换出。"
    "虚拟内存让程序看到连续的地址空间。"
)
DOC_NET = (
    "合成预检文档乙：TCP 通过三次握手建立连接，用序号与确认号保证可靠有序交付。"
)


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _fake_vector(text: str, fingerprint: str = TEST_FP,
                 dim: int = TEST_DIM) -> list[float]:
    digest = hashlib.sha256(f"{fingerprint}|passage|{text}".encode()).digest()
    vals: list[float] = []
    while len(vals) < dim:
        digest = hashlib.sha256(digest).digest()
        vals.extend([(b - 128) / 128.0 for b in digest])
    vals = vals[:dim]
    norm = math.sqrt(sum(v * v for v in vals)) or 1.0
    return [v / norm for v in vals]


def _snapshot_db(path: Path) -> dict:
    """数据库文件哈希 + 全表行数快照（证明预检没有写入）。"""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        tables = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        counts = {name: conn.execute(
            f'SELECT COUNT(*) FROM "{name}"').fetchone()[0] for name in tables}
    finally:
        conn.close()
    return {"sha256": digest, "counts": counts}


def _ingest(session, external_id: str, text: str):
    from app.services.discipline_knowledge.ingest import ingest_document

    return ingest_document(session, {
        "source_kind": "textbook",
        "external_id": external_id,
        "source_family_id": f"fam-{external_id}",
        "title": f"合成预检标题-{external_id}",
        "language": "zh",
        "domains": ["os"],
        "license_code": "CC-BY-SA-4.0",
        "text": text,
    }, chunker_config=CORPUS_CHUNKER)


def _cache_vectors(session, chunk_ids, fingerprint: str = TEST_FP):
    from app.platform.knowledge.corpus_embedding import VectorCache, input_hash_for
    from app.services.discipline_knowledge.corpus_text import read_chunk_text

    cache = VectorCache(session)
    for chunk_id in chunk_ids:
        text = read_chunk_text(session, chunk_id)
        cache.put(model_fingerprint=fingerprint,
                  input_hash=input_hash_for(text, "passage", fingerprint),
                  vector=_fake_vector(text, fingerprint), dimension=TEST_DIM,
                  token_count=max(1, len(text) // 4), commit=False)
    session.commit()


@pytest.fixture
def corpus_env(tmp_path, monkeypatch):
    """CR6 隔离环境：FTS/来源/模型目录全部落在临时目录。"""
    fts_root = tmp_path / "fts"
    fts_root.mkdir()
    source_root = tmp_path / "sources"
    source_root.mkdir()
    for name in ("corpus_textbooks.jsonl", "corpus_zhwiki_cs.jsonl",
                 "corpus_enwiki_cs.jsonl", "corpus_rfc.jsonl",
                 "corpus_arxiv_cs.jsonl"):
        (source_root / name).write_text('{"id": "synth-cr6"}\n',
                                        encoding="utf-8")
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    for name in ("config.json", "tokenizer.json", "tokenizer_config.json",
                 "model.safetensors"):
        (model_dir / name).write_text("{}", encoding="utf-8")
    model_config = tmp_path / "model-config.json"
    model_config.write_text(
        json.dumps({"model": MODEL_CONFIG_BODY}, ensure_ascii=False),
        encoding="utf-8")

    monkeypatch.setenv("DISCIPLINE_FTS_ROOT", str(fts_root))
    monkeypatch.setenv("DISCIPLINE_SOURCE_ROOT", str(source_root))
    monkeypatch.setenv("CORPUS_EMBEDDING_MODEL_PATH", str(model_dir))
    monkeypatch.setenv("CORPUS_EMBEDDING_MODEL_CONFIG", str(model_config))
    monkeypatch.setenv("CORPUS_EMBEDDING_URL", "")
    return {"fts_root": fts_root, "source_root": source_root,
            "model_dir": model_dir, "model_config": model_config}


@pytest.fixture
def release(session, corpus_env):
    """已激活的合成 release（含 FTS 与向量成员）。"""
    from app.services.discipline_knowledge import corpus_index as index_svc

    chunk_ids: list[str] = []
    for i, text in enumerate((DOC_OS, DOC_NET)):
        chunk_ids.extend(_ingest(session, f"synth-cr6-{i}", text)["chunk_ids"])
    _cache_vectors(session, chunk_ids)
    created = index_svc.create_release(
        session, chunk_ids=chunk_ids, model_fingerprint=TEST_FP,
        dimension=TEST_DIM, title="CR6 合成发布")
    index_svc.build_fts(session, created["release_id"])
    assert index_svc.validate_index(session, created["release_id"])["ready"]
    activated = index_svc.activate_index(
        session, created["release_id"], index_svc.read_head(session)["revision"])
    assert activated["error_code"] == ""
    return {"release_id": created["release_id"], "chunk_ids": chunk_ids,
            "fingerprint": TEST_FP, "dimension": TEST_DIM,
            "fts_object_key": index_svc.fts_object_key_for(
                created["release_id"])}


@pytest.fixture
def preflight_client(corpus_env):
    module = _load_script("corpus_preflight")

    class _Client:
        def __init__(self):
            self.module = module

        def run(self, **env_overrides):
            return module.run(env=env_overrides or None)

    return _Client()


class _FakeEmbedServer:
    """loopback fake embedding 服务（指纹可换，用于预检/检索两类用例）。"""

    def __init__(self, fingerprint: str = TEST_FP,
                 dimension: int = TEST_DIM):
        self.fingerprint = fingerprint
        self.dimension = dimension
        self.fixed = _fake_vector(DOC_OS)
        state = self

        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # noqa: D102 - 测试静音
                pass

            def _json(self, status: int, body: dict) -> None:
                data = json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler 约定
                if self.path == "/health":
                    self._json(200, {"ready": True,
                                     "model_fingerprint": state.fingerprint,
                                     "dimension": state.dimension})
                else:
                    self._json(404, {})

            def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler 约定
                length = int(self.headers.get("Content-Length") or 0)
                payload = json.loads(self.rfile.read(length) or b"{}")
                texts = list(payload.get("texts") or [])
                self._json(200, {
                    "vectors": [list(state.fixed) for _ in texts],
                    "token_counts": [1 for _ in texts],
                    "model_fingerprint": state.fingerprint,
                    "dimension": state.dimension,
                })

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"

    def start(self):
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        daemon=True)
        self._thread.start()

    def stop(self):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


@pytest.fixture
def fake_embed_server(release):
    """fake 服务：默认返回合成 release 的指纹（检索用例需要）。"""
    from app.services.discipline_knowledge import corpus_search

    corpus_search.reset_vector_cooldown()
    server = _FakeEmbedServer()
    server.start()
    try:
        yield server
    finally:
        server.stop()
        corpus_search.reset_vector_cooldown()


def _write_queries(path: Path, release, extra_no_answer: bool = True) -> Path:
    rows = [
        {"query_id": "cr6-q1", "kind": "zh", "text": "虚拟内存 页表 映射",
         "relevant_passage_ids": [release["chunk_ids"][0]]},
        {"query_id": "cr6-q2", "kind": "zh", "text": "TCP 三次握手 可靠交付",
         "relevant_passage_ids": [release["chunk_ids"][1]]},
    ]
    if extra_no_answer:
        rows.append({"query_id": "cr6-q3", "kind": "no_answer",
                     "text": "量子纠缠的贝尔不等式实验",
                     "relevant_passage_ids": []})
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# 只读预检
# ---------------------------------------------------------------------------


def test_preflight_is_read_only(preflight_client, temp_db_path, release):
    before = _snapshot_db(temp_db_path)
    result = preflight_client.run()
    assert "model_fingerprint" in result
    assert result["mutation_count"] == 0
    after = _snapshot_db(temp_db_path)
    # 文件哈希 + 全表行数逐表一致：写入会同时改变两者之一
    assert after == before


def test_preflight_reports_required_sections(preflight_client, release,
                                             corpus_env):
    from app.platform.knowledge.corpus_embedding import model_fingerprint_for

    result = preflight_client.run()
    assert result["ok"] is True, result["errors"]
    assert result["mutation_count"] == 0
    assert result["schema_head"]["ok"] is True
    assert result["schema_head"]["current"] in result["schema_head"]["heads"]
    assert result["model_ready"] is True
    assert result["model_fingerprint"] == model_fingerprint_for({
        "model_id": MODEL_CONFIG_BODY["id"],
        "revision": MODEL_CONFIG_BODY["revision"],
        "files_hash": MODEL_CONFIG_BODY["files_hash"],
        "tokenizer": MODEL_CONFIG_BODY["tokenizer"],
        "pooling": MODEL_CONFIG_BODY["pooling"],
        "prefixes": MODEL_CONFIG_BODY["prefixes"],
        "dimension": MODEL_CONFIG_BODY["dimension"],
        "max_length": MODEL_CONFIG_BODY["max_length"],
    })
    assert result["dimension"] == TEST_DIM
    assert result["source_manifest"]["sets"] == ["cs-public", "cs-textbooks"]
    assert result["source_manifest"]["files_available"] == 5
    assert result["fts"]["root"] == str(corpus_env["fts_root"])
    assert result["fts"]["release_object_present"] is True
    assert result["active_release"]["release_id"] == release["release_id"]
    assert result["active_release"]["status"] == "ready"
    assert result["active_release"]["members"] >= 1
    assert result["resource_margin"]["disk_free_mb"] > 0
    assert result["resource_margin"]["embedding_port_listening"] is False


def test_preflight_reports_live_service_fingerprint(preflight_client,
                                                    fake_embed_server):
    from app.platform.knowledge.corpus_embedding import model_fingerprint_for

    # 服务端指纹必须与冻结配置一致（不一致即拒绝混算，见下一条用例）
    fake_embed_server.fingerprint = model_fingerprint_for({
        "model_id": MODEL_CONFIG_BODY["id"],
        "revision": MODEL_CONFIG_BODY["revision"],
        "files_hash": MODEL_CONFIG_BODY["files_hash"],
        "tokenizer": MODEL_CONFIG_BODY["tokenizer"],
        "pooling": MODEL_CONFIG_BODY["pooling"],
        "prefixes": MODEL_CONFIG_BODY["prefixes"],
        "dimension": MODEL_CONFIG_BODY["dimension"],
        "max_length": MODEL_CONFIG_BODY["max_length"],
    })
    result = preflight_client.run(CORPUS_EMBEDDING_URL=fake_embed_server.url)
    assert result["model_ready"] is True
    assert result["model_fingerprint"] == fake_embed_server.fingerprint
    assert result["model"]["source"] == "service"
    assert result["resource_margin"]["embedding_port_listening"] is True


def test_preflight_flags_fingerprint_mismatch(preflight_client,
                                              fake_embed_server):
    result = preflight_client.run(CORPUS_EMBEDDING_URL=fake_embed_server.url)
    assert result["ok"] is False
    assert any(err["code"] == "MODEL_FINGERPRINT_MISMATCH"
               for err in result["errors"])


def test_preflight_flags_missing_model_files(preflight_client, corpus_env,
                                             monkeypatch):
    monkeypatch.setenv("CORPUS_EMBEDDING_MODEL_PATH",
                       str(corpus_env["model_dir"] / "absent"))
    result = preflight_client.run()
    assert result["ok"] is False
    assert result["model_ready"] is False
    assert any(err["code"] == "MODEL_FILES_MISSING"
               for err in result["errors"])
    code = preflight_client.module.main(["--json"])
    assert code == 2


def test_preflight_flags_invalid_model_config(preflight_client, tmp_path):
    """P2-7：pooling/prefixes 与实现不一致必须在预检阶段阻断。"""
    config = tmp_path / "cls.json"
    config.write_text(json.dumps({"model": {
        **MODEL_CONFIG_BODY, "pooling": "cls",
    }}, ensure_ascii=False), encoding="utf-8")
    result = preflight_client.run(CORPUS_EMBEDDING_MODEL_CONFIG=str(config))
    assert result["ok"] is False
    assert result["model_ready"] is False
    assert any(err["code"] == "MODEL_CONFIG_INVALID"
               for err in result["errors"])


def test_preflight_flags_unfrozen_model_config(preflight_client, tmp_path):
    config = tmp_path / "unfrozen.json"
    config.write_text(json.dumps({"model": {
        **MODEL_CONFIG_BODY, "revision": None, "files_hash": None,
    }}, ensure_ascii=False), encoding="utf-8")
    result = preflight_client.run(CORPUS_EMBEDDING_MODEL_CONFIG=str(config))
    assert result["ok"] is False
    assert result["model_ready"] is False
    assert result["model_fingerprint"] == ""
    assert any(err["code"] == "MODEL_CONFIG_UNFROZEN"
               for err in result["errors"])


# ---------------------------------------------------------------------------
# 检索验收 CLI
# ---------------------------------------------------------------------------


def test_verify_cli_retrieval_only(session, release, fake_embed_server,
                                   tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CORPUS_EMBEDDING_URL", fake_embed_server.url)
    queries = _write_queries(tmp_path / "queries.jsonl", release)
    module = _load_script("verify_corpus_rag")
    code = module.main([
        "--release-id", release["release_id"],
        "--suite", "cr6-test", "--queries", str(queries),
    ])
    assert code == 0, capsys.readouterr().err
    report = json.loads(capsys.readouterr().out)
    assert report["release_id"] == release["release_id"]
    assert report["retrieval_only"] is True
    assert report["generation_called"] is False
    assert report["stats"]["queries"] == 3
    assert report["stats"]["scorable"] == 2
    assert report["stats"]["hit_at_k"] == 1.0
    assert report["stats"]["mrr"] == 1.0
    assert report["stats"]["no_answer_queries"] == 1
    assert report["references"]["checked"] >= 2
    assert report["references"]["failed"] == 0
    assert report["references"]["not_in_release"] == 0
    assert report["latency_ms"]["samples"] == 3
    assert report["error_codes"] == {}
    assert report["modes"]["hybrid"] >= 1


def test_verify_cli_requires_generation_budget(release, tmp_path, capsys):
    queries = _write_queries(tmp_path / "queries.jsonl", release)
    module = _load_script("verify_corpus_rag")
    code = module.main([
        "--release-id", release["release_id"],
        "--queries", str(queries), "--with-generation",
    ])
    assert code == 2
    assert "GENERATION_BUDGET_REQUIRED" in capsys.readouterr().err


def test_verify_cli_generation_requires_configured_endpoint(
        release, tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("VERIFY_CORPUS_GENERATION_URL", raising=False)
    queries = _write_queries(tmp_path / "queries.jsonl", release)
    module = _load_script("verify_corpus_rag")
    code = module.main([
        "--release-id", release["release_id"], "--queries", str(queries),
        "--with-generation", "--max-generation-calls", "2",
    ])
    assert code == 3
    assert "GENERATION_NOT_CONFIGURED" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# 部署产物静态契约
# ---------------------------------------------------------------------------


def test_deploy_artifacts_cover_corpus_ops():
    embedding = (DEPLOY_DIR / "systemd"
                 / "smartcarb-corpus-embedding.service").read_text(
        encoding="utf-8")
    worker = (DEPLOY_DIR / "systemd"
              / "smartcarb-corpus-worker.service").read_text(encoding="utf-8")
    assert "127.0.0.1" in embedding and "8310" in embedding
    assert "serve_corpus_embedding.py" in embedding
    assert "corpus_rag" in worker
    assert "run_discipline_worker.py" in worker
    assert "Restart=" in embedding and "Restart=" in worker

    release_script = (DEPLOY_DIR / "scripts"
                      / "smartcarb-release.sh").read_text(encoding="utf-8")
    assert "alembic" in release_script
    assert "upgrade head" in release_script
    assert "nexus-runtime" in release_script
    assert "rev-parse" in release_script

    preflight = (DEPLOY_DIR / "scripts"
                 / "corpus-preflight.sh").read_text(encoding="utf-8")
    assert "corpus_preflight.py" in preflight
