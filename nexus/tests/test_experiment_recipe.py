"""F5 冻结配方（计划 §10）：最终方案提炼＋冻结＋完整性（纯函数）。"""

from nexus import experiment_recipe as recipe_module


def _attempt(no, command, exit_code, op_kind="target"):
    return {"attempt_no": no, "actual_command": command, "exit_code": exit_code,
            "config_changes": {"kind": "execute", "op_kind": op_kind},
            "operation_id": f"run-op-{no:04d}"}


def _scope(mode="smoke"):
    return {"objective": "x", "repo_url": "https://github.com/e/r",
            "repo_revision": "deadbeef1234", "source_refs": [], "data_refs": [],
            "network_profile": "p", "resources": {}, "mode": mode}


def test_final_chain_keeps_success_env_and_target_only():
    attempts = [
        _attempt(1, "pip install -r requirements.txt", 1, "environment"),
        _attempt(2, "pip install -r requirements.txt", 0, "environment"),
        _attempt(3, "pip install fakepkg", 0, "environment"),
        _attempt(4, "pwd", 0, "probe"),
        _attempt(5, "python train.py", 1, "target"),
        _attempt(6, "python train.py", 0, "target"),
        _attempt(7, "ls /workspace", 0, "probe"),
    ]
    chain = recipe_module.final_chain(attempts)
    assert [s["command"] for s in chain["env_setup"]] == [
        "pip install -r requirements.txt", "pip install fakepkg"]
    assert [s["command"] for s in chain["target"]] == ["python train.py"]
    assert chain["curated"] is False
    assert chain["excluded"].get("probe", 0) >= 1
    assert chain["excluded"].get("failed_or_empty", 0) == 2


def test_curated_verified_and_dropped():
    attempts = [_attempt(2, "pip install fakepkg", 0, "environment"),
                _attempt(6, "python train.py", 0, "target")]
    chain = recipe_module.final_chain(
        attempts, {"steps": [{"attempt_no": 6}, {"command": "rm -rf /"},
                             {"command": "pip install fakepkg"}],
                   "note": "model"})
    assert chain["curated"] is True
    assert [s["command"] for s in chain["target"]] == ["python train.py"]
    assert any("rm -rf" in str(d) for d in chain["dropped"])


def test_curated_unlocatable_falls_back():
    attempts = [_attempt(6, "python train.py", 0, "target")]
    chain = recipe_module.final_chain(attempts, {"steps": [{"command": "nope"}]})
    assert chain["curated"] is False
    assert [s["command"] for s in chain["target"]] == ["python train.py"]


def test_freeze_complete_and_hash_stable():
    run = {"run_id": "r1", "proposal_id": "p1", "scope_hash": "h",
           "attempts": [_attempt(1, "pip install x", 0, "environment"),
                        _attempt(2, "python train.py", 0, "target")]}
    exports = {"diff_text": "diff --git a/x b/x",
               "files": [{"path": "/workspace/train.py", "sha256": "s",
                          "size_bytes": 10, "content": "print(1)"}],
               "pip_freeze": "fakepkg==1.0",
               "data_hashes": {}}
    first = recipe_module.freeze_recipe(
        run=run, scope=_scope(), exports=exports,
        image="img", image_digest="sha256:abc")
    assert first["completeness"] == "complete"
    assert first["missing"] == []
    assert first["recipe_id"].startswith("rcp-")
    second = recipe_module.freeze_recipe(
        run=run, scope=_scope(), exports=exports,
        image="img", image_digest="sha256:abc")
    assert second["recipe_hash"] == first["recipe_hash"], "冻结确定性"


def test_freeze_incomplete_lists_missing():
    run = {"run_id": "r1", "proposal_id": "p1", "scope_hash": "h", "attempts": []}
    recipe = recipe_module.freeze_recipe(run=run, scope=_scope("reproduce"),
                                         exports=None)
    assert recipe["completeness"] == "incomplete"
    for key in ("target_commands", "image_digest", "patch_or_files"):
        assert key in recipe["missing"]
    # smoke 不要求指标政策；reproduce 要求。
    assert "metric_policy" in recipe["missing"]
    smoke = recipe_module.freeze_recipe(
        run={"run_id": "r1", "proposal_id": "p1", "scope_hash": "h",
             "attempts": [_attempt(1, "python train.py", 0, "target")]},
        scope=_scope("smoke"), exports=None, image="img",
        image_digest="sha256:abc")
    assert "metric_policy" not in smoke["missing"]


def test_denied_paths_excluded():
    assert recipe_module.is_denied_path("/workspace/.env") is True
    assert recipe_module.is_denied_path("/workspace/id_token.json") is True
    assert recipe_module.is_denied_path("/workspace/train.py") is False
    run = {"run_id": "r1", "proposal_id": "p1", "scope_hash": "h",
           "attempts": [_attempt(1, "python train.py", 0, "target")]}
    recipe = recipe_module.freeze_recipe(
        run=run, scope=_scope(), image="img", image_digest="sha256:abc",
        exports={"files": [{"path": "/workspace/.env", "sha256": "s",
                            "size_bytes": 5, "content": "K=V"},
                           {"path": "/workspace/train.py", "sha256": "t",
                            "size_bytes": 5, "content": "x"}]})
    paths = [item["path"] for item in recipe["patch"]["files"]]
    assert "/workspace/train.py" in paths
    assert "/workspace/.env" not in paths


def test_render_recipe_json_strips_inline_content():
    run = {"run_id": "r1", "proposal_id": "p1", "scope_hash": "h",
           "attempts": [_attempt(1, "python train.py", 0, "target")]}
    recipe = recipe_module.freeze_recipe(
        run=run, scope=_scope(), image="img", image_digest="sha256:abc",
        exports={"files": [{"path": "/workspace/train.py", "sha256": "t",
                            "size_bytes": 5, "content": "print(1)"}]})
    import json as _json

    slim = _json.loads(recipe_module.render_recipe_json(recipe))
    assert slim["patch"]["files"][0]["content"] is None
    assert slim["patch"]["files"][0]["sha256"] == "t"
    assert slim["recipe_hash"] == recipe["recipe_hash"]
