"""T6 交付环境配方与真实结果（接既有 Artifact）。

行为契约（任务书 T6）：
- 收集固定 repo SHA＋实际补丁、依赖锁/镜像 digest、数据来源/hash、执行
  命令、参数、seed、日志引用与实际指标；保存后才回收可变工作区；
- 配方和结果关联本 run；报告区分 environment_ready / execution_succeeded /
  metric_verdict / clean_verification；没有指标就是 not_evaluated，B 未
  执行就是 not_run；
- 用户得到"做了什么、修了什么、跑出什么、如何再跑"的 Markdown 报告和可
  下载配方/日志；产物经现有 owner/session 校验；
- exit 0 不等于论文复现成功（任务书示例断言）。

全调用真实业务代码；Artifact 写入与控制回收经注入替身（ tracking 调用
顺序，断言"先落盘后回收"）。
"""

import pytest

from nexus import approvals
from nexus import experiment_runs as runs_module
from nexus import proposals as proposals_module


@pytest.fixture(autouse=True)
def _clean_stores():
    approvals.clear_memory_store()
    proposals_module.clear_memory_store()
    runs_module.clear_memory_store()
    yield
    approvals.clear_memory_store()
    proposals_module.clear_memory_store()
    runs_module.clear_memory_store()


def _scope():
    return {
        "objective": "配置并试跑", "repo_url": "https://github.com/example/r",
        "repo_revision": "deadbeef1234", "source_refs": [], "data_refs": [],
        "network_profile": "pypi-allowed",
        "resources": {"cpu": 1.0, "memory_mb": 2048, "disk_mb": 5120,
                      "wall_time_s": 1800},
        "mode": "smoke", "allow_environment_repair": True,
    }


def _make_run(user_id="u-t6", session_id="s-t6", scope=None):
    proposal = proposals_module.create_proposal(
        user_id=user_id, session_id=session_id, preset=None,
        kind="autonomous_experiment", scope=scope or _scope())
    req = proposals_module.request_approval_for_proposal(
        proposal["proposal_id"], user_id=user_id,
        expected_version=proposal["version"])
    aid = req["approval"]["approval_id"]
    approvals.decide_approval(aid, user_id, "approved")
    approvals.consume_approval(aid, user_id=user_id, session_id=session_id,
                               preset={})
    run = runs_module.create_or_get_run(
        run_id=aid, owner=user_id, session_id=session_id,
        proposal_id=proposal["proposal_id"], proposal_version=1,
        scope_hash=proposal["scope_hash"], approval_id=aid)
    return run, proposal


def _attempts_ok(run_id):
    runs_module.record_attempt(
        run_id, actual_command="pip install -r requirements.txt",
        operation_id=f"{run_id}-op-0002", exit_code=0, log_ref="ok")
    runs_module.record_attempt(
        run_id, actual_command="python train.py",
        operation_id=f"{run_id}-op-0003", exit_code=0, log_ref="loss=0.5")


def _report(exit_code=0, metrics=None, clean_b=None):
    """任务书示例形态：只组装输入，判定走真实 build。"""
    from nexus import experiment_report as report_module

    run, _proposal = _make_run()
    if exit_code == 0:
        _attempts_ok(run["run_id"])
    else:
        runs_module.record_attempt(
            run["run_id"], actual_command="python train.py",
            operation_id=f"{run['run_id']}-op-0002", exit_code=exit_code,
            log_ref="traceback")
    runs_module.set_status(run["run_id"],
                           "succeeded" if exit_code == 0 else "failed", "")
    return report_module.build_experiment_report(
        run=runs_module.get_run(run["run_id"]),
        scope=_scope(), license_info={"spdx": "MIT", "status": "verified"},
        image="repro-task:1.4.0", image_digest="sha256:4f2ba29b",
        metrics=metrics, clean=clean_b)


async def test_stored_report_takes_image_digest_from_control_plane():
    """A7：配方镜像 digest 来自控制面 lifecycle，不是 scope 里的虚构字段。"""
    from nexus import experiment_report as report_module

    run, _proposal = _make_run()
    _attempts_ok(run["run_id"])
    runs_module.set_status(run["run_id"], "succeeded", "")

    class _FakeBackend:
        async def sandbox_status(self):
            return {"image": "repro-task:1.4.0",
                    "image_digest": "sha256:4f2ba29b"}

    report, _markdown, recipe_md = await report_module.build_stored_report(
        run_id=run["run_id"], user_id="u-t6", backend=_FakeBackend())
    assert report["recipe"]["image_digest"] == "sha256:4f2ba29b"
    assert report["recipe"]["base_image"] == "repro-task:1.4.0"
    assert "sha256:4f2ba29b" in recipe_md

    class _Down:
        async def sandbox_status(self):
            raise RuntimeError("control down")

    fallback, _md, _recipe = await report_module.build_stored_report(
        run_id=run["run_id"], user_id="u-t6", backend=_Down())
    assert fallback["recipe"]["image_digest"] == "", "控制面不可达如实留空"


def test_exit_zero_is_not_paper_success():
    report = _report(exit_code=0, metrics=None, clean_b=None)
    assert report["execution_succeeded"] is True
    assert report["metric_verdict"] == "not_evaluated"
    assert report["clean_verification"] == "not_run"
    assert report.get("reproducible") is not True


def test_failed_run_marks_execution_failed():
    report = _report(exit_code=1, metrics=None, clean_b=None)
    assert report["execution_succeeded"] is False
    assert report["metric_verdict"] == "not_evaluated"
    assert "reproducible" not in report or report.get("reproducible") is not True


def test_metrics_compare_deterministically():
    report = _report(
        exit_code=0,
        metrics={"observed": {"val_loss": 1.89},
                 "expected": {"val_loss": {"target": 1.88, "tolerance": 0.06}}},
        clean_b=None)
    assert report["metric_verdict"] == "PASS"
    assert report["comparison"][0]["observed"] == 1.89
    bad = _report(
        exit_code=0,
        metrics={"observed": {"val_loss": 2.5},
                 "expected": {"val_loss": {"target": 1.88, "tolerance": 0.06}}},
        clean_b=None)
    assert bad["metric_verdict"] == "FAIL"


def test_clean_b_verdict_passthrough():
    report = _report(
        exit_code=0, metrics=None,
        clean_b={"status": "passed", "note": "clean env ok"})
    assert report["clean_verification"] == "passed"
    assert _report(exit_code=0)["clean_verification"] == "not_run"


def test_recipe_pins_revision_image_and_commands():
    from nexus import experiment_report as report_module

    run, _proposal = _make_run()
    _attempts_ok(run["run_id"])
    runs_module.set_status(run["run_id"], "succeeded", "")
    report = report_module.build_experiment_report(
        run=runs_module.get_run(run["run_id"]), scope=_scope(),
        license_info={"spdx": "MIT", "status": "verified"},
        image="repro-task:1.4.0", image_digest="sha256:4f2ba29b")
    recipe = report["recipe"]
    assert recipe["repo_url"] == "https://github.com/example/r"
    assert recipe["repo_revision"] == "deadbeef1234"
    assert recipe["revision_pinned"] is True
    assert recipe["base_image"] == "repro-task:1.4.0"
    assert recipe["image_digest"] == "sha256:4f2ba29b"
    assert [s["command"] for s in recipe["steps"]] == [
        "pip install -r requirements.txt", "python train.py"]
    assert recipe["generated_from_run"] == run["run_id"]
    # seed 未跟踪：如实 null，不编造。
    assert recipe["seed"] is None
    markdown = report_module.render_recipe_markdown(report)
    assert "pip install -r requirements.txt" in markdown
    assert "repro-task:1.4.0" in markdown


def test_report_markdown_has_four_sections():
    from nexus import experiment_report as report_module

    report = _report(exit_code=0, metrics=None, clean_b=None)
    text = report_module.render_report_markdown(report)
    for section in ("做了什么", "修了什么", "跑出什么", "如何再跑"):
        assert section in text
    assert "not_evaluated" in text or "未评估" in text
    assert "claim_refs" not in text


def test_report_records_repair_history():
    """修了什么：失败 attempt 与其后成功的命令如实列出（不编造因果）。"""
    from nexus import experiment_report as report_module

    run, _proposal = _make_run()
    runs_module.record_attempt(
        run["run_id"], actual_command="python train.py",
        operation_id=f"{run['run_id']}-op-0002", exit_code=1,
        log_ref="ModuleNotFoundError: No module named 'fakepkg'")
    runs_module.record_attempt(
        run["run_id"], actual_command="pip install fakepkg",
        operation_id=f"{run['run_id']}-op-0003", exit_code=0, log_ref="ok")
    runs_module.record_attempt(
        run["run_id"], actual_command="python train.py",
        operation_id=f"{run['run_id']}-op-0004", exit_code=0, log_ref="loss=0.5")
    runs_module.set_status(run["run_id"], "succeeded", "")
    report = report_module.build_experiment_report(
        run=runs_module.get_run(run["run_id"]), scope=_scope(),
        license_info={"spdx": "MIT", "status": "verified"},
        image="repro-task:1.4.0", image_digest="sha256:4f2ba29b")
    failures = report["failures"]
    assert len(failures) == 1
    assert "fakepkg" in failures[0]["log_tail"]
    assert "PASS" not in report_module.render_report_markdown(report)


async def test_generate_writes_artifacts_then_recycles(monkeypatch):
    """保存后才回收：artifact 写入全部成功后才调控制取消；写入失败不回收."""
    from nexus import experiment_report as report_module

    calls: list = []

    async def _fake_write(*, artifact_type, title, content, user_id, run_id=""):
        calls.append(("write", artifact_type, title))
        return {"status": "success",
                "artifact": {"artifact_id": f"art-{len(calls)}",
                             "artifact_type": artifact_type, "title": title,
                             "size_bytes": len(content),
                             "download_path": f"/api/v1/nexus/artifacts/art-{len(calls)}/download"}}

    class _FakeBackend:
        async def cancel(self):
            calls.append(("cancel",))
            return {"status": "cancelled"}

    monkeypatch.setattr(report_module.artifact_client,
                        "write_artifact_via_backend", _fake_write)
    run, _proposal = _make_run()
    _attempts_ok(run["run_id"])
    runs_module.set_status(run["run_id"], "succeeded", "")
    result = await report_module.generate_run_report(
        run_id=run["run_id"], user_id="u-t6", backend=_FakeBackend())
    assert result["content_version"] == "experiment-report/1"
    # F5：报告 2 Markdown＋冻结配方/补丁 2 JSON（产物先落盘后回收）。
    assert len(result["artifacts"]) == 4
    assert result["recipe_hash"] == runs_module.get_run(run["run_id"])["recipe_hash"]
    assert [c[0] for c in calls] == ["write", "write", "write", "write", "cancel"]
    # 写入失败 → 不回收，调用方得 502 语义（此处抛 ReportError）。
    async def _failing_write(**kwargs):
        calls.append(("write-fail",))
        return {"status": "unavailable", "code": "ARTIFACT_UNAVAILABLE",
                "detail": "down"}

    monkeypatch.setattr(report_module.artifact_client,
                        "write_artifact_via_backend", _failing_write)
    n_cancel_before = len([c for c in calls if c[0] == "cancel"])
    with pytest.raises(report_module.ReportError) as exc:
        await report_module.generate_run_report(
            run_id=run["run_id"], user_id="u-t6", backend=_FakeBackend())
    assert exc.value.code == "REPORT_ARTIFACT_WRITE_FAILED"
    assert len([c for c in calls if c[0] == "cancel"]) == n_cancel_before


async def test_generate_rejects_unfinished_and_foreign():
    from nexus import experiment_report as report_module

    run, _proposal = _make_run()
    with pytest.raises(report_module.ReportError) as exc:
        await report_module.generate_run_report(
            run_id=run["run_id"], user_id="u-t6", backend=None)
    assert exc.value.code == "RUN_NOT_FINISHED"
    runs_module.request_cancel(run["run_id"], "u-t6")
    runs_module.set_status(run["run_id"], "cancelled", "")
    with pytest.raises(report_module.ReportError) as exc2:
        await report_module.generate_run_report(
            run_id=run["run_id"], user_id="u-t6", backend=None)
    assert exc2.value.code == "RUN_CANCELLED"
    with pytest.raises(report_module.ReportError) as exc3:
        await report_module.generate_run_report(
            run_id=run["run_id"], user_id="attacker", backend=None)
    assert exc3.value.code == "RUN_FORBIDDEN"


async def test_report_http_endpoint(monkeypatch):
    """Runtime 报告端点：成功 200＋产物；跨用户 404；运行中 409；写入失败 502。"""
    from httpx import ASGITransport, AsyncClient

    from nexus import experiment_report as report_module
    from nexus.main import app

    monkeypatch.delenv("NEXUS_API_KEY", raising=False)

    async def _ok_write(*, artifact_type, title, content, user_id, run_id=""):
        return {"status": "success",
                "artifact": {"artifact_id": f"art-{title[:4]}",
                             "artifact_type": artifact_type, "title": title,
                             "size_bytes": len(content),
                             "download_path": "/api/v1/nexus/artifacts/x/download"}}

    monkeypatch.setattr(report_module.artifact_client,
                        "write_artifact_via_backend", _ok_write)
    run, _proposal = _make_run(user_id="u-http", session_id="s-http")
    _attempts_ok(run["run_id"])
    runs_module.set_status(run["run_id"], "succeeded", "")
    user = {"X-Nexus-User-Id": "u-http"}
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://test") as client:
        ok_resp = await client.post(
            f"/api/v1/nexus/repro/runs/{run['run_id']}/report", headers=user)
        assert ok_resp.status_code == 200, ok_resp.text
        body = ok_resp.json()
        assert body["execution_succeeded"] is True
        assert body["metric_verdict"] == "not_evaluated"
        assert len(body["artifacts"]) == 4
        assert body["content_version"] == "experiment-report/1"
        # 跨用户 → 404（不区分不存在/他人）。
        cross = await client.post(
            f"/api/v1/nexus/repro/runs/{run['run_id']}/report",
            headers={"X-Nexus-User-Id": "attacker"})
        assert cross.status_code == 404
        # 运行中 → 409。
        run2, _p2 = _make_run(user_id="u-http", session_id="s-http")
        busy = await client.post(
            f"/api/v1/nexus/repro/runs/{run2['run_id']}/report", headers=user)
        assert busy.status_code == 409

    async def _bad_write(**kwargs):
        return {"status": "unavailable", "code": "ARTIFACT_UNAVAILABLE",
                "detail": "down"}

    monkeypatch.setattr(report_module.artifact_client,
                        "write_artifact_via_backend", _bad_write)
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://test") as client:
        fail = await client.post(
            f"/api/v1/nexus/repro/runs/{run['run_id']}/report", headers=user)
        assert fail.status_code == 502


# ── F1：按目标判定结果（计划 §6） ──

def _f1_run_with(attempt_specs, scope=None):
    from nexus import experiment_report as report_module

    run, _proposal = _make_run(scope=scope)
    for index, (command, exit_code) in enumerate(attempt_specs, start=2):
        runs_module.record_attempt(
            run["run_id"], actual_command=command,
            operation_id=f"{run['run_id']}-op-{index:04d}", exit_code=exit_code,
            log_ref="log")
    runs_module.set_status(run["run_id"], "succeeded", "")
    return report_module.build_experiment_report(
        run=runs_module.get_run(run["run_id"]), scope=scope or _scope(),
        license_info={"spdx": "MIT", "status": "verified"})


def test_f1_target_failure_not_covered_by_probe():
    """目标失败后 pwd 成功不得覆盖结论；环境来自安装成功."""
    report = _f1_run_with([
        ("pip install -r requirements.txt", 0),
        ("python train.py", 1),
        ("pwd", 0),
    ])
    assert report["environment_ready"] is True
    assert report["execution_succeeded"] is False
    assert report["operation_summary"].get("target") == 1
    assert report["operation_summary"].get("probe", 0) >= 1


def test_f1_environment_not_from_image_route():
    """仅有探测（无 environment 类成功）即环境未就绪；无 target 即未完成."""
    report = _f1_run_with([("ls /workspace", 0)])
    assert report["environment_ready"] is False
    assert report["execution_succeeded"] is False
    assert report["legacy_target"] is True


def test_f1_setup_mode_ignores_metrics():
    report = _f1_run_with(
        [("pip install -r requirements.txt", 0),
         ("python train.py", 0)],
        scope={**_scope(), "mode": "setup"},
        )
    # setup 目标本就不含指标：即使传入 metrics 也不评估。
    from nexus import experiment_report as report_module

    run, _proposal = _make_run(scope={**_scope(), "mode": "setup"})
    runs_module.record_attempt(
        run["run_id"], actual_command="pip install -r requirements.txt",
        operation_id=f"{run['run_id']}-op-0002", exit_code=0, log_ref="ok")
    runs_module.set_status(run["run_id"], "succeeded", "")
    with_metrics = report_module.build_experiment_report(
        run=runs_module.get_run(run["run_id"]),
        scope={**_scope(), "mode": "setup"},
        metrics={"observed": {"a": 1.0},
                 "expected": {"a": {"target": 1.0, "tolerance": 0.1}}})
    assert with_metrics["metric_verdict"] == "not_evaluated"
    assert "setup" in (with_metrics.get("metric_note") or "")
    assert report["goal"]["mode"] == "setup"
    assert report["goal"]["requires_metrics"] is False


def test_f1_metric_policy_mismatch_rejected():
    """冻结政策与调用方期望不一致→拒绝评估（禁改阈值凑 PASS）."""
    from nexus import experiment_report as report_module

    scope = {**_scope(), "mode": "reproduce",
             "metric_policy": {"val_loss": {"target": 1.88, "tolerance": 0.06}}}
    run, _proposal = _make_run(scope=scope)
    runs_module.record_attempt(
        run["run_id"], actual_command="pip install -r requirements.txt",
        operation_id=f"{run['run_id']}-op-0002", exit_code=0, log_ref="ok")
    runs_module.record_attempt(
        run["run_id"], actual_command="python train.py",
        operation_id=f"{run['run_id']}-op-0003", exit_code=0, log_ref="ok")
    runs_module.set_status(run["run_id"], "succeeded", "")
    tampered = report_module.build_experiment_report(
        run=runs_module.get_run(run["run_id"]), scope=scope,
        metrics={"observed": {"val_loss": 1.88},
                 "expected": {"val_loss": {"target": 9.99, "tolerance": 5.0}}})
    assert tampered["metric_verdict"] == "not_evaluated"
    assert "冻结" in (tampered.get("metric_note") or "")
    honest = report_module.build_experiment_report(
        run=runs_module.get_run(run["run_id"]), scope=scope,
        metrics={"observed": {"val_loss": 1.89},
                 "expected": {"val_loss": {"target": 1.88, "tolerance": 0.06}}})
    assert honest["metric_verdict"] == "PASS"
    assert honest["metric_basis"] == "frozen_policy"


async def test_f1_stored_report_marks_legacy_clean():
    """旧规则干净结论仅作历史记录，不得当作新规则通过."""
    from nexus import experiment_clean as clean_module
    from nexus import experiment_report as report_module

    run, _proposal = _make_run()
    runs_module.record_attempt(
        run["run_id"], actual_command="pip install -r requirements.txt",
        operation_id=f"{run['run_id']}-op-0002", exit_code=0, log_ref="ok")
    runs_module.record_attempt(
        run["run_id"], actual_command="python train.py",
        operation_id=f"{run['run_id']}-op-0003", exit_code=0, log_ref="ok")
    runs_module.set_status(run["run_id"], "succeeded", "")
    runs_module.set_clean_verdict(run["run_id"], "passed", "旧结论", rule="sr6-clean/1")
    assert clean_module.CLEAN_RULE_VERSION != "sr6-clean/1"
    report, markdown, _recipe = await report_module.build_stored_report(
        run_id=run["run_id"], user_id="u-t6", backend=None)
    assert report["clean_verification"] == "not_run"
    assert "历史命令一致性记录" in (report.get("clean_note") or "")
    assert "历史命令一致性记录" in markdown


def test_f1_contracts_classify_and_goal():
    from nexus import experiment_contracts as contracts_module

    assert contracts_module.classify_operation("pip install -r requirements.txt") == "environment"
    assert contracts_module.classify_operation("python train.py") == "target"
    assert contracts_module.classify_operation("pwd") == "probe"
    assert contracts_module.classify_operation("ls /workspace") == "probe"
    assert contracts_module.classify_operation("write_file x", "file_tool") == "file_tool"
    assert contracts_module.derive_goal({"mode": "setup"})["requires_target"] is False
    assert contracts_module.derive_goal({"mode": "smoke"})["requires_target"] is True
    assert contracts_module.derive_goal({"mode": "reproduce"})["requires_metrics"] is True
