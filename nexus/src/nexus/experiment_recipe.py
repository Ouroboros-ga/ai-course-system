"""F5 最终配方冻结（FrozenRecipe）：B 重现的是 A 的最终方案，不是失败史重演。

- 最终步骤：默认启发式＝成功的 environment 安装去重＋成功的 target 命令
  保序（诊断/失败安装/探测/文件工具不进 B 脚本）；模型整理结果（curated）
  可覆盖，但平台逐条核对引用（attempt 编号/命令原文/文件路径三者至少居
  其一可定位），核对不上即剔除＋留痕，不静默吞掉。
- 冻结内容：源码 SHA、实际文件变更（内容快照 hashing＋引用，大文件只存
  可验证引用）、新增文件、执行镜像身份、依赖锁定、数据清单/hash、目标
  命令、参数、种子、指标政策；未知字段显式标缺失。
- 完整性：按 mode 分级要求；缺关键项 → incomplete（配方仍可下载，验证
  不得判 passed，不能自动补编）。
- recipe_id/hash：规范 JSON 的 sha256（不可变；新版本即新 hash）。
- 本模块纯函数为主（exports 以数据传入）；容器采集见 clean.py。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

RECIPE_VERSION = "frozen-recipe/1"

# 采集排除（凭据/缓存/无关文件/未授权数据不进配方；大小另行封顶）。
DENIED_PATH_SUBSTRINGS = (
    ".env", "secret", "token", "password", "credential", ".git/",
    "__pycache__", ".pyc", ".venv/", "node_modules/", ".cache/",
    ".pytest_cache/", "*.egg-info",
)
# 单文件内容快照上限（超限只存引用＋hash＋size，不重复拷贝）。
FILE_SNAPSHOT_MAX_BYTES = 256 * 1024
# diff 文本上限。
DIFF_MAX_BYTES = 512 * 1024


class RecipeError(Exception):
    """配方域失败：携带机器可读 code（fail-closed 语义）。"""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


def recipe_hash(recipe: dict[str, Any]) -> str:
    """规范 hash（排序键 JSON 的 sha256 前 32 hex；recipe_id 源）。"""
    canonical = json.dumps(recipe, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def recipe_id_for(recipe: dict[str, Any]) -> str:
    return f"rcp-{recipe_hash(recipe)[:12]}"


def is_denied_path(path: str) -> bool:
    """采集排除判定（纯函数，可单测）。"""
    lowered = (path or "").lower()
    for marker in DENIED_PATH_SUBSTRINGS:
        if marker.startswith("*"):
            if lowered.endswith(marker[1:]):
                return True
        elif marker in lowered:
            return True
    return False


def _attempt_op_kind(attempt: dict[str, Any]) -> str:
    return str((attempt.get("config_changes") or {}).get("op_kind") or "")


def final_chain(attempts: list[dict[str, Any]],
                curated: dict[str, Any] | None = None) -> dict[str, Any]:
    """最终步骤提炼（纯函数，可单测）。

    默认启发式：成功的 environment 安装（按命令去重保序）＋成功的 target
    命令（保序）；其余只计数不收录。curated 覆盖时：
    curated = {"steps": [{"command": ...} 或 {"attempt_no": N}], "note": ...}，
    平台逐条核对（attempt 编号命中，或命令原文在成功记录中出现，或引用
    文件路径真实存在——路径存在性由调用方经 files_present 传入）；
    核对不上即剔除＋dropped 留痕。
    返回 {"env_setup": [...], "target": [...], "excluded": {...},
            "curated": bool, "dropped": [...]}。
    """
    steps = _heuristic_chain(attempts or [])
    if not curated:
        return steps
    verified, dropped = _verify_curated(curated, attempts or [])
    if verified is None:
        steps["dropped"] = list((curated.get("steps") or []))[:20]
        return steps
    steps["env_setup"] = verified["env_setup"]
    steps["target"] = verified["target"]
    steps["curated"] = True
    steps["dropped"] = dropped
    steps["curated_note"] = str(curated.get("note") or "")[:500]
    return steps


def _heuristic_chain(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    env_setup: list[dict[str, Any]] = []
    target: list[dict[str, Any]] = []
    seen_commands: set[str] = set()
    excluded: dict[str, int] = {}
    for attempt in attempts:
        command = str(attempt.get("actual_command") or "")
        kind = _attempt_op_kind(attempt)
        exit_code = attempt.get("exit_code")
        if not command or exit_code != 0:
            excluded["failed_or_empty"] = excluded.get("failed_or_empty", 0) + 1
            continue
        if kind == "environment":
            if command in seen_commands:
                excluded["duplicate_env"] = excluded.get("duplicate_env", 0) + 1
                continue
            seen_commands.add(command)
            env_setup.append({"attempt_no": attempt.get("attempt_no", 0),
                              "command": command, "exit_code": 0})
        elif kind == "target":
            target.append({"attempt_no": attempt.get("attempt_no", 0),
                           "command": command, "exit_code": 0})
        else:
            excluded[kind or "unclassified"] = excluded.get(kind or "unclassified", 0) + 1
    return {"env_setup": env_setup, "target": target, "excluded": excluded,
            "curated": False, "dropped": []}


def _verify_curated(curated: dict[str, Any],
                    attempts: list[dict[str, Any]]) -> tuple[dict[str, list], list] | tuple[None, list]:
    """核对模型整理结果；全不可定位即 (None, dropped)。"""
    raw_steps = curated.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        return None, []
    by_no = {int(a.get("attempt_no", 0)): a for a in attempts}
    success_commands = {str(a.get("actual_command") or "") for a in attempts
                        if a.get("exit_code") == 0
                        and str(a.get("actual_command") or "")}
    files_present = set(curated.get("files_present") or [])
    env_setup: list[dict[str, Any]] = []
    target: list[dict[str, Any]] = []
    dropped: list[Any] = []
    for step in raw_steps:
        command = ""
        attempt_no = 0
        if isinstance(step, dict):
            attempt_no = int(step.get("attempt_no") or 0)
            command = str(step.get("command") or "")
            if attempt_no and attempt_no in by_no:
                source = by_no[attempt_no]
                command = command or str(source.get("actual_command") or "")
        elif isinstance(step, str):
            command = step
        command = command.strip()
        if not command:
            dropped.append(step)
            continue
        located = (attempt_no and attempt_no in by_no) \
            or command in success_commands \
            or any(command.strip() == path or command.strip().endswith("/" + path.lstrip("/"))
                   for path in files_present if isinstance(path, str))
        if not located:
            dropped.append(step)
            continue
        kind = _attempt_op_kind(by_no.get(attempt_no, {})) if attempt_no else ""
        if not kind:
            try:
                from nexus import experiment_contracts as contracts_module

                kind = contracts_module.classify_operation(command)
            except Exception:  # noqa: BLE001
                kind = ""
        source = by_no.get(attempt_no, {}) if attempt_no else {}
        located_exit = source.get("exit_code")
        if located_exit is None and command in success_commands:
            located_exit = 0
        bucket = env_setup if kind == "environment" else target
        bucket.append({"attempt_no": attempt_no, "command": command,
                       "exit_code": located_exit})
    if not env_setup and not target:
        return None, dropped[:20]
    return {"env_setup": env_setup, "target": target}, dropped[:20]


def freeze_recipe(*, run: dict[str, Any], scope: dict[str, Any],
                  proposal: dict[str, Any] | None = None,
                  exports: dict[str, Any] | None = None,
                  image: str = "", image_digest: str = "",
                  curated: dict[str, Any] | None = None,
                  ) -> dict[str, Any]:
    """冻结配方（纯函数；exports 缺席即记缺失，不猜）。

    exports（clean/report 采集）: {
      "diff_text": str, "files": [{path, sha256, size_bytes, content?}],
      "deleted": [path], "pip_freeze": str, "conda_export": str,
      "data_hashes": {url: sha256}, "seeds": {...}, "params": {...} }
    返回 FrozenRecipe（含 recipe_id/hash/completeness/missing）。
    """
    exports = exports or {}
    scope = scope or {}
    attempts = list(run.get("attempts", []) or [])
    chain = final_chain(attempts, curated)
    mode = str(scope.get("mode") or "smoke")
    revision = str(scope.get("repo_revision") or "")
    files = []
    for item in exports.get("files") or []:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "")
        if not path or is_denied_path(path):
            continue
        files.append({
            "path": path,
            "sha256": str(item.get("sha256") or ""),
            "size_bytes": int(item.get("size_bytes") or 0),
            "via": "content" if item.get("content") else "reference",
            "content": item.get("content") if item.get("content") else None,
        })
    data_refs = list(scope.get("data_refs") or [])
    data_hashes = dict(exports.get("data_hashes") or {})
    metric_policy = None
    if isinstance(proposal, dict):
        metric_policy = (proposal.get("metric_policy")
                         or (proposal.get("scope") or {}).get("metric_policy"))
    recipe = {
        "version": RECIPE_VERSION,
        "run_id": str(run.get("run_id", "")),
        "proposal_id": str(run.get("proposal_id", "")),
        "scope_hash": str(run.get("scope_hash", "")),
        "mode": mode,
        "repo": {"url": str(scope.get("repo_url") or ""),
                 "revision": revision},
        "patch": {
            "diff_text": str(exports.get("diff_text") or "")[:DIFF_MAX_BYTES],
            "diff_truncated": len(str(exports.get("diff_text") or "")) > DIFF_MAX_BYTES,
            "files": files,
            "deleted": [str(p) for p in (exports.get("deleted") or [])][:100],
        },
        "image": {"base": image or "",
                  "digest": image_digest or "",
                  "build_image": str(exports.get("build_image") or ""),
                  "exec_image": str(exports.get("exec_image") or "")},
        "dependencies": {
            "pip_freeze": str(exports.get("pip_freeze") or ""),
            "conda_export": str(exports.get("conda_export") or ""),
            "os_note": ("OS 层由执行镜像 digest 覆盖；仅 pip freeze 不代表 OS 已冻结。"
                        if image_digest else "执行镜像未知；OS 层未冻结。"),
        },
        "data": {
            "refs": data_refs,
            "hashes": {url: str(data_hashes.get(url) or "") for url in data_refs},
        },
        "commands": {"env_setup": chain["env_setup"], "target": chain["target"]},
        "params": dict(exports.get("params") or {}),
        "seeds": dict(exports.get("seeds") or {}),
        "metric_policy": metric_policy,
        "history": {"attempt_count": len(attempts),
                    "excluded": dict(chain.get("excluded") or {}),
                    "curated": bool(chain.get("curated", False)),
                    "dropped": list(chain.get("dropped") or []),
                    "curated_note": str(chain.get("curated_note") or "")},
    }
    missing = completeness_missing(recipe, mode)
    recipe["completeness"] = "complete" if not missing else "incomplete"
    recipe["missing"] = missing
    recipe["recipe_hash"] = recipe_hash(recipe)
    recipe["recipe_id"] = recipe_id_for(recipe)
    return recipe


def completeness_missing(recipe: dict[str, Any], mode: str) -> list[str]:
    """缺项清单（未知字段显式标缺失；与判定解耦，可单测）。"""
    missing: list[str] = []
    repo = recipe.get("repo") or {}
    if not str(repo.get("revision") or ""):
        missing.append("repo_revision")
    commands = recipe.get("commands") or {}
    if not (commands.get("target") or []):
        missing.append("target_commands")
    image = recipe.get("image") or {}
    if not str(image.get("digest") or ""):
        missing.append("image_digest")
    patch = recipe.get("patch") or {}
    if not (patch.get("files") or []) and not str(patch.get("diff_text") or ""):
        missing.append("patch_or_files")
    if mode == "reproduce":
        data = recipe.get("data") or {}
        refs = list(data.get("refs") or [])
        hashes = dict(data.get("hashes") or {})
        if refs and any(not hashes.get(url) for url in refs):
            missing.append("data_hashes")
        if recipe.get("metric_policy") in (None, {}, {"basis": "not_evaluated"}):
            missing.append("metric_policy")
    return missing


def render_recipe_json(recipe: dict[str, Any]) -> str:
    """配方 JSON 文本（产物落盘用；content 内联文件默认剥离防膨胀）。

    大 content 内联只进 patch 产物（另件），本 JSON 保留引用＋hash。
    """
    slim = json.loads(json.dumps(recipe, ensure_ascii=False, default=str))
    for item in ((slim.get("patch") or {}).get("files") or []):
        if isinstance(item, dict) and item.get("via") == "content":
            item["content"] = None
            item["via"] = "reference"
    return json.dumps(slim, ensure_ascii=False, sort_keys=True, indent=2)
