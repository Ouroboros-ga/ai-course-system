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


async def test_paper_input_finds_repo_via_search():
    async def _searcher(query):
        assert "github" in query
        return {"repo_url": REPO_A, "paper_title": "Fixture Paper",
                "source": "web"}

    flow = _Intake(searcher=_searcher)
    result = await flow.prepare("Fixture Paper 做图像分类", "复现论文指标")
    assert result["status"] == "success"
    assert result["scope"]["repo_url"] == REPO_A
    assert result["scope"]["mode"] == "reproduce"
    # 初始 repo 固定 revision（Reader 给出的 SHA）。
    assert result["scope"]["repo_revision"] == "deadbeef1234"


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
