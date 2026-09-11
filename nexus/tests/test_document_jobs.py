"""F6 文档作业：冻结快照＋幂等＋partial/重试/取消（纯内存分支）。

行为契约（计划 §11）：
- 同一冻结快照供多格式消费；转换不改写事实；
- 幂等键同内容去重、同内容不同键冲突；失败格式可单独重试；
- PDF 无工具链如实缺席（partial），不伪装预览；
- 撤销/删除的材料读不到即拒绝生成新版本。
"""

import pytest

from nexus import document_jobs as jobs_module
from nexus import document_output as output_module


@pytest.fixture(autouse=True)
def _clean():
    jobs_module.clear_memory_store()
    yield
    jobs_module.clear_memory_store()


SAMPLE_MD = """# 技术说明 · demo

结论 $E=mc^2$ 与 **加粗**。

| 指标 | 实测 |
|---|---|
| val_loss | 1.89 |

```bash
echo hi
```

![架构图](https://example.com/arch.png)

见 [@doe2024](https://example.com/paper)。
"""


class _FakeArtifacts:
    def __init__(self):
        self.objects: dict[str, str] = {}
        self.binaries: dict[str, bytes] = {}
        self.count = 0

    async def write_artifact_via_backend(self, *, artifact_type, title,
                                         content, user_id, run_id=""):
        self.count += 1
        artifact_id = f"art-{self.count:04d}"
        self.objects[artifact_id] = content
        return {"status": "success",
                "artifact": {"artifact_id": artifact_id,
                             "artifact_type": artifact_type, "title": title,
                             "size_bytes": len(content),
                             "download_path": f"/x/{artifact_id}"}}

    async def write_binary_artifact_via_backend(self, *, artifact_type, title,
                                                raw, user_id, run_id=""):
        self.count += 1
        artifact_id = f"art-{self.count:04d}"
        self.binaries[artifact_id] = bytes(raw)
        return {"status": "success",
                "artifact": {"artifact_id": artifact_id,
                             "artifact_type": artifact_type, "title": title,
                             "size_bytes": len(raw),
                             "download_path": f"/x/{artifact_id}"}}

    async def read_artifact_via_backend(self, *, artifact_id, user_id):
        if artifact_id not in self.objects:
            return {"status": "unavailable", "code": "ARTIFACT_NOT_FOUND",
                    "detail": "无"}
        return {"status": "success",
                "artifact": {"artifact_id": artifact_id},
                "content": self.objects[artifact_id], "truncated": False}


@pytest.fixture()
def fake_artifacts(monkeypatch):
    from nexus import artifact_client as artifact_client_module

    store = _FakeArtifacts()
    monkeypatch.setattr(artifact_client_module, "write_artifact_via_backend",
                        store.write_artifact_via_backend)
    monkeypatch.setattr(artifact_client_module, "write_binary_artifact_via_backend",
                        store.write_binary_artifact_via_backend)
    monkeypatch.setattr(artifact_client_module, "read_artifact_via_backend",
                        store.read_artifact_via_backend)
    return store


def _frozen(template="tech_doc"):
    return output_module.freeze_document(
        markdown=SAMPLE_MD, title="技术说明", template=template,
        source={"kind": "markdown"})


def test_freeze_deterministic_with_inventory():
    first = _frozen()
    second = _frozen()
    assert first["content_hash"] == second["content_hash"]
    assert first["document_id"] == second["document_id"]
    inventory = first["inventory"]
    assert inventory["tables"] == 1
    assert inventory["code_blocks"] == 1
    assert inventory["math_spans"] == 1
    assert inventory["figures"][0]["src"] == "https://example.com/arch.png"
    assert "doe2024" in inventory["citations"]
    assert first["template_version"] == "tpl-techdoc/1"


def test_freeze_rejects_unknown_template_and_empty():
    with pytest.raises(output_module.DocumentRenderError) as exc:
        output_module.freeze_document(markdown="# hi", template="nature")
    assert exc.value.code == "TEMPLATE_UNKNOWN"
    with pytest.raises(output_module.DocumentRenderError) as exc2:
        output_module.freeze_document(markdown="   ", template="tech_doc")
    assert exc2.value.code == "DOCUMENT_EMPTY"


def test_math_preserved_editable_in_stdlib(monkeypatch):
    monkeypatch.setattr(output_module.shutil, "which", lambda _name: None)
    frozen = _frozen()
    built = output_module.build_document_formats(
        frozen=frozen, formats=["word", "latex"])
    assert built["status"] == "succeeded"
    word = built["formats"]["word"]
    assert word["engine"] == "stdlib/1"
    assert word["checks"]["checks"]["math_editable"] is True
    assert word["checks"]["checks"]["math_native"] is False
    latex = built["formats"]["latex"]
    assert "$E=mc^2$" in latex["text"], "tex 数学必须为原生 $…$，不得转义"
    assert latex["checks"]["checks"]["math_spans"] == 1


async def test_job_create_idempotent_and_conflict(fake_artifacts):
    frozen = _frozen()
    first = await jobs_module.create_and_render(
        owner="u-f6", session_id="s-f6", frozen=frozen,
        formats=["markdown", "word", "latex"], template="tech_doc",
        idempotency_key="key-1", source={"kind": "markdown"})
    assert first["deduped"] is False
    assert first["job"]["status"] in ("succeeded", "partial")
    assert fake_artifacts.count == 3
    again = await jobs_module.create_and_render(
        owner="u-f6", session_id="s-f6", frozen=frozen,
        formats=["markdown", "word", "latex"], template="tech_doc",
        idempotency_key="key-1", source={"kind": "markdown"})
    assert again["deduped"] is True
    assert again["job"]["job_id"] == first["job"]["job_id"]
    assert fake_artifacts.count == 3, "去重不得重写产物"
    other = output_module.freeze_document(
        markdown="# 不同内容\n", title="技术说明", template="tech_doc",
        source={"kind": "markdown"})
    with pytest.raises(jobs_module.DocumentError) as exc:
        await jobs_module.create_and_render(
            owner="u-f6", session_id="s-f6", frozen=other,
            formats=["markdown"], template="tech_doc",
            idempotency_key="key-1", source={"kind": "markdown"})
    assert exc.value.code == "DOCUMENT_CONFLICT"


async def test_job_partial_pdf_missing_toolchain(fake_artifacts, monkeypatch):
    monkeypatch.setattr(output_module.shutil, "which", lambda _name: None)
    frozen = _frozen()
    created = await jobs_module.create_and_render(
        owner="u-f6", session_id="s-f6", frozen=frozen,
        formats=["markdown", "word", "latex", "pdf"], template="tech_doc",
        idempotency_key="key-pdf", source={"kind": "markdown"})
    job = created["job"]
    assert job["status"] == "partial"
    assert job["formats"]["pdf"]["status"] == "failed"
    assert job["formats"]["pdf"]["checks"]["code"] == "TOOLCHAIN_MISSING"
    assert job["formats"]["word"]["status"] == "succeeded"
    assert job["formats"]["word"]["artifact_id"].startswith("art-")
    view = jobs_module.public_job_view(job)
    assert view["formats"]["pdf"]["structural_valid"] is False
    assert view["formats"]["word"]["structural_valid"] is True
    assert view["formats"]["word"]["math_editable"] is True


async def test_job_retry_only_failed(fake_artifacts, monkeypatch):
    monkeypatch.setattr(output_module.shutil, "which", lambda _name: None)
    frozen = _frozen()
    created = await jobs_module.create_and_render(
        owner="u-f6", session_id="s-f6", frozen=frozen,
        formats=["word", "pdf"], template="tech_doc",
        idempotency_key="key-retry", source={"kind": "markdown"})
    job = created["job"]
    assert job["status"] == "partial"
    before = fake_artifacts.count
    retried = await jobs_module.retry_failed(
        job_id=job["job_id"], owner="u-f6")
    assert retried["retried"] == ["pdf"], "只跑失败格式"
    assert retried["job"]["formats"]["word"]["artifact_id"] == \
        job["formats"]["word"]["artifact_id"], "成功格式不重写"
    assert fake_artifacts.count == before, "pdf 仍缺工具链，不产生新产物"
    assert retried["deduped"] is False


async def test_job_cancel_terminal_semantics(fake_artifacts):
    frozen = _frozen()
    created = await jobs_module.create_and_render(
        owner="u-f6", session_id="s-f6", frozen=frozen,
        formats=["markdown"], template="tech_doc",
        idempotency_key="key-cancel", source={"kind": "markdown"})
    job = created["job"]
    cancelled = jobs_module.cancel_job(job_id=job["job_id"], owner="u-f6")
    assert cancelled["already_terminal"] is True
    with pytest.raises(jobs_module.DocumentError) as exc:
        jobs_module.cancel_job(job_id="nope", owner="u-f6")
    assert exc.value.code == "JOB_NOT_FOUND"
    with pytest.raises(jobs_module.DocumentError) as exc2:
        jobs_module.cancel_job(job_id=job["job_id"], owner="attacker")
    assert exc2.value.code == "JOB_FORBIDDEN"


async def test_tool_revoked_artifact_refused(monkeypatch):
    from nexus import artifact_client as artifact_client_module
    from nexus.request_scope import set_execution_scope, set_scope
    from nexus.tools import artifact as artifact_tool_module

    async def _gone(*, artifact_id, user_id):
        return {"status": "unavailable", "code": "ARTIFACT_NOT_FOUND",
                "detail": "产物不存在或无权读取。"}

    monkeypatch.setattr(artifact_client_module, "read_artifact_via_backend", _gone)
    tokens = set_scope("u-f6", None) + set_execution_scope("s-f6", None)
    try:
        out = await artifact_tool_module.create_document_output.ainvoke({
            "source": "artifact:art-gone", "title": "t",
            "template": "tech_doc", "formats": "markdown,word",
            "idempotency_key": ""})
    finally:
        from nexus.request_scope import reset_execution_scope, reset_scope

        reset_scope(tokens[:2])
        reset_execution_scope(tokens[2:])
    assert out["status"] == "error"
    assert out["code"] == "ARTIFACT_NOT_FOUND"


async def test_tool_run_source_needs_terminal():
    from nexus import experiment_runs as runs_module
    from nexus.request_scope import set_execution_scope, set_scope
    from nexus.tools import artifact as artifact_tool_module

    runs_module.clear_memory_store()
    run = runs_module.create_or_get_run(
        run_id="run-f6-tool", owner="u-f6", session_id="s-f6",
        proposal_id="pp-1", proposal_version=1,
        scope_hash="h" * 16, approval_id="run-f6-tool")
    tokens = set_scope("u-f6", None) + set_execution_scope("s-f6", None)
    try:
        out = await artifact_tool_module.create_document_output.ainvoke({
            "source": "run:run-f6-tool", "title": "t",
            "template": "experiment_report", "formats": "markdown",
            "idempotency_key": ""})
    finally:
        from nexus.request_scope import reset_execution_scope, reset_scope

        reset_scope(tokens[:2])
        reset_execution_scope(tokens[2:])
        runs_module.clear_memory_store()
    assert out["status"] == "error"
    assert out["code"] == "SOURCE_NOT_READY"


async def test_document_http_endpoints(monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from nexus import artifact_client as artifact_client_module
    from nexus.main import app

    store = _FakeArtifacts()
    monkeypatch.setattr(artifact_client_module, "write_artifact_via_backend",
                        store.write_artifact_via_backend)
    monkeypatch.setattr(artifact_client_module, "write_binary_artifact_via_backend",
                        store.write_binary_artifact_via_backend)
    monkeypatch.delenv("NEXUS_API_KEY", raising=False)
    user = {"X-Nexus-User-Id": "u-http"}
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://test") as client:
        created = await client.post(
            "/api/v1/nexus/document-jobs",
            json={"source_kind": "markdown", "markdown": "# hi\n",
                  "title": "t", "template": "tech_doc",
                  "formats": ["markdown", "word"],
                  "idempotency_key": "http-key-1"}, headers=user)
        assert created.status_code == 200, created.text
        body = created.json()
        assert body["status"] in ("succeeded", "partial")
        assert body["deduped"] is False
        job_id = body["job_id"]
        again = await client.post(
            "/api/v1/nexus/document-jobs",
            json={"source_kind": "markdown", "markdown": "# hi\n",
                  "title": "t", "template": "tech_doc",
                  "formats": ["markdown", "word"],
                  "idempotency_key": "http-key-1"}, headers=user)
        assert again.json()["deduped"] is True
        conflict = await client.post(
            "/api/v1/nexus/document-jobs",
            json={"source_kind": "markdown", "markdown": "# other\n",
                  "title": "t", "template": "tech_doc",
                  "formats": ["markdown"],
                  "idempotency_key": "http-key-1"}, headers=user)
        assert conflict.status_code == 409
        bad_template = await client.post(
            "/api/v1/nexus/document-jobs",
            json={"source_kind": "markdown", "markdown": "# hi\n",
                  "template": "nature", "formats": ["markdown"]},
            headers=user)
        assert bad_template.status_code == 400
        queried = await client.get(
            f"/api/v1/nexus/document-jobs/{job_id}", headers=user)
        assert queried.status_code == 200
        cross = await client.get(
            f"/api/v1/nexus/document-jobs/{job_id}",
            headers={"X-Nexus-User-Id": "attacker"})
        assert cross.status_code == 404
        cancelled = await client.post(
            f"/api/v1/nexus/document-jobs/{job_id}/cancel", headers=user)
        assert cancelled.json()["already_terminal"] is True
        retried = await client.post(
            f"/api/v1/nexus/document-jobs/{job_id}/retry", headers=user)
        assert retried.status_code == 200
