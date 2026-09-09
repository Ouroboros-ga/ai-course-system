"""T3 无 preset 入口：最小输入 → 自主提案（最小 SR1/N1）。

行为契约（任务书 T3）：
- `prepare_experiment(target, objective)` 输出同一提案引用、可读摘要、
  缺少的用户输入；不直接执行（Worker 零提交）；
- 明确仓库＋"配置并试跑" → 自主提案（不答"仅支持 nanoGPT"，不要求
  指标/主张；无 claim_refs 冒充）；
- 明确论文 → 读可得论文、按作者链接找仓库；初始 repo 固定 revision；
  License 沿既有规则核验（未知仓库不信任；未核验如实标注，不冒充已读）；
- README 与环境/数据入口决定 setup/smoke/reproduce；默认资源来自服务端
  可用配置；不确定的依赖版本留给沙箱试验，不虚构"已配置成功"；
- 默认展示目标＋公开数据来源＋资源摘要；目标真正歧义且无法推断时才问，
  不把每个字段做确认表单。

全调用真实业务代码；网络/读取经注入的 Reader/Searcher 替身——fixture URL
只在测试 Reader 中处理，不进入正式工具来源白名单。
"""

import pytest

from nexus import approvals
from nexus import proposals as proposals_module
from nexus import request_scope


@pytest.fixture(autouse=True)
def _clean_stores():
    approvals.clear_memory_store()
    proposals_module.clear_memory_store()
    yield
    approvals.clear_memory_store()
    proposals_module.clear_memory_store()


REPO_A = "fixture://repo-a"


class _FakeReader:
    """测试 Reader：只认识 fixture://（正式白名单仅 GitHub，见正式拒绝测试）。"""

    def __init__(self, meta=None):
        self.meta = meta or {
            "readme": "# repo-a\n Synthetic fixture repo.",
            "env_files": {"requirements.txt": "numpy\n"},
            "license": {"spdx": "MIT", "status": "verified"},
            "default_branch": "main",
            "revision_sha": "deadbeef1234",
            "repo_url": REPO_A,
        }
        self.reads = []

    async def read_repo(self, repo_url):
        self.reads.append(repo_url)
        if repo_url != REPO_A:
            return {"repo_url": repo_url, "reachable": False}
        return {"repo_url": repo_url, "reachable": True, **self.meta}


class _Intake:
    """任务书示例形态的薄夹具：合成身份＋测试 Reader，计数读真实存储。"""

    def __init__(self, reader=None, searcher=None,
                 user_id="u-t3", session_id="s-t3"):
        self.reader = reader or _FakeReader()
        self.searcher = searcher
        self.user_id = user_id
        self.session_id = session_id
        self.worker_submit_count = 0

    async def prepare(self, target, objective=""):
        from nexus import experiment_intake as intake_module
        from nexus.tools import reproduction as repro_module

        # 真实计数：把 Worker 提交入口换成会计数的转发（prepare 若真提交，
        # 计数必然 >0——空断言不算护栏）。
        real_submit = repro_module._submit_to_worker
        intake = self

        async def _counting_submit(preset):
            intake.worker_submit_count += 1
            return await real_submit(preset)

        repro_module._submit_to_worker = _counting_submit
        try:
            result = await intake_module.prepare(
                target, objective, user_id=self.user_id,
                session_id=self.session_id, reader=self.reader,
                searcher=self.searcher)
        finally:
            repro_module._submit_to_worker = real_submit
        return result


@pytest.fixture()
def intake():
    return _Intake()


async def test_unknown_preset_can_prepare(intake):
    proposal = await intake.prepare(REPO_A, "配置环境并试跑")
    assert proposal["status"] == "success"
    assert proposal["kind"] == "autonomous_experiment"
    assert proposal["scope"]["mode"] == "smoke"
    assert proposal["scope"].get("claim_refs") is None
    assert intake.worker_submit_count == 0
    # 真实落盘：提案行可读且为自主种。
    stored = proposals_module.get_proposal(proposal["proposal"]["proposal_id"])
    assert stored is not None and stored["kind"] == "autonomous_experiment"


async def test_explicit_repo_never_answers_nanogpt_only(intake):
    result = await intake.prepare(REPO_A, "配置环境并试跑")
    assert result["status"] == "success"
    text = str(result.get("summary", "")) + str(result.get("detail", ""))
    assert "nanoGPT" not in text
    assert "仅支持" not in text
    # 不要求指标/主张：无 metrics 门。
    assert result["scope"].get("metric_refs") is None


async def test_paper_input_single_unverified_hit_asks():
    """F4 替代旧“首个命中即成功”：单个无确证搜索命中必须询问，不默认作者仓库。

    旧断言（test_paper_input_finds_repo_via_search）对应已被替代的行为，
    由本测试＋ test_paper_page_link_accepts_verified 接替覆盖。
    """

    async def _searcher(query):
        assert "github" in query
        return {"repo_url": REPO_A, "paper_title": "Fixture Paper",
                "source": "web"}

    flow = _Intake(searcher=_searcher)
    result = await flow.prepare("Fixture Paper 做图像分类", "复现论文指标")
    assert result["status"] == "need_input"
    assert REPO_A in str(result.get("questions", ""))
    assert "首个" in str(result.get("questions", ""))


async def test_paper_page_link_accepts_verified():
    """论文页明确链接＋可达即取（作者自陈，不 HAVE 歧义）。"""

    async def _searcher(query):
        return {"repo_url": None}

    from nexus import experiment_intake as intake_module

    async def _fake_links(arxiv_id):
        assert arxiv_id == "2401.00001"
        return [REPO_A]

    async def _fake_meta(arxiv_id):
        return {"title": "Fixture Paper", "authors": ["Ada"]}

    real_links = intake_module._fetch_paper_code_links
    real_meta = intake_module._fetch_arxiv_meta
    intake_module._fetch_paper_code_links = _fake_links
    intake_module._fetch_arxiv_meta = _fake_meta
    try:
        flow = _Intake(searcher=_searcher)
        result = await flow.prepare("arxiv:2401.00001", "配置环境并试跑")
    finally:
        intake_module._fetch_paper_code_links = real_links
        intake_module._fetch_arxiv_meta = real_meta
    assert result["status"] == "success"
    assert result["scope"]["repo_url"] == REPO_A
    assert result["scope"]["env_manifest"]["repo_source"] == "paper-page"


async def test_arxiv_url_not_rejected_by_scheme():
    """F4：arXiv URL 不再被 scheme 分支提前拒绝（进论文流）。"""

    async def _searcher(query):
        return {"repo_url": None}

    flow = _Intake(searcher=_searcher)
    result = await flow.prepare("https://arxiv.org/abs/2401.00001", "试跑")
    # 无链接无命中 → need_input（问仓库），而不是 rejected。
    assert result["status"] == "need_input"
    assert "公开仓库" in str(result.get("questions", ""))


async def test_attachment_ref_records_without_read():
    """F4：附件引用只记录不冒充已读，并要仓库直链。"""
    flow = _Intake()
    result = await flow.prepare("attachment:att-123 做图像分类", "试跑")
    assert result["status"] == "need_input"
    assert "附件" in str(result.get("questions", ""))


async def test_license_verified_and_unknown_marked():
    flow = _Intake()
    ok_result = await flow.prepare(REPO_A, "试跑")
    assert ok_result["license"] == {"spdx": "MIT", "status": "verified"}

    unknown_meta = {
        "readme": "# repo-a", "env_files": {},
        "license": {"spdx": "", "status": "unknown"},
        "default_branch": "main", "revision_sha": "deadbeef1234",
        "repo_url": REPO_A,
    }
    flow2 = _Intake(reader=_FakeReader(meta=unknown_meta))
    pending = await flow2.prepare(REPO_A, "试跑")
    assert pending["status"] == "success"
    assert pending["license"]["status"] == "unknown"
    # 未核验如实标注进缺失输入，不阻止先配置/试跑。
    assert any("License" in item for item in pending["missing_inputs"])


async def test_mode_inference_setup_smoke_reproduce(intake):
    setup = await intake.prepare(REPO_A, "配置环境")
    assert setup["scope"]["mode"] == "setup"
    smoke = await intake.prepare(REPO_A, "配置环境并试跑")
    assert smoke["scope"]["mode"] == "smoke"
    repro = await intake.prepare(REPO_A, "复现论文指标")
    assert repro["scope"]["mode"] == "reproduce"


async def test_known_preset_routes_to_preset_flow(intake):
    result = await intake.prepare("nanogpt", "配置环境并试跑")
    assert result["status"] == "known_preset"
    assert result["preset_id"] == "nanogpt"
    assert result.get("proposal") is None
    assert intake.worker_submit_count == 0


async def test_ambiguous_target_asks_instead_of_form(intake):
    result = await intake.prepare("", "")
    assert result["status"] == "need_input"
    assert result.get("proposal") is None
    assert len(result.get("questions", [])) >= 1
    # 不是逐字段确认表单：问题数有界。
    assert len(result["questions"]) <= 3


async def test_unreachable_repo_without_paper_asks(intake):
    result = await intake.prepare("fixture://repo-missing", "配置并试跑")
    assert result["status"] == "need_input"
    assert result.get("proposal") is None


async def test_summary_shows_target_sources_resources(intake):
    result = await intake.prepare(REPO_A, "配置环境并试跑")
    summary = result["summary"]
    assert SCOPE_OBJECTIVE in summary["objective"]
    assert summary["repo_url"] == REPO_A
    assert summary["resources"]["cpu"] > 0
    assert summary["resources"]["wall_time_s"] > 0
    assert isinstance(result["missing_inputs"], list)


SCOPE_OBJECTIVE = "配置环境并试跑"


async def test_production_rejects_fixture_url():
    """正式工具不认 fixture://（来源白名单仅 GitHub 公开仓库）。"""
    from nexus import experiment_intake as intake_module

    result = await intake_module.prepare(
        REPO_A, "试跑", user_id="u1", session_id="s1")
    assert result["status"] == "rejected"
    assert result["code"] == "TARGET_UNSUPPORTED"
    assert result.get("proposal") is None


async def test_tool_wrapper_needs_scope_and_never_submits(monkeypatch):
    """工具面：缺身份拒绝；有身份走真实 prepare；Worker 零提交。"""
    import nexus.tools.reproduction as repro_module
    from nexus import experiment_intake as intake_module

    async def _must_not_submit(preset):
        raise AssertionError("prepare 不得提交 Worker")

    monkeypatch.setattr(repro_module, "_submit_to_worker", _must_not_submit)
    # 缺用户上下文 → 拒绝。
    naked = await intake_module.prepare_experiment.ainvoke(
        {"target": "https://github.com/example/r", "objective": "试跑"})
    assert naked["status"] == "error"
    assert naked["code"] == "SCOPE_MISSING"
    # 有身份但仓库不可达（无网断言不可用时走 need_input/不可达分支，
    # 绝不伪造提案；不断言具体分支，只断言零提交与形状）。
    tokens = (request_scope.set_scope("u-tool", None)
              + request_scope.set_execution_scope("s-tool", None))
    gate = request_scope.set_experiment_gate("research", "ask")
    try:
        result = await intake_module.prepare_experiment.ainvoke(
            {"target": "https://github.com/example/r", "objective": "试跑"})
    finally:
        request_scope.reset_experiment_gate(gate)
        request_scope.reset_scope(tokens[:2])
        request_scope.reset_execution_scope(tokens[2:])
    assert result["status"] in ("success", "need_input", "rejected", "unavailable")
    assert result.get("is_supplementary") is True


async def test_plan_no_preset_points_to_prepare():
    """plan_reproduction 无预设分支指引 prepare_experiment（形状兼容旧调用方）。"""
    from nexus.tools.reproduction import plan_reproduction

    result = await plan_reproduction.ainvoke({"target": "some random paper"})
    assert result["status"] == "no_preset"
    assert result.get("suggested_tool") == "prepare_experiment"
    assert "nanogpt" in result["known_presets"]


def test_prepare_tool_is_research_only():
    """准备工具 Research 可见、General 不可见；Ask 保留（仅执行被禁）。"""
    from nexus.agent import _tools_for_mode

    assert "prepare_experiment" in {t.name for t in _tools_for_mode("research", "auto")}
    assert "prepare_experiment" in {t.name for t in _tools_for_mode("research", "ask")}
    assert "prepare_experiment" not in {t.name for t in _tools_for_mode("general", "auto")}


def test_probe_link_ip_filter():
    """F4：探测 SSRF 底线（内网/回环/非法 scheme 不发包）。"""
    from nexus import experiment_intake as intake_module

    assert intake_module._is_public_http_url("http://127.0.0.1/x") is False
    assert intake_module._is_public_http_url("http://169.254.169.254/") is False
    assert intake_module._is_public_http_url("http://10.1.2.3/y") is False
    assert intake_module._is_public_http_url("ftp://example.com/x") is False
    assert intake_module._is_public_http_url("not a url") is False


class _CheckedClient:
    """_checked_get/_fetch_repo_file 替身：按 host 脚本化应答。"""

    def __init__(self, raw_text=None, contents_text=None):
        import base64 as _base64

        self.raw_text = raw_text
        self.contents_text = contents_text
        self.calls: list[str] = []
        self._b64 = _base64

    async def get(self, url):
        import httpx

        self.calls.append(url)
        if "raw.githubusercontent.com" in url:
            if self.raw_text is None:
                raise httpx.ConnectError("v6 down")
            return _FakeResp(200, text=self.raw_text, url=url)
        if "/contents/" in url:
            if self.contents_text is None:
                return _FakeResp(404, text="{}", url=url)
            payload = {"encoding": "base64",
                       "content": self._b64.b64encode(
                           self.contents_text.encode()).decode()}
            return _FakeResp(200, json_data=payload, url=url)
        return _FakeResp(404, text="{}", url=url)


class _FakeResp:
    def __init__(self, status_code, text="", json_data=None, url=""):
        self.status_code = status_code
        self.text = text
        self._json = json_data
        self.url = url
        self.headers = {}

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


async def test_fetch_repo_file_prefers_raw():
    """raw 可达即用 raw（不碰 contents API）。"""
    from nexus import experiment_intake as intake_module

    client = _CheckedClient(raw_text="hello-raw")
    text = await intake_module._fetch_repo_file(client, "o", "r", "abc", "README.md", 5.0)
    assert text == "hello-raw"
    assert not any("/contents/" in call for call in client.calls)


async def test_fetch_repo_file_falls_back_to_contents_api():
    """raw 不通即 contents API 同 ref 读取（v6 机房实证场景）。"""
    from nexus import experiment_intake as intake_module

    client = _CheckedClient(raw_text=None, contents_text="hello-contents")
    text = await intake_module._fetch_repo_file(client, "o", "r", "abc", "README.md", 5.0)
    assert text == "hello-contents"
    assert any("/contents/" in call and "ref=abc" in call for call in client.calls)


async def test_fetch_repo_file_missing_both_ways():
    """两路皆无即 None（调用方按不可读处理，不抛）。"""
    from nexus import experiment_intake as intake_module

    client = _CheckedClient(raw_text=None, contents_text=None)
    assert await intake_module._fetch_repo_file(
        client, "o", "r", "abc", "NOPE.md", 5.0) is None


def test_parse_paper_ref_shapes():
    """F4：来源识别（arXiv URL/id、附件、标题）先于来源限制。"""
    from nexus import experiment_intake as intake_module

    ref = intake_module.parse_paper_ref("https://arxiv.org/abs/2401.00001")
    assert (ref["kind"], ref["arxiv_id"]) == ("arxiv_url", "2401.00001")
    ref = intake_module.parse_paper_ref("https://arxiv.org/pdf/2401.00001.pdf")
    assert ref["kind"] == "arxiv_url"
    ref = intake_module.parse_paper_ref("arxiv:2401.00001v2")
    assert (ref["kind"], ref["arxiv_id"]) == ("arxiv_id", "2401.00001v2")
    ref = intake_module.parse_paper_ref("2401.00001")
    assert ref["kind"] == "arxiv_id"
    ref = intake_module.parse_paper_ref("attachment:att-9 做分类")
    assert ref["kind"] == "attachment" and ref["attachment_id"] == "att-9"
    ref = intake_module.parse_paper_ref("Attention Is All You Need")
    assert ref["kind"] == "title"


def test_verify_repo_paper_link_levels():
    """F4：关联信号分级（强/弱/无），确定性。"""
    from nexus import experiment_intake as intake_module

    paper = {"arxiv_id": "2401.00001", "title": "Fixture Paper For Images"}
    assert intake_module.verify_repo_paper_link(
        "see https://arxiv.org/abs/2401.00001", paper)["level"] == "strong"
    assert intake_module.verify_repo_paper_link(
        "Fixture paper for images official code", paper)["level"] == "weak"
    assert intake_module.verify_repo_paper_link(
        "some random toolkit", paper)["level"] == "none"


def test_extract_data_links_classifies():
    """F4：数据链接提取＋分类（只提取不下载）。"""
    from nexus import experiment_intake as intake_module

    links = intake_module._extract_data_links(
        "data at https://huggingface.co/datasets/foo/bar and "
        "https://github.com/o/r/releases/download/v1/data.zip plus "
        "https://arxiv.org/abs/2401.1 and https://pypi.org/project/x")
    kinds = {item["kind"] for item in links}
    assert "huggingface" in kinds and "github-release" in kinds
    assert not any("arxiv.org" in item["url"] for item in links)
    assert not any("pypi.org" in item["url"] for item in links)


async def test_scope_carries_env_manifest(intake):
    """F4：scope 冻结环境清单（读位 SHA＋数据＋来源），过 scope 校验。"""
    result = await intake.prepare(REPO_A, "配置环境并试跑")
    assert result["status"] == "success"
    manifest = result["scope"].get("env_manifest") or {}
    assert manifest.get("read_at_sha") == "deadbeef1234"
    assert "requirements.txt" in manifest.get("env_files_detected", [])
    assert manifest.get("repo_source") == "direct"
    assert result["scope"]["data_refs"] == []
