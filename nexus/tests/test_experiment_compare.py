"""F8 受控对照：共同条件＋两组冻结配方＋只关联终态运行（计划 §13）。

行为契约：
- 对照说明缺数据/hash/指标政策即拒绝；arm 少于两组、重名、配方未固定、
  变化了未声明参数、参数非标量、两组不可区分即拒绝；
- 关联只收终态运行（失败也并列）；运行无配方引用或与组声明不一致即拒绝
  （排错改了控制变量只能建新对照）；
- 指标只取运行存储报告实测值，取不到即缺失；verdict 永不做显著性判定；
- PG 行直传 _row_from_pg（F7 事故回归：禁止预先 dict(zip)）。
"""

import pytest

from nexus import experiment_compare as compare_module
from nexus import experiment_runs as runs_module


@pytest.fixture(autouse=True)
def _clean():
    compare_module.clear_memory_store()
    runs_module.clear_memory_store()
    yield
    compare_module.clear_memory_store()
    runs_module.clear_memory_store()


def _common(**over):
    base = {"data_ref": "dataset-v3", "data_hash": "sha256:abc123",
            "metric_policy": {"basis": "verified"},
            "budget": {"max_runs": 4}}
    base.update(over)
    return base


def _arms():
    return [
        {"name": "A", "recipe_hash": "deadbeef0001",
         "varied_params": {"lr": 0.01}},
        {"name": "B", "recipe_hash": "deadbeef0002",
         "varied_params": {"lr": 0.02}},
    ]


def _make_compare(**over):
    kwargs = {"owner": "u-f8", "session_id": "s-f8",
              "objective": "比较学习率", "common": _common(),
              "allowed_varied": ["lr"], "arms": _arms()}
    kwargs.update(over)
    return compare_module.create_compare(**kwargs)


def _make_run(run_id, owner="u-f8", status="succeeded",
              recipe_hash="deadbeef0001"):
    run = runs_module.create_or_get_run(
        run_id=run_id, owner=owner, session_id="s-f8",
        proposal_id="", proposal_version=0,
        scope_hash="scope-1", approval_id="")
    runs_module.record_attempt(run_id, actual_command="train --lr 0.01",
                              exit_code=0, log_ref="ok")
    runs_module.set_recipe(run_id, recipe_hash, "complete", "art-r", "art-p")
    runs_module.set_status(run_id, status, "")
    return runs_module.get_run(run_id)


def test_create_compare_ok():
    compare = _make_compare()
    assert compare["compare_id"].startswith("cmp-")
    assert compare["status"] == "open"
    assert [arm["name"] for arm in compare["arms"]] == ["A", "B"]
    assert compare["common"]["data_hash"] == "sha256:abc123"


def test_create_rejects_bad_spec():
    with pytest.raises(compare_module.CompareError) as exc:
        _make_compare(objective="  ")
    assert exc.value.code == "COMPARE_OBJECTIVE_EMPTY"
    with pytest.raises(compare_module.CompareError) as exc:
        _make_compare(arms=[{"name": "A", "recipe_hash": "deadbeef0001"}])
    assert exc.value.code == "COMPARE_ARMS_TOO_FEW"
    with pytest.raises(compare_module.CompareError) as exc:
        _make_compare(common=_common(data_hash=""))
    assert exc.value.code == "COMPARE_COMMON_INCOMPLETE"
    with pytest.raises(compare_module.CompareError) as exc:
        _make_compare(common=_common(metric_policy={}))
    assert exc.value.code == "COMPARE_COMMON_INCOMPLETE"


def test_create_rejects_bad_arms():
    dup = [_arms()[0], dict(_arms()[0], recipe_hash="deadbeef0009")]
    with pytest.raises(compare_module.CompareError) as exc:
        _make_compare(arms=dup)
    assert exc.value.code == "COMPARE_ARM_NAME_DUP"
    with pytest.raises(compare_module.CompareError) as exc:
        _make_compare(arms=[
            {"name": "A", "recipe_hash": "short", "varied_params": {"lr": 1}},
            _arms()[1]])
    assert exc.value.code == "COMPARE_RECIPE_UNPINNED"
    with pytest.raises(compare_module.CompareError) as exc:
        _make_compare(arms=[
            {"name": "A", "recipe_hash": "deadbeef0001",
             "varied_params": {"batch": 32}},
            _arms()[1]])
    assert exc.value.code == "COMPARE_PARAM_UNDECLARED"
    with pytest.raises(compare_module.CompareError) as exc:
        _make_compare(arms=[
            {"name": "A", "recipe_hash": "deadbeef0001",
             "varied_params": {"lr": {"nested": 1}}},
            _arms()[1]])
    assert exc.value.code == "COMPARE_PARAM_VALUE"
    same = [dict(_arms()[0], recipe_hash="deadbeef0009"), _arms()[1]]
    same[1] = dict(same[1], varied_params={"lr": 0.01})
    with pytest.raises(compare_module.CompareError) as exc:
        _make_compare(arms=same)
    assert exc.value.code == "COMPARE_ARMS_INDISTINGUISHABLE"


async def test_link_run_gates():
    compare = _make_compare()
    running = _make_run("run-f8-running", status="running")
    with pytest.raises(compare_module.CompareError) as exc:
        await compare_module.link_arm_run(
            compare_id=compare["compare_id"], owner="u-f8",
            arm_name="A", run_id=running["run_id"])
    assert exc.value.code == "COMPARE_RUN_NOT_TERMINAL"
    unfrozen = _make_run("run-f8-unfrozen")
    runs_module.set_recipe(unfrozen["run_id"], "", "", "", "")
    with pytest.raises(compare_module.CompareError) as exc:
        await compare_module.link_arm_run(
            compare_id=compare["compare_id"], owner="u-f8",
            arm_name="A", run_id=unfrozen["run_id"])
    assert exc.value.code == "COMPARE_RUN_UNFROZEN"
    other = _make_run("run-f8-other", recipe_hash="cafef00d0000")
    with pytest.raises(compare_module.CompareError) as exc:
        await compare_module.link_arm_run(
            compare_id=compare["compare_id"], owner="u-f8",
            arm_name="A", run_id=other["run_id"])
    assert exc.value.code == "COMPARE_RECIPE_MISMATCH"
    with pytest.raises(compare_module.CompareError) as exc:
        await compare_module.link_arm_run(
            compare_id=compare["compare_id"], owner="attacker",
            arm_name="A", run_id=other["run_id"])
    assert exc.value.code == "COMPARE_FORBIDDEN"
    with pytest.raises(compare_module.CompareError) as exc:
        await compare_module.link_arm_run(
            compare_id=compare["compare_id"], owner="u-f8",
            arm_name="Z", run_id=other["run_id"])
    assert exc.value.code == "COMPARE_ARM_UNKNOWN"


async def test_link_run_records_missing_metrics_honestly():
    compare = _make_compare()
    run = _make_run("run-f8-link")
    linked = await compare_module.link_arm_run(
        compare_id=compare["compare_id"], owner="u-f8",
        arm_name="A", run_id=run["run_id"])
    assert linked["status"] == "running"
    result = linked["arm_results"]["A"]
    assert result["run_id"] == run["run_id"]
    assert result["run_status"] == "succeeded"
    assert result["recipe_hash"] == "deadbeef0001"
    assert result["exit_code"] == 0
    # 合成运行无存储报告：指标缺失如实记录，不编造。
    assert result["metrics"] is None
    assert result["metrics_missing"]
    report = compare_module.compare_report(linked)
    assert report["verdict"] == "incomplete"
    assert "显著" in report["significance"]


async def test_link_run_carries_real_metrics(monkeypatch):
    from nexus import experiment_report as report_module

    async def _fake_report(*, run_id, user_id, backend=None):
        return ({"metrics_observed": {"acc": 0.91},
                 "metric_verdict": "PASS",
                 "comparison": [{"metric": "acc"}]}, "", "")

    monkeypatch.setattr(report_module, "build_stored_report", _fake_report)
    compare = _make_compare()
    run_a = _make_run("run-f8-ma", recipe_hash="deadbeef0001")
    run_b = _make_run("run-f8-mb", recipe_hash="deadbeef0002")
    linked = await compare_module.link_arm_run(
        compare_id=compare["compare_id"], owner="u-f8",
        arm_name="A", run_id=run_a["run_id"])
    linked = await compare_module.link_arm_run(
        compare_id=compare["compare_id"], owner="u-f8",
        arm_name="B", run_id=run_b["run_id"])
    report = compare_module.compare_report(linked)
    assert report["verdict"] == "descriptive_ready"
    assert report["rows"][0]["metrics"] == {"acc": 0.91}
    assert "显著" in report["significance"]
    assert report["verdict_reasons"] == []


async def test_failed_run_linked_not_hidden(monkeypatch):
    from nexus import experiment_report as report_module

    async def _boom(*, run_id, user_id, backend=None):
        raise report_module.ReportError("RUN_PROPOSAL_UNAVAILABLE", "x")

    monkeypatch.setattr(report_module, "build_stored_report", _boom)
    compare = _make_compare()
    failed = _make_run("run-f8-failed", status="failed",
                       recipe_hash="deadbeef0001")
    linked = await compare_module.link_arm_run(
        compare_id=compare["compare_id"], owner="u-f8",
        arm_name="A", run_id=failed["run_id"])
    report = compare_module.compare_report(linked)
    assert report["rows"][0]["run_status"] == "failed"
    assert any("失败" in note for note in report["comparability_notes"])


def test_cancel_and_foreign_denied():
    compare = _make_compare()
    cancelled = compare_module.request_cancel(compare["compare_id"], "u-f8")
    assert cancelled["status"] == "cancelled"
    with pytest.raises(compare_module.CompareError) as exc:
        compare_module.request_cancel(compare["compare_id"], "attacker")
    assert exc.value.code == "COMPARE_FORBIDDEN"
    assert compare_module.get_compare("cmp-no-such") is None


def test_list_compares_pg_rows_map_once(monkeypatch):
    """PG 行直传 _row_from_pg（F7 事故同类回归；禁止预先 dict(zip)）。"""
    import json as _json
    import sys as _sys
    import types as _types

    created = _make_compare()
    row = dict(compare_module._memory_compares[created["compare_id"]])
    pg_tuple = tuple(
        _json.dumps(row[key], ensure_ascii=False)
        if isinstance(row[key], (dict, list)) else row[key]
        for key in compare_module._JOB_KEYS
    )

    class _FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, *args, **kwargs):
            return None

        def fetchall(self):
            return [pg_tuple]

    class _FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def cursor(self):
            return _FakeCursor()

    fake_psycopg = _types.ModuleType("psycopg")
    fake_psycopg.connect = lambda *args, **kwargs: _FakeConn()
    monkeypatch.setitem(_sys.modules, "psycopg", fake_psycopg)
    monkeypatch.setattr(compare_module, "_pg_settings",
                        lambda: ("postgresql://fake/db", "nexus_checkpoints"))
    compare_module.clear_memory_store()

    items = compare_module.list_compares("u-f8", "")
    assert len(items) == 1
    assert items[0]["compare_id"] == created["compare_id"]
    assert isinstance(items[0]["created_at"], float)


async def test_compare_http_endpoints(monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from nexus.main import app

    compare_module.clear_memory_store()
    monkeypatch.delenv("NEXUS_API_KEY", raising=False)
    user = {"X-Nexus-User-Id": "u-http"}
    payload = {"objective": "比较学习率",
               "common": {"data_ref": "d", "data_hash": "h",
                          "metric_policy": {"basis": "verified"}},
               "allowed_varied": ["lr"], "arms": _arms()}
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://test") as client:
        created = await client.post("/api/v1/nexus/compares", json=payload,
                                    headers=user)
        assert created.status_code == 200, created.text
        compare_id = created.json()["compare"]["compare_id"]
        assert created.json()["compare"]["report"]["verdict"] == "incomplete"
        listed = await client.get("/api/v1/nexus/compares", headers=user)
        assert any(item["compare_id"] == compare_id
                   for item in listed.json()["compares"])
        queried = await client.get(f"/api/v1/nexus/compares/{compare_id}",
                                   headers=user)
        assert queried.status_code == 200
        assert queried.json()["compare"]["report"]["significance"]
        cross = await client.get(f"/api/v1/nexus/compares/{compare_id}",
                                 headers={"X-Nexus-User-Id": "attacker"})
        assert cross.status_code == 404
        bad = await client.post("/api/v1/nexus/compares",
                                json={"objective": "x", "arms": []},
                                headers=user)
        assert bad.status_code == 400
        link_missing = await client.post(
            f"/api/v1/nexus/compares/{compare_id}/link-run",
            json={"arm_name": "A", "run_id": "run-no-such"}, headers=user)
        assert link_missing.status_code == 404
        cancelled = await client.post(
            f"/api/v1/nexus/compares/{compare_id}/cancel", headers=user)
        assert cancelled.json()["compare"]["status"] == "cancelled"
