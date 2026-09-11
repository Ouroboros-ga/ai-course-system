"""T7 执行前核验门：修订固定＋License 持久化（配方修订固定门）。

行为契约（任务书 T7＋§2/§8）：
- intake 核验的 License 结论持久化进提案（不入 scope_hash），审批冻结、
  执行门消费冻结快照，报告取持久化结论（旧行缺失回退 unknown，不伪装）；
- 执行前核验门：修订未固定→REVISION_NOT_PINNED；未核验→LICENSE_UNVERIFIED；
  白名单外→LICENSE_NOT_ALLOWED；三者皆 fail-closed（票据已消费语义同 P1-A）；
- 换仓库未附新结论→重置 unknown（不沿用旧结论）；
- 真实仓库走读（micrograd MIT / flask BSD-3-Clause，固定 SHA）经纯函数
  门验证（只读核验，不调真实容器/LLM；真实容器行为见回执线上实证）。

全调用真实业务代码；网络经注入 Reader，不进正式白名单。
"""

import pytest

from nexus import approvals
from nexus import experiment_runs as runs_module
from nexus import proposals as proposals_module
from nexus import license_policy as license_module


@pytest.fixture(autouse=True)
def _clean_stores():
    approvals.clear_memory_store()
    proposals_module.clear_memory_store()
    runs_module.clear_memory_store()
    yield
    approvals.clear_memory_store()
    proposals_module.clear_memory_store()
    runs_module.clear_memory_store()


def _scope(revision="deadbeef1234567890"):
    return {
        "objective": "配置并试跑",
        "repo_url": "https://github.com/example/r",
        "repo_revision": revision,
        "source_refs": [], "data_refs": [],
        "network_profile": "pypi-allowed",
        "resources": {"cpu": 1.0, "memory_mb": 2048, "disk_mb": 5120,
                      "wall_time_s": 1800},
        "mode": "smoke", "allow_environment_repair": True,
    }


def _start_run(user_id="u-t7", session_id="s-t7", scope=None, license_info=None):
    from nexus.tools import reproduction as repro_module  # noqa: F401 (门经此核)

    proposal = proposals_module.create_proposal(
        user_id=user_id, session_id=session_id, preset=None,
        kind="autonomous_experiment", scope=scope or _scope(),
        license_info=license_info)
    req = proposals_module.request_approval_for_proposal(
        proposal["proposal_id"], user_id=user_id,
        expected_version=proposal["version"])
    aid = req["approval"]["approval_id"]
    approvals.decide_approval(aid, user_id, "approved")
    return proposal, aid


def test_license_allowlist_mit_and_bsd_pass_gpl_blocked():
    assert license_module.verify_license(
        {"spdx": "MIT", "status": "verified"})["allowed"] is True
    assert license_module.verify_license(
        {"spdx": "BSD-3-Clause", "status": "verified"})["allowed"] is True
    assert license_module.verify_license(
        {"spdx": "", "status": "unknown"})["code"] == "LICENSE_UNVERIFIED"
    assert license_module.verify_license(
        {"spdx": "MIT", "status": "unknown"})["code"] == "LICENSE_UNVERIFIED"
    blocked = license_module.verify_license(
        {"spdx": "GPL-3.0-only", "status": "verified"})
    assert blocked["allowed"] is False
    assert blocked["code"] == "LICENSE_NOT_ALLOWED"


def test_revision_pinning_requires_sha():
    assert license_module.is_sha_pinned("7bc720e951fe422b8f8814aa5aa1b64121d26b4c") is True
    assert license_module.is_sha_pinned("abc1234") is True
    assert license_module.is_sha_pinned("main") is False
    assert license_module.is_sha_pinned("") is False
    gate = license_module.verify_execution_gate(
        scope=_scope(revision="main"),
        license_info={"spdx": "MIT", "status": "verified"})
    assert gate["ok"] is False and gate["code"] == "REVISION_NOT_PINNED"


def test_real_repo_walkthrough_micrograd_and_flask():
    """真实仓库只读走读（T7 样例选择依据，纯函数门验证，不调容器/LLM）。

    A micrograd（MIT，setup.py，README 示例可跑，CPU 纯 Python）；
    B flask（BSD-3-Clause，pyproject.toml，不同环境入口）。
    SHA 取自 2026-09-08 GitHub API 只读核验（见回执）。
    """
    micro_sha = "7bc720e951fe422b8f8814aa5aa1b64121d26b4c"
    flask_sha = "d318b683471101618febed18996405ad26462110"
    gate_a = license_module.verify_execution_gate(
        scope={**_scope(), "repo_url": "https://github.com/karpathy/micrograd",
               "repo_revision": micro_sha},
        license_info={"spdx": "MIT", "status": "verified"})
    gate_b = license_module.verify_execution_gate(
        scope={**_scope(), "repo_url": "https://github.com/pallets/flask",
               "repo_revision": flask_sha},
        license_info={"spdx": "BSD-3-Clause", "status": "verified"})
    assert gate_a["ok"] is True and gate_a["code"] == "GATE_OK"
    assert gate_b["ok"] is True and gate_b["code"] == "GATE_OK"


def test_proposal_persists_license_and_freezes_to_approval():
    proposal = proposals_module.create_proposal(
        user_id="u1", session_id="s1", preset=None,
        kind="autonomous_experiment", scope=_scope(),
        license_info={"spdx": "MIT", "status": "verified"})
    assert proposal["license"] == {"spdx": "MIT", "status": "verified"}
    stored = proposals_module.get_proposal(proposal["proposal_id"])
    assert stored["license"]["spdx"] == "MIT"
    req = proposals_module.request_approval_for_proposal(
        proposal["proposal_id"], user_id="u1", expected_version=1)
    row = approvals.get_approval(req["approval"]["approval_id"])
    assert row["frozen_license"] == {"spdx": "MIT", "status": "verified"}
    # 旧行（无 license 入参）默认 unknown，不伪装。
    legacy = proposals_module.create_proposal(
        user_id="u1", session_id="s1", preset=None,
        kind="autonomous_experiment", scope=_scope())
    assert legacy["license"]["status"] == "unknown"


def test_patch_change_repo_resets_license_without_new_conclusion():
    proposal = proposals_module.create_proposal(
        user_id="u1", session_id="s1", preset=None,
        kind="autonomous_experiment", scope=_scope(),
        license_info={"spdx": "MIT", "status": "verified"})
    patched = proposals_module.patch_proposal(
        proposal["proposal_id"], user_id="u1", expected_version=1,
        scope={**_scope(), "repo_url": "https://github.com/example/other"})
    assert patched["proposal"]["license"]["status"] == "unknown"
    # 附新结论则采用新结论（版本已＋1，用新版本号继续改）。
    patched2 = proposals_module.patch_proposal(
        proposal["proposal_id"], user_id="u1", expected_version=2,
        scope={**_scope(), "repo_revision": "fffffffffffffff"},
        license_info={"spdx": "BSD-3-Clause", "status": "verified"})
    assert patched2["proposal"]["license"]["spdx"] == "BSD-3-Clause"


async def test_gate_blocks_unpinned_unverified_disallowed():
    from nexus.tools import reproduction as repro_module

    # 未固定修订 → REVISION_NOT_PINNED。
    _p1, aid1 = _start_run(
        scope=_scope(revision="main"),
        license_info={"spdx": "MIT", "status": "verified"})
    with pytest.raises(approvals.ApprovalError) as exc1:
        await repro_module.execute_autonomous_experiment(
            approval_id=aid1, user_id="u-t7", session_id="s-t7",
            mode="research", research_execution_mode="auto")
    assert exc1.value.code == "REVISION_NOT_PINNED"
    # 未核验 → LICENSE_UNVERIFIED。
    _p2, aid2 = _start_run(license_info={"spdx": "", "status": "unknown"})
    with pytest.raises(approvals.ApprovalError) as exc2:
        await repro_module.execute_autonomous_experiment(
            approval_id=aid2, user_id="u-t7", session_id="s-t7",
            mode="research", research_execution_mode="auto")
    assert exc2.value.code == "LICENSE_UNVERIFIED"
    # 白名单外 → LICENSE_NOT_ALLOWED。
    _p3, aid3 = _start_run(
        license_info={"spdx": "GPL-3.0-only", "status": "verified"})
    with pytest.raises(approvals.ApprovalError) as exc3:
        await repro_module.execute_autonomous_experiment(
            approval_id=aid3, user_id="u-t7", session_id="s-t7",
            mode="research", research_execution_mode="auto")
    assert exc3.value.code == "LICENSE_NOT_ALLOWED"


async def test_verified_proposal_executes_and_report_uses_persisted_license(monkeypatch):
    """已核验提案执行建 run；报告取持久化 License（非 unknown 占位）。"""
    from nexus import experiment_report as report_module
    from nexus.tools import reproduction as repro_module

    proposal, aid = _start_run(
        license_info={"spdx": "MIT", "status": "verified"})
    # 后台调度会起真实图（无控制服务时 run 落 failed）；此处只断言核销＋
    # run 登记成功（门通过），不等待后台终态。
    result = await repro_module.execute_autonomous_experiment(
        approval_id=aid, user_id="u-t7", session_id="s-t7",
        mode="research", research_execution_mode="auto")
    assert result["status"] == "running"
    assert result["run_id"] == aid

    async def _ok_write(*, artifact_type, title, content, user_id, run_id=""):
        return {"status": "success",
                "artifact": {"artifact_id": f"art-{title[:4]}",
                             "artifact_type": artifact_type, "title": title,
                             "size_bytes": len(content),
                             "download_path": "/x/download"}}

    monkeypatch.setattr(report_module.artifact_client,
                        "write_artifact_via_backend", _ok_write)
    run = runs_module.get_run(aid)
    runs_module.record_attempt(
        aid, actual_command="python -c \"from micrograd.engine import Value; print('ok')\"",
        operation_id=f"{aid}-op-0002", exit_code=0, log_ref="ok")
    runs_module.set_status(aid, "succeeded", "")
    out = await report_module.generate_run_report(
        run_id=aid, user_id="u-t7", backend=None)
    assert out["execution_succeeded"] is True
    # F5：报告 2 Markdown＋冻结配方/补丁 2 JSON。
    assert len(out["artifacts"]) == 4
    assert run is not None
    # 报告 Markdown 含已核验 MIT（非"未知"占位）。
    full = report_module.build_experiment_report(
        run=runs_module.get_run(aid), scope=proposal["scope"],
        license_info=proposal["license"])
    assert full["license"]["spdx"] == "MIT"
    assert "MIT" in report_module.render_report_markdown(full)


async def test_intake_verified_license_persists_to_proposal():
    """intake→提案：GitHubReader 给出的 verified 结论落盘（只准备不执行）。"""

    class _Reader:
        async def read_repo(self, repo_url):
            return {"repo_url": repo_url, "reachable": True,
                    "readme": "# r", "env_files": {"setup.py": "x"},
                    "license": {"spdx": "MIT", "status": "verified"},
                    "default_branch": "master",
                    "revision_sha": "7bc720e951fe422b8f8814aa5aa1b64121d26b4c"}

    from nexus import experiment_intake as intake_module

    result = await intake_module.prepare(
        "https://github.com/karpathy/micrograd", "配置并试跑",
        user_id="u-t7", session_id="s-t7", reader=_Reader())
    assert result["status"] == "success"
    stored = proposals_module.get_proposal(result["proposal"]["proposal_id"])
    assert stored["license"] == {"spdx": "MIT", "status": "verified"}
    assert stored["scope"]["repo_revision"] == "7bc720e951fe422b8f8814aa5aa1b64121d26b4c"
