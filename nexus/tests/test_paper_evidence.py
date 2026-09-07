"""NX-R1a 证据薄链测试：规范单元 + 工具行为（合成附件数据，零真实 LLM/网络）。"""

import pytest

from nexus.paper_evidence import (
    ABSTRACT_ONLY_THRESHOLD_CHARS,
    EVIDENCE_EXCERPT_MAX,
    EvidenceRegistry,
    build_evidence,
    citation_line,
    evidence_id_for,
    get_registry,
)
from nexus.request_scope import (
    reset_attachments,
    reset_execution_scope,
    reset_scope,
    set_attachments,
    set_execution_scope,
    set_scope,
)
import nexus.tools.paper_research as pr


# ---------------------------------------------------------------------------
# paper_evidence 规范单元
# ---------------------------------------------------------------------------


def _block(text: str, locator: str | None = "p1") -> dict:
    out = {"text": text}
    if locator is not None:
        out["locator"] = locator
    return out


def test_build_evidence_full_shape():
    evidence = build_evidence(
        attachment_id="att01", filename="方法A论文.pdf",
        block=_block("本文提出一种方法。" * 50), attachment_total_chars=5000,
    )
    assert evidence["evidence_id"].startswith("ev-")
    assert evidence["attachment_id"] == "att01"
    assert evidence["source_title"] == "方法A论文.pdf"
    assert evidence["source_kind"] == "upload_label", "来源是上传文件标签，不伪装已验证书目"
    assert evidence["locator"] == "p1"
    assert evidence["coverage"] == "fulltext_excerpt"
    assert evidence["is_supplementary"] is True


def test_build_evidence_locator_missing_is_honest():
    """页面映射缺失 → locator None，不编造 page 1。"""
    evidence = build_evidence(
        attachment_id="att01", filename="f.pdf",
        block=_block("正文", None), attachment_total_chars=5000,
    )
    assert evidence["locator"] is None
    line = citation_line(1, evidence)
    assert "定位缺失" in line
    assert "page 1" not in line and "p1" not in line.replace("定位缺失", "")


def test_build_evidence_abstract_only_by_parse_size():
    """解析总字符低于阈值 → abstract_only（机械判定，不依赖模型自述）。"""
    evidence = build_evidence(
        attachment_id="att01", filename="f.pdf",
        block=_block("Abstract: short"), attachment_total_chars=ABSTRACT_ONLY_THRESHOLD_CHARS - 1,
    )
    assert evidence["coverage"] == "abstract_only"
    evidence_full = build_evidence(
        attachment_id="att02", filename="f.pdf",
        block=_block("Abstract: short"), attachment_total_chars=ABSTRACT_ONLY_THRESHOLD_CHARS,
    )
    assert evidence_full["coverage"] == "fulltext_excerpt"


def test_excerpt_capped_and_empty_blocks_skipped():
    long_text = "x" * (EVIDENCE_EXCERPT_MAX + 500)
    evidence = build_evidence(
        attachment_id="a", filename="f.pdf", block=_block(long_text, None), attachment_total_chars=99999,
    )
    assert len(evidence["excerpt"]) == EVIDENCE_EXCERPT_MAX
    assert build_evidence(attachment_id="a", filename="f.pdf", block=_block("  "),
                          attachment_total_chars=9999) is None
    assert build_evidence(attachment_id="a", filename="f.pdf", block=None,
                          attachment_total_chars=9999) is None


def test_evidence_id_deterministic():
    e1 = evidence_id_for("att01", "p3", "same text")
    e2 = evidence_id_for("att01", "p3", "same text")
    e3 = evidence_id_for("att01", None, "same text")
    assert e1 == e2 and e1 != e3


def test_registry_owner_and_session_isolation_and_fifo():
    registry = EvidenceRegistry(max_entries=3)
    ev = [{"evidence_id": "ev-1", "source_title": "a", "locator": "p1",
           "excerpt": "x", "coverage": "fulltext_excerpt"}]
    registry.register("42", "sess-1", ev)
    assert registry.resolve("ev-1", user_id="42", session_id="sess-1") is not None
    assert registry.resolve("ev-1", user_id="99", session_id="sess-1") is None, "跨用户拒绝"
    assert registry.resolve("ev-1", user_id="42", session_id="other") is None, "跨会话拒绝"
    assert registry.resolve("ev-missing", user_id="42", session_id="sess-1") is None
    # FIFO 容量：第 4 条挤掉第 1 条。
    for i in range(2, 6):
        registry.register("42", "sess-1",
                          [{"evidence_id": f"ev-{i}", "source_title": "a", "locator": "p1",
                            "excerpt": "x", "coverage": "fulltext_excerpt"}])
    assert registry.resolve("ev-1", user_id="42", session_id="sess-1") is None
    assert registry.resolve("ev-5", user_id="42", session_id="sess-1") is not None


# ---------------------------------------------------------------------------
# collect_paper_evidence 工具（MockTransport 拦截 Backend 内部端点）
# ---------------------------------------------------------------------------


def _pdf_payload(filename: str, blocks: list[dict], truncated=False) -> dict:
    return {"attachment_id": "att01", "filename": filename, "kind": "pdf",
            "status": "ready", "blocks": blocks, "truncated": truncated,
            "total_blocks": len(blocks)}


def _resp(payload: dict, status: int = 200) -> "object":
    """MockTransport 处理器必须返回真实 httpx.Response（鸭子类型响应会让
    transport 内部递归）。外层信封与 Backend unified_response 同形。"""
    import httpx

    return httpx.Response(status, json={"code": 200, "message": "ok", "data": payload})


def _patch_backend(monkeypatch: pytest.MonkeyPatch, responder):
    import httpx

    # 必须在打补丁前捕获原始 AsyncClient——monkeypatch 的是全局 httpx 模块
    # 属性，工厂体内再取 httpx.AsyncClient 会命中工厂自身（无限递归）。
    original_client = httpx.AsyncClient

    def factory(**kwargs):
        kwargs["transport"] = httpx.MockTransport(responder)
        return original_client(**kwargs)

    monkeypatch.setattr(pr.httpx, "AsyncClient", factory)


@pytest.fixture
def research_scope(monkeypatch: pytest.MonkeyPatch):
    """配置 Backend 内部端点（httpx 被 MockTransport 拦截，不真实联网）。"""
    monkeypatch.setenv("NEXUS_BACKEND_INTERNAL_URL", "http://backend.test")
    monkeypatch.setenv("NEXUS_BACKEND_INTERNAL_TOKEN", "internal-test-token")
    from nexus.config import get_settings as _gs

    _gs.cache_clear()

    def _set(attachment_ids=("att01", "att02"), user="42", session="sess-r1"):
        tokens_scope = set_scope(user, None)
        tokens_exec = set_execution_scope(session, None)
        token_att = set_attachments(list(attachment_ids))
        return (tokens_scope, tokens_exec, token_att)

    yield _set
    _gs.cache_clear()


async def _teardown(tokens):
    reset_scope(tokens[0])
    reset_execution_scope(tokens[1])
    reset_attachments(tokens[2])


async def test_collect_evidence_success_two_pdfs(monkeypatch, research_scope):
    """两篇 PDF → 证据各带原文 locator 与上传标签；登记后可被同会话解析。"""
    tokens = research_scope()
    get_registry()._entries.clear()
    get_registry()._order.clear()

    def responder(request):
        import re as _re
        match = _re.search(r"attachments/(\w+)/content$", request.url.path)
        aid = match.group(1) if match else ""
        if aid == "att01":
            blocks = [_block("方法A在数据集X上达到SOTA。", "p2"), _block("方法A的限制是计算量大。", "p3")]
            return _resp(_pdf_payload("方法A.pdf", blocks))
        blocks = [_block("方法B在数据集X上略逊但更省资源。", "p5")]
        return _resp(_pdf_payload("方法B.pdf", blocks))

    _patch_backend(monkeypatch, responder)
    try:
        result = await pr.collect_paper_evidence.coroutine(
            question="比较方法A与方法B", attachment_ids=["att01", "att02"]
        )
    finally:
        await _teardown(tokens)
    assert result["status"] == "success", result
    evidences = result["evidences"]
    assert len(evidences) == 3
    assert [e["locator"] for e in evidences] == ["p2", "p3", "p5"]
    assert {e["source_title"] for e in evidences} == {"方法A.pdf", "方法B.pdf"}
    # 登记后同 owner+session 可解析（write_research_report 的前置）。
    resolved = get_registry().resolve(evidences[0]["evidence_id"], user_id="42", session_id="sess-r1")
    assert resolved is not None


async def test_collect_evidence_marks_abstract_only(monkeypatch, research_scope):
    tokens = research_scope(attachment_ids=("att01",))
    get_registry()._entries.clear()

    def responder(request):
        return _resp(_pdf_payload("短摘要.pdf", [_block("Abstract: 我们做了某事。")]))

    _patch_backend(monkeypatch, responder)
    try:
        result = await pr.collect_paper_evidence.coroutine(
            question="q", attachment_ids=["att01"]
        )
    finally:
        await _teardown(tokens)
    assert result["status"] == "success"
    assert result["coverage_by_attachment"]["att01"] == "abstract_only"
    assert result["evidences"][0]["coverage"] == "abstract_only"


async def test_collect_evidence_budgets(monkeypatch, research_scope):
    """>12 条证据触发条数预算并如实 truncated；超出附件进 errors。"""
    tokens = research_scope()
    get_registry()._entries.clear()
    blocks = [_block(f"证据块内容-{i}" * 2, f"p{i + 1}") for i in range(20)]

    def responder(request):
        return _resp(_pdf_payload("很多证据.pdf", blocks))

    _patch_backend(monkeypatch, responder)
    try:
        result = await pr.collect_paper_evidence.coroutine(
            question="q", attachment_ids=["att01", "att02"]
        )
    finally:
        await _teardown(tokens)
    assert result["status"] == "success"
    assert len(result["evidences"]) == 12
    assert result["truncated"] is True
    assert any(e["code"] == "EVIDENCE_BUDGET_REACHED" for e in result["attachment_errors"])


async def test_collect_evidence_rejects_out_of_scope_and_non_pdf(monkeypatch, research_scope):
    tokens = research_scope(attachment_ids=("att01",))
    get_registry()._entries.clear()

    # 1) 越权：未绑定附件直接拒绝（模型传参不能扩大范围）。
    try:
        result = await pr.collect_paper_evidence.coroutine(
            question="q", attachment_ids=["att99"]
        )
        assert result["status"] == "rejected"
        assert result["code"] == "ATTACHMENT_NOT_IN_SCOPE"

        # 2) 非 PDF：如实拒绝进入研究证据链（本批先验收 PDF）。
        async def fake_fetch(url, token, aid):
            return {"kind": "docx", "filename": "文档.docx", "blocks": [_block("内容")]}, None

        monkeypatch.setattr(pr, "_fetch_blocks", fake_fetch)
        result2 = await pr.collect_paper_evidence.coroutine(
            question="q", attachment_ids=["att01"]
        )
        assert result2["status"] == "failed"
        assert result2["attachment_errors"][0]["code"] == "KIND_NOT_PDF"

        # 3) 403/404 语义映射。
        async def fake_fetch_403(url, token, aid):
            return None, "ATTACHMENT_SESSION_MISMATCH"

        monkeypatch.setattr(pr, "_fetch_blocks", fake_fetch_403)
        result3 = await pr.collect_paper_evidence.coroutine(
            question="q", attachment_ids=["att01"]
        )
        assert result3["status"] == "failed"
        assert result3["code"] == "ATTACHMENT_SESSION_MISMATCH"
    finally:
        await _teardown(tokens)


async def test_collect_evidence_requires_question_and_ids():
    tokens = set_scope("42", None)
    tokens_exec = set_execution_scope("s", None)
    token_att = set_attachments([])
    try:
        r1 = await pr.collect_paper_evidence.coroutine(**{"question": "", "attachment_ids": ["att01"]})
        assert r1["status"] == "rejected" and r1["code"] == "QUESTION_REQUIRED"
        r2 = await pr.collect_paper_evidence.coroutine(**{"question": "q", "attachment_ids": []})
        assert r2["status"] == "rejected" and r2["code"] == "ATTACHMENT_ID_INVALID"
    finally:
        reset_scope(tokens)
        reset_execution_scope(tokens_exec)
        reset_attachments(token_att)


# ---------------------------------------------------------------------------
# write_research_report：引用校验与服务端渲染
# ---------------------------------------------------------------------------


def _register_one(user="42", session="sess-r1", eid="ev-cite1", locator="p2") -> None:
    get_registry().register(user, session, [{
        "evidence_id": eid, "attachment_id": "att01", "source_title": "方法A.pdf",
        "source_kind": "upload_label", "locator": locator,
        "excerpt": "方法A在数据集X上达到SOTA。", "coverage": "fulltext_excerpt",
        "is_supplementary": True,
    }])


async def _run_report(**kwargs):
    return await pr.write_research_report.coroutine(**kwargs)


async def test_report_rejects_invalid_and_foreign_citations(research_scope):
    tokens = research_scope()
    get_registry()._entries.clear()
    _register_one(eid="ev-mine")
    try:
        result = await _run_report(
            title="报告", question="q", body_markdown="结论 [1]。",
            cited_evidence_ids=["ev-fake", "ev-mine", "ev-mine"],
        )
        assert result["status"] == "rejected"
        assert result["code"] == "EVIDENCE_ID_INVALID"
        assert result["invalid_ids"] == ["ev-fake"], "重复合法引用去重，伪造 id 全量报告"
        assert "最多一次" in result["detail"]

        # 他人证据（同 id 不同 owner 登记在另一用户名下）→ 解析失败。
        _register_one(user="99", session="sess-other", eid="ev-theirs")
        result2 = await _run_report(
            title="报告", question="q", body_markdown="x", cited_evidence_ids=["ev-theirs"],
        )
        assert result2["status"] == "rejected"
        assert result2["invalid_ids"] == ["ev-theirs"]

        # 无任何引用 → 拒绝（不写无证据的"成功报告"）。
        result3 = await _run_report(title="报告", question="q", body_markdown="x", cited_evidence_ids=[])
        assert result3["status"] == "rejected"
        assert result3["code"] == "CITATIONS_REQUIRED"
    finally:
        await _teardown(tokens)


async def test_report_renders_citations_and_writes_artifact(monkeypatch, research_scope):
    tokens = research_scope()
    get_registry()._entries.clear()
    _register_one(eid="ev-ok1", locator="p2")
    _register_one(eid="ev-ok2", locator=None)
    captured = {}

    async def fake_write(artifact_type, title, content, user_id):
        captured.update({"type": artifact_type, "title": title, "content": content, "user": user_id})
        return {"status": "success", "artifact": {"artifact_id": "art1", "download_path": "/d"}}

    import nexus.artifact_client as artifact_client

    monkeypatch.setattr(artifact_client, "write_artifact_via_backend", fake_write)
    # NX-N0/R2：撤销重验需要来源可读（本用例来源正常）。
    _patch_backend(monkeypatch, lambda request: _resp(_pdf_payload(
        "方法A.pdf", [{"text": "方法A在数据集X上达到SOTA。", "locator": "p2"}])))
    try:
        result = await _run_report(
            title="方法比较报告", question="A 与 B 有何异同", body_markdown="## 比较\n- 相同点 [1]\n- 差异 [2]",
            cited_evidence_ids=["ev-ok1", "ev-ok2"],
        )
    finally:
        await _teardown(tokens)
    assert result["status"] == "success", result
    assert result["artifact"]["artifact_id"] == "art1"
    assert len(result["citations"]) == 2
    content = captured["content"]
    assert "## 引用" in content
    assert "方法A.pdf" in content and "定位 p2" in content
    assert "定位缺失（解析未提供页码映射）" in content, "locator 缺失如实标注"
    assert "补充参考" in content and captured["user"] == "42"


async def test_report_fails_closed_when_artifact_write_fails(monkeypatch, research_scope):
    tokens = research_scope()
    get_registry()._entries.clear()
    _register_one(eid="ev-ok")

    async def fake_write(artifact_type, title, content, user_id):
        return {"status": "failed", "detail": "存储不可用"}

    import nexus.artifact_client as artifact_client

    monkeypatch.setattr(artifact_client, "write_artifact_via_backend", fake_write)
    # NX-N0/R2：撤销重验需要来源可读——本用例来源正常，走到写入失败分支。
    _patch_backend(monkeypatch, lambda request: _resp(_pdf_payload(
        "方法A.pdf", [{"text": "方法A在数据集X上达到SOTA。", "locator": "p2"}])))
    try:
        result = await _run_report(
            # NX-N0/R1：正文须带合法 [n] 引用（本用例测写入失败路径，引用合规）。
            title="t", question="q", body_markdown="b [1]", cited_evidence_ids=["ev-ok"],
        )
    finally:
        await _teardown(tokens)
    assert result["status"] == "unavailable"
    assert result["code"] == "ARTIFACT_UNAVAILABLE"
