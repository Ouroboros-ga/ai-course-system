"""F5 干净B：按冻结配方在全新沙箱中确定性恢复重放（不经 LLM）。

- 重放对象是冻结配方（FrozenRecipe）的最终方案：成功的环境安装＋成功的
  目标命令（去重保序）；诊断/失败安装/探测/文件工具不进 B 脚本。补丁文件
  按配方恢复（sha 复核），依赖按锁定安装，模型不参与，不发明、不修改。
- 沙箱是全新的（单次沙箱 id，与原 run 沙箱零复用；工作区从空开始），
  隔离语义沿控制服务（独立容器/网络/资源），继承原授权与资源/网络限制。
- 判定（规则 sr6-clean/3）：环境/目标分别比对；配方缺关键项即 incomplete
  （可下载，不判 passed）；A 未成功即 failed（同样失败不构成 passed）；
  B 未完成（超时/中断）如实抛错，不持久化 verdict，不伪装通过。
- verdict 持久化进 run 行（clean_status/clean_note/clean_checked_at＋
  规则版本），报告生成时自动带出。
- 补丁、配方先写产物后落行；B 沙箱执行完即 cancel 回收（best-effort）。
- 长重放走异步：入口只置 verifying 标记并调度后台任务即返；调用方轮询
  同一端点（幂等）或 run 详情拿结论。HTTP 断开不杀任务。
- 单 run 单验证者（进程内锁＋verifying 集合）；服务重启时 lifespan 把
  残留 verifying 复位为空（内存任务随进程消失，不伪装结论，可重试）。
- Ask/Auto 契约：重放会调用实验沙箱，与 Ask“不调用实验沙箱”互斥——
  入口强制 research_execution_mode=auto（未知 400，非 auto 403）。
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

from nexus.experiment_sandbox import HttpSandboxBackend as _HttpSandboxBackendBase

logger = logging.getLogger("nexus.experiment_clean")

CLEAN_SANDBOX_SUFFIX = "-clean1"
CLEANABLE_RUN_STATUSES = ("succeeded", "failed")
CLEAN_TERMINAL_STATUSES = ("passed", "failed", "incomplete")
CLEAN_PASS_STATUSES = CLEAN_TERMINAL_STATUSES
# 结论规则版本：判定口径变化时 bump，旧规则结论视为过期重验。
# v1（隐式 ""）：全部冻结步骤计数（含文件工具摘要，必 127 误杀）；
# v2（sr6-clean/2）：只比对 shell 步骤，文件工具摘要跳过留痕；
# v3（sr6-clean/3）：F5 冻结配方语义——B 只重放最终方案（成功环境安装＋
# 成功目标命令），补丁/依赖/数据按配方恢复；配方缺关键项即 incomplete；
# A 未成功即 failed（同样失败不构成 passed）；结论带 recipe hash。
CLEAN_RULE_VERSION = "sr6-clean/3"


class CleanError(Exception):
    """干净B域失败：携带机器可读 code（fail-closed 语义）。"""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


def clean_sandbox_id(run_id: str, nonce: str = "") -> str:
    """干净沙箱 id（默认 `{run}-clean1`，保持可读与可对账）。

    调度时传入 per-replay nonce → `{run}-clean-{nonce}`：控制面沙箱
    cancel 后即终态（后续 submit 409 RUN_TERMINAL），复用 id 会永久
    毒化该 run 的后续重验；每次调度全新 id，一次性，用后即回收。
    """
    base = (run_id or "").strip()
    if nonce and str(nonce).strip():
        suffix = f"-clean-{str(nonce).strip()[:8]}"
    else:
        suffix = CLEAN_SANDBOX_SUFFIX
    return f"{base[: 64 - len(suffix)]}{suffix}"


def replayable_steps(run: dict[str, Any]) -> list[dict[str, Any]]:
    """可重放步骤（与 T6 报告配方同源同过滤：非空＋排除路由探针）。"""
    attempts = list(run.get("attempts", []) or [])
    steps: list[dict[str, Any]] = []
    for attempt in attempts:
        command = str(attempt.get("actual_command") or "")
        if not command or command.startswith("ls /workspace"):
            continue
        steps.append({
            "attempt_no": attempt.get("attempt_no", 0),
            "command": command,
            "exit_code": attempt.get("exit_code"),
        })
    return steps


# 原生文件工具摘要（T5-1 file_tool_summary 形状）不是 shell 命令：
# write_file/read_file/edit_file/delete/glob 无 shell 同名物（执行必 127）；
# grep 摘要形如 "grep <单token>"（真 shell grep 必带 flag/路径/管道，
# 且裸 grep 会挂起等 stdin）。ls 摘要与 shell ls 同形同语义，保留重放。
# 判别只认"工具名＋单个裸 token"形状，真 shell 命令（含 flag/管道/引号）
# 不受影响。
_NON_SHELL_TOOL_RE = re.compile(
    r"^(write_file|read_file|edit_file|delete|glob|grep)\s+[^\s|&;]+\s*$")


def is_shell_replayable(command: str) -> bool:
    """该 attempt 命令是否为可重放的 shell 命令（纯函数，可单测）。"""
    text = (command or "").strip()
    if not text:
        return False
    return _NON_SHELL_TOOL_RE.match(text) is None


def skipped_file_tool_steps(run: dict[str, Any]) -> list[dict[str, Any]]:
    """文件工具摘要步骤（留痕用：如实列出，不计入 verdict）。"""
    return [s for s in replayable_steps(run)
            if not is_shell_replayable(s["command"])]


# 注：v2 引擎 replay_steps（逐条重演全部历史命令）已在 F5 被替代删除：
# B 只重放冻结配方的最终方案（见 restore_and_replay），不再重演失败尝试。


def _backend_for_clean(clean_id: str) -> Any:
    """由服务端配置构造干净沙箱绑定 Backend（与实验图同源配置）。

    op id 带 per-replay nonce 后缀（_ReplayBackend）：控制面"同 id
    不运行两次"，重试复用 id 会 409 误杀；nonce 保证每次重放 ids 唯一。
    """
    import uuid

    from nexus.config import get_settings
    from nexus.experiment_sandbox import ExperimentSandboxError

    settings = get_settings()
    base_url = (getattr(settings, "repro_control_url", "") or "").rstrip("/")
    token = getattr(settings, "repro_control_token", "") or ""
    if not base_url:
        raise ExperimentSandboxError(
            "SANDBOX_NOT_CONFIGURED",
            "执行控制服务未配置（NEXUS_REPRO_CONTROL_URL 为空）；干净验证未执行。",
        )
    return _ReplayBackend(run_id=clean_id, base_url=base_url, token=token,
                          _nonce=uuid.uuid4().hex[:8])


class _ReplayBackend(_HttpSandboxBackendBase):
    """重放专用 Backend：op id 追加 per-replay nonce（控制面去重要求）。

    基类在模块导入时解析（experiment_sandbox 只依赖 deepagents/httpx，
    无 nexus 包内循环）。
    """

    def __init__(self, *args: Any, _nonce: str = "", **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._replay_nonce = (_nonce or "").strip()[:16]

    def _new_operation_id(self) -> str:
        self._op_seq += 1
        suffix = f"-{self._replay_nonce}" if self._replay_nonce else ""
        return f"{self._run_id}-op-{self._op_seq:04d}{suffix}"


# F5：采集排除之外的候选上限（文件数/单文件沿 recipe 模块常量）。
_EXPORT_MAX_FILES = 50


async def collect_exports(*, backend: Any, run: dict[str, Any]) -> dict[str, Any]:
    """F5：从 A 容器采集冻结输入（best-effort：逐项失败即记缺失，不抛）。

    backend 为 None（容器已回收/测试）即全缺失返回。采集：git 变更清单＋
    diff、变更/新增文件内容（排除凭据缓存＋超限引用化）、pip freeze、
    conda 导出。返回 freeze_recipe 的 exports 形态。
    """
    from nexus import experiment_recipe as recipe_module

    empty: dict[str, Any] = {"diff_text": "", "files": [], "deleted": [],
                             "pip_freeze": "", "conda_export": "",
                             "data_hashes": {}, "seeds": {}, "params": {}}
    if backend is None:
        return empty
    try:
        status_resp = await backend.aexecute(
            "git -C /workspace status --porcelain=v1 -uall", timeout=60)
    except Exception:  # noqa: BLE001 - 非 git/不可达即全缺失
        return empty
    if status_resp.exit_code != 0:
        return empty
    modified: list[str] = []
    deleted: list[str] = []
    for line in (status_resp.output or "").splitlines():
        if len(line) < 4:
            continue
        code, path = line[:2], line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip().strip('"')
        path = path.strip().strip('"')
        if not path:
            continue
        full = path if path.startswith("/") else f"/workspace/{path}"
        if code.strip() == "D":
            deleted.append(full)
        elif code.strip() in ("M", "A", "??", "AM", "MM"):
            modified.append(full)
    exports: dict[str, Any] = {"diff_text": "", "files": [],
                               "deleted": deleted[:100], "pip_freeze": "",
                               "conda_export": "", "data_hashes": {},
                               "seeds": {}, "params": {}}
    try:
        diff_resp = await backend.aexecute(
            "git -C /workspace diff HEAD -- . | head -c 600000", timeout=120)
        if diff_resp.exit_code == 0:
            exports["diff_text"] = (diff_resp.output or "")[:(
                recipe_module.DIFF_MAX_BYTES)]
    except Exception:  # noqa: BLE001 - diff 失败不否决文件快照
        pass
    for path in modified[:_EXPORT_MAX_FILES]:
        if recipe_module.is_denied_path(path):
            continue
        try:
            got = await backend.adownload_files([path])
        except Exception:  # noqa: BLE001 - 单文件失败跳过
            continue
        if not got or getattr(got[0], "error", None):
            continue
        content = getattr(got[0], "content", None) or b""
        try:
            size = len(bytes(content))
        except Exception:  # noqa: BLE001
            continue
        item: dict[str, Any] = {"path": path, "size_bytes": size}
        import hashlib as _hashlib

        if size <= recipe_module.FILE_SNAPSHOT_MAX_BYTES:
            item["sha256"] = _hashlib.sha256(bytes(content)).hexdigest()
            try:
                item["content"] = bytes(content).decode("utf-8")
            except UnicodeDecodeError:
                import base64 as _base64

                item["content"] = _base64.b64encode(bytes(content)).decode("ascii")
                item["encoding"] = "base64"
        else:
            item["via"] = "reference"
            item["note"] = "超限未内联；凭引用＋大小复核，不重复拷贝。"
        exports["files"].append(item)
    try:
        freeze_resp = await backend.aexecute("pip freeze", timeout=180)
        if freeze_resp.exit_code == 0:
            exports["pip_freeze"] = (freeze_resp.output or "")[:65536]
    except Exception:  # noqa: BLE001
        pass
    try:
        conda_resp = await backend.aexecute(
            "conda env export --no-builds 2>/dev/null | head -c 65536", timeout=180)
        if conda_resp.exit_code == 0 and (conda_resp.output or "").strip():
            exports["conda_export"] = conda_resp.output or ""
    except Exception:  # noqa: BLE001 - 无 conda 即空，不否决
        pass
    return exports


async def ensure_frozen_recipe(
    *, run_id: str, user_id: str, scope: dict[str, Any],
    proposal: dict[str, Any] | None, backend: Any = None,
    curated: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """F5：冻结配方（幂等复用行引用；产物先落盘后落行）。

    - 行已有 recipe_hash → 复用（deduped，不重采不重写）；
    - 否则采集→冻结→写 recipe/patch 双产物→落行。产物任一失败即抛
      CleanError（RECIPE_ARTIFACT_WRITE_FAILED），行不落，不伪装。
    返回 {"recipe", "recipe_artifact_id", "patch_artifact_id", "deduped"}。
    """
    from nexus import artifact_client
    from nexus import experiment_recipe as recipe_module
    from nexus import experiment_runs as runs_module

    run = runs_module.get_run(run_id)
    if run is None:
        raise CleanError("RUN_NOT_FOUND", "运行不存在或已不可恢复")
    if str(run.get("recipe_hash") or "") and str(run.get("recipe_status") or ""):
        return {"recipe": None, "recipe_hash": str(run["recipe_hash"]),
                "recipe_status": str(run["recipe_status"]),
                "recipe_artifact_id": str(run.get("recipe_artifact_id") or ""),
                "patch_artifact_id": str(run.get("recipe_patch_id") or ""),
                "deduped": True}
    try:
        image = ""
        image_digest = ""
        if backend is not None:
            try:
                view = await backend.sandbox_status()
                image = str(view.get("image") or "")
                image_digest = str(view.get("image_digest") or "")
            except Exception:  # noqa: BLE001 - 镜像未知即记缺失
                pass
        exports = await collect_exports(backend=backend, run=run)
        recipe = recipe_module.freeze_recipe(
            run=run, scope=scope, proposal=proposal, exports=exports,
            image=image, image_digest=image_digest, curated=curated)
    except Exception as error:  # noqa: BLE001 - 冻结自身失败 fail-closed
        raise CleanError("RECIPE_FREEZE_FAILED",
                         f"配方冻结失败（{type(error).__name__}）。") from error
    title_base = f"冻结配方 · {run_id[:12]}"
    recipe_json = recipe_module.render_recipe_json(recipe)
    written = await artifact_client.write_artifact_via_backend(
        artifact_type="json", title=title_base, content=recipe_json,
        user_id=user_id, run_id=run_id)
    if written.get("status") != "success":
        raise CleanError(
            "RECIPE_ARTIFACT_WRITE_FAILED",
            f"配方产物写入失败（{written.get('code', '')}）：{written.get('detail', '')}"[:300])
    recipe_artifact = written["artifact"]
    patch_bundle = {"recipe_id": recipe["recipe_id"],
                    "recipe_hash": recipe["recipe_hash"],
                    "version": recipe.get("version", ""),
                    "mode": recipe.get("mode", ""),
                    "completeness": recipe.get("completeness", "incomplete"),
                    "missing": list(recipe.get("missing") or []),
                    "missing": list(recipe.get("missing") or []),
                    "repo": recipe.get("repo") or {},
                    "commands": recipe.get("commands") or {},
                    "image": recipe.get("image") or {},
                    "dependencies": recipe.get("dependencies") or {},
                    "data": recipe.get("data") or {},
                    "diff_text": (recipe.get("patch") or {}).get("diff_text", ""),
                    "files": (recipe.get("patch") or {}).get("files", []),
                    "deleted": (recipe.get("patch") or {}).get("deleted", [])}
    import json as _json

    patch_json = _json.dumps(patch_bundle, ensure_ascii=False, sort_keys=True)
    if len(patch_json.encode("utf-8")) > 512 * 1024:
        # 超限：剥离内联 content 重写（引用＋hash 保留，可下载配方但 B 受限）。
        slim_files = []
        for item in patch_bundle["files"]:
            slim = dict(item)
            slim.pop("content", None)
            slim["via"] = "reference"
            slim_files.append(slim)
        patch_bundle["files"] = slim_files
        patch_bundle["content_stripped"] = True
        patch_json = _json.dumps(patch_bundle, ensure_ascii=False, sort_keys=True)
    written_patch = await artifact_client.write_artifact_via_backend(
        artifact_type="json", title=f"{title_base}（补丁束）", content=patch_json,
        user_id=user_id, run_id=run_id)
    if written_patch.get("status") != "success":
        raise CleanError(
            "RECIPE_ARTIFACT_WRITE_FAILED",
            f"补丁产物写入失败（{written_patch.get('code', '')}）："
            f"{written_patch.get('detail', '')}"[:300])
    runs_module.set_recipe(run_id, recipe["recipe_hash"],
                           str(recipe.get("completeness") or "incomplete"),
                           str(recipe_artifact.get("artifact_id") or ""),
                           str(written_patch["artifact"].get("artifact_id") or ""))
    return {"recipe": recipe, "recipe_hash": recipe["recipe_hash"],
            "recipe_status": str(recipe.get("completeness") or "incomplete"),
            "recipe_artifact_id": str(recipe_artifact.get("artifact_id") or ""),
            "patch_artifact_id": str(written_patch["artifact"].get("artifact_id") or ""),
            "deduped": False}


async def run_clean_verification(
    *, run_id: str, user_id: str, backend: Any = None,
    step_timeout_s: int = 300,
) -> dict[str, Any]:
    """干净B编排（同步版，测试/脚本用；HTTP 入口请用 start_clean_verification）。

    语义与异步版一致，区别是当前协程内等到落盘。归属→终态→冻结提案→
    冻结配方→B 恢复重放→落盘→回收。
    """
    outcome = await _guarded_verify(
        run_id=run_id, user_id=user_id, backend=backend,
        step_timeout_s=step_timeout_s)
    if outcome.get("deduped"):
        return outcome
    return outcome


async def restore_and_replay(
    *, recipe: dict[str, Any], backend: Any, run_id: str = "",
    step_timeout_s: int = 300,
) -> dict[str, Any]:
    """F5：B 端确定性恢复＋重放（不经 LLM，不改方案）。

    1. 全新沙箱从空开始：clone 固定 revision（rev-parse 核对）；
    2. 应用补丁文件（upload＋sha 复核；引用化缺 content 即失败，
       不猜不编）；执行删除清单（精确路径）；
    3. 安装依赖（pip freeze 文本；conda 仅 best-effort 注记）；
    4. 按序执行最终 env_setup＋target 命令，逐条比对退出码。
    任何提交/传输失败即 CleanError（码随因走），未知≠通过。
    返回 {"matched_env", "total_env", "matched_target", "total_target",
            "results": [...], "env_results": [...]}。
    """
    from nexus.experiment_sandbox import ExperimentSandboxError

    repo = recipe.get("repo") or {}
    repo_url = str(repo.get("url") or "")
    revision = str(repo.get("revision") or "")
    if not repo_url or not revision:
        raise CleanError("RECIPE_RESTORE_FAILED", "配方缺仓库/修订，无法恢复。")
    import shlex as _shlex

    async def _run(command: str, timeout: int, label: str) -> Any:
        try:
            response = await backend.aexecute(command, timeout=timeout)
        except ExperimentSandboxError as error:
            raise CleanError("CLEAN_REPLAY_INTERRUPTED",
                             f"B {label}中断（{error.code}）：{error}") from error
        if response.exit_code is None:
            # 超时未出退出码：未知≠通过；沙箱单次使用，先回收再如实抛错。
            try:
                await backend.cancel()
            except Exception:  # noqa: BLE001 - 回收 best-effort
                pass
            raise CleanError("CLEAN_STEP_TIMEOUT",
                             f"B {label}超时未出退出码；未知≠通过，未持久化结论。")
        return response

    clone = await _run(
        f"git init -q /workspace && git -C /workspace remote add origin "
        f"{_shlex.quote(repo_url)} && git -C /workspace fetch --depth 1 origin "
        f"{_shlex.quote(revision)} && git -C /workspace checkout {_shlex.quote(revision)}",
        min(600, max(120, int(step_timeout_s or 300))), "克隆")
    if clone.exit_code != 0:
        raise CleanError("RECIPE_RESTORE_FAILED",
                         f"B 克隆固定修订失败（exit={clone.exit_code}）。")
    verify = await _run("git -C /workspace rev-parse HEAD", 60, "核对")
    actual = (verify.output or "").strip().splitlines()
    if verify.exit_code != 0 or not actual or actual[-1].strip() != revision:
        raise CleanError("RECIPE_RESTORE_FAILED", "B 修订核对不一致，拒绝继续。")
    patch = recipe.get("patch") or {}
    for item in patch.get("files") or []:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "")
        if not path:
            continue
        content = item.get("content")
        if content is None:
            raise CleanError(
                "RECIPE_RESTORE_FAILED",
                f"补丁文件无内容（{path}，引用化超限）；不猜不编，停止。")
        try:
            if str(item.get("encoding") or "") == "base64":
                import base64 as _base64

                raw = _base64.b64decode(content)
            else:
                raw = str(content).encode("utf-8")
        except Exception as error:  # noqa: BLE001 - 补丁解码失败即停
            raise CleanError("RECIPE_RESTORE_FAILED",
                             f"补丁解码失败（{path}）：{type(error).__name__}。") from error
        try:
            uploaded = await backend.aupload_files([(path, raw)])
        except Exception as error:  # noqa: BLE001
            raise CleanError("RECIPE_RESTORE_FAILED",
                             f"补丁上传失败（{path}）：{type(error).__name__}。") from error
        if uploaded and getattr(uploaded[0], "error", None):
            raise CleanError("RECIPE_RESTORE_FAILED",
                             f"补丁上传被拒（{path}）：{uploaded[0].error}")
        if str(item.get("sha256") or ""):
            check = await _run(
                f"sha256sum {_shlex.quote(path)}", 60, "复核")
            if str(item["sha256"]) not in (check.output or ""):
                raise CleanError("RECIPE_RESTORE_FAILED",
                                 f"补丁复核不一致（{path}），拒绝继续。")
    for path in patch.get("deleted") or []:
        path = str(path or "")
        if not path:
            continue
        removed = await _run(f"rm -f {_shlex.quote(path)}", 60, "删除")
        if removed.exit_code != 0:
            raise CleanError("RECIPE_RESTORE_FAILED",
                             f"删除清单执行失败（{path}）。")
    deps = recipe.get("dependencies") or {}
    if str(deps.get("pip_freeze") or "").strip():
        try:
            await backend.aupload_files(
                [("/tmp/frozen-requirements.txt",
                  str(deps["pip_freeze"]).encode("utf-8"))])
        except Exception as error:  # noqa: BLE001
            raise CleanError("RECIPE_RESTORE_FAILED",
                             f"依赖清单下发失败：{type(error).__name__}。") from error
        installed = await _run(
            "pip install -r /tmp/frozen-requirements.txt",
            min(900, max(300, int(step_timeout_s or 300))), "安装依赖")
        if installed.exit_code != 0:
            raise CleanError("CLEAN_ENV_MISMATCH",
                             "B 依赖安装失败（环境不可重复）；"
                             f"尾部：{(installed.output or '')[-500:]}")
    commands = recipe.get("commands") or {}
    outcome: dict[str, Any] = {"env_results": [], "results": [],
                               "matched_env": 0, "total_env": 0,
                               "matched_target": 0, "total_target": 0}
    for bucket, key_matched, key_total in (
            ("env_setup", "matched_env", "total_env"),
            ("target", "matched_target", "total_target")):
        for step in commands.get(bucket) or []:
            command = str((step or {}).get("command") or "")
            expected = (step or {}).get("exit_code")
            if not command:
                continue
            if expected is None:
                outcome["env_results" if bucket == "env_setup" else "results"].append({
                    "command": command[:500], "expected": None,
                    "observed": None, "match": False, "unknown": True})
                outcome[key_total] += 1
                continue
            response = await _run(
                command, max(60, int(step_timeout_s or 300)), f"重放#{step.get('attempt_no', '')}")
            observed = response.exit_code
            if observed is None:
                try:
                    await backend.cancel()
                except Exception:  # noqa: BLE001
                    pass
                raise CleanError(
                    "CLEAN_STEP_TIMEOUT",
                    f"B 步骤超时未出退出码（`{command[:80]}`）；未知≠通过。")
            match = int(observed) == int(expected)
            outcome["env_results" if bucket == "env_setup" else "results"].append({
                "command": command[:500], "expected": int(expected),
                "observed": int(observed), "match": match})
            outcome[key_total] += 1
            if match:
                outcome[key_matched] += 1
            logger.info("clean B %s exit expected=%s observed=%s match=%s",
                        bucket, expected, observed, match)
    return outcome


# 单 run 单验证者（进程内锁；verifying 集合做快速去重，见 start）。
_CLEAN_LOCKS: dict[str, asyncio.Lock] = {}
_CLEAN_LOCKS_GUARD = asyncio.Lock()
_VERIFYING: set[str] = set()


async def _lock_for(run_id: str) -> asyncio.Lock:
    async with _CLEAN_LOCKS_GUARD:
        lock = _CLEAN_LOCKS.get(run_id)
        if lock is None:
            lock = asyncio.Lock()
            _CLEAN_LOCKS[run_id] = lock
        return lock


async def start_clean_verification(
    *, run_id: str, user_id: str, step_timeout_s: int = 900,
) -> dict[str, Any]:
    """干净B入口（异步）：校验门→置 verifying→调度后台→即返。

    - 已有 passed/failed/incomplete 结论（现规则）直接返回（deduped）；
    - verifying 中重复触发返回 verifying（deduped，不重复调度）；
    - 新调度返回 verifying（deduped False）。调用方轮询同一端点或
      run 详情（console 快照带 clean_status）拿终态结论。
    后台完成落盘 passed/failed/incomplete；B 未完成（超时/中断/异常）
    复位为空（报告仍 not_run，可重试，不伪装结论）。
    """
    from nexus import experiment_runs as runs_module
    from nexus import proposals as proposals_module

    run = runs_module.get_run(run_id)
    if run is None:
        raise CleanError("RUN_NOT_FOUND", "运行不存在或已不可恢复")
    if (user_id or "") != run["owner"]:
        raise CleanError("RUN_FORBIDDEN", "无权操作他人的运行")
    if run["status"] not in CLEANABLE_RUN_STATUSES:
        if run["status"] == "cancelled":
            raise CleanError("RUN_CANCELLED", "运行已取消，无可结论的结果")
        raise CleanError(
            "RUN_NOT_FINISHED", f"运行尚未结束（现态 {run['status']}），不得做干净验证")
    proposal = proposals_module.get_proposal(run.get("proposal_id", ""))
    if proposal is None or proposal.get("kind") != "autonomous_experiment":
        raise CleanError("RUN_PROPOSAL_UNAVAILABLE", "绑定的自主提案不可读，无法验证")
    stored_verdict = str(run.get("clean_status") or "")
    if stored_verdict in CLEAN_PASS_STATUSES:
        if str(run.get("clean_rule") or "") == CLEAN_RULE_VERSION:
            return {
                "run_id": run_id,
                "clean_verification": stored_verdict,
                "clean_note": str(run.get("clean_note") or ""),
                "recipe_hash": str(run.get("recipe_hash") or ""),
                "deduped": True,
            }
        # 规则过期（口径变化）：视为未验证，重新验证覆盖。
    async with _CLEAN_LOCKS_GUARD:
        if run_id in _VERIFYING or str(
                (runs_module.get_run(run_id) or {}).get("clean_status") or "") == "verifying":
            return {"run_id": run_id, "clean_verification": "verifying",
                    "deduped": True}
        _VERIFYING.add(run_id)
    runs_module.set_clean_verdict(run_id, "verifying", "干净验证运行中（全新沙箱重放）。")

    async def _guarded() -> None:
        try:
            await _complete_clean_verification(
                run_id=run_id, user_id=user_id, step_timeout_s=step_timeout_s)
        except CleanError as error:
            logger.warning("clean verification failed for %s: %s: %s",
                           run_id, error.code, error)
            try:
                runs_module.set_clean_verdict(run_id, "", f"干净验证异常（{error.code}），可重试。")
            except Exception:  # noqa: BLE001 - 落盘失败只记日志
                logger.warning("clean reset persist failed for %s", run_id)
            finally:
                async with _CLEAN_LOCKS_GUARD:
                    _VERIFYING.discard(run_id)
        except Exception as error:  # noqa: BLE001 - 后台任务绝不裸抛
            logger.warning("clean verification failed for %s: %s",
                           run_id, type(error).__name__)
            try:
                runs_module.set_clean_verdict(run_id, "", f"干净验证异常（{type(error).__name__}），可重试。")
            except Exception:  # noqa: BLE001 - 落盘失败只记日志
                logger.warning("clean reset persist failed for %s", run_id)
            finally:
                async with _CLEAN_LOCKS_GUARD:
                    _VERIFYING.discard(run_id)

    try:
        asyncio.get_running_loop().create_task(_guarded())
    except RuntimeError as error:
        async with _CLEAN_LOCKS_GUARD:
            _VERIFYING.discard(run_id)
        runs_module.set_clean_verdict(run_id, "", "调度器无运行循环，可重试。")
        raise CleanError("CLEAN_SCHEDULER_UNAVAILABLE",
                         f"无运行循环可调度干净验证：{error}") from error
    return {"run_id": run_id, "clean_verification": "verifying",
            "deduped": False}


async def _complete_clean_verification(
    *, run_id: str, user_id: str, backend: Any = None,
    step_timeout_s: int = 900,
) -> dict[str, Any]:
    """后台完成：重放→落盘→日志产物→回收（锁内串行；失败复位为空，可重试）。"""
    from nexus import experiment_runs as runs_module

    lock = await _lock_for(run_id)
    async with lock:
        try:
            outcome = await _guarded_verify(
                run_id=run_id, user_id=user_id, backend=backend,
                step_timeout_s=step_timeout_s, _skip_verifying_check=True)
        finally:
            async with _CLEAN_LOCKS_GUARD:
                _VERIFYING.discard(run_id)
        # 验证日志产物（best-effort：verdict 已落盘，日志写失败不推翻结论）。
        try:
            from nexus import artifact_client

            run = runs_module.get_run(run_id) or {"run_id": run_id}
            log_md = render_clean_log_markdown(run, outcome)
            await artifact_client.write_artifact_via_backend(
                artifact_type="markdown",
                title=f"干净验证日志 · {run_id[:12]}",
                content=log_md, user_id=user_id, run_id=run_id)
        except Exception as error:  # noqa: BLE001
            logger.warning("clean log artifact write failed for %s: %s",
                           run_id, type(error).__name__)
        return outcome


async def _guarded_verify(
    *, run_id: str, user_id: str, backend: Any = None,
    step_timeout_s: int = 900, _skip_verifying_check: bool = False,
    clean_id: str = "",
) -> dict[str, Any]:
    """F5 干净B编排：归属→终态→冻结提案→预算→冻结配方→B 恢复重放→落盘→回收。

    - 只接受本人终态 succeeded/failed 的 run（running→RUN_NOT_FINISHED，
      cancelled→RUN_CANCELLED——取消无可结论的结果，不验证）；
    - 已有 passed/failed/incomplete 结论（现规则）直接返回（deduped；
      attempt 终态后不可变，结论天然稳定）；
    - 预算耗尽→ incomplete 落盘；配方 incomplete→ incomplete 落盘；
    - B 确定性重放最终方案（不经 LLM），环境/目标分别比对；
    - clean_id 为空且 backend 未注入时，按本次调度生成全新沙箱 id
      （单次使用；cancel/终态不影响后续重验）；
    - 新鲜沙箱执行完即 cancel 回收（best-effort，失败只记日志）。
    """
    from nexus import experiment_runs as runs_module
    from nexus import proposals as proposals_module
    from nexus.experiment_sandbox import ExperimentSandboxError

    run = runs_module.get_run(run_id)
    if run is None:
        raise CleanError("RUN_NOT_FOUND", "运行不存在或已不可恢复")
    if (user_id or "") != run["owner"]:
        raise CleanError("RUN_FORBIDDEN", "无权操作他人的运行")
    if run["status"] not in CLEANABLE_RUN_STATUSES:
        if run["status"] == "cancelled":
            raise CleanError("RUN_CANCELLED", "运行已取消，无可结论的结果")
        raise CleanError(
            "RUN_NOT_FINISHED", f"运行尚未结束（现态 {run['status']}），不得做干净验证")
    proposal = proposals_module.get_proposal(run.get("proposal_id", ""))
    if proposal is None or proposal.get("kind") != "autonomous_experiment":
        raise CleanError("RUN_PROPOSAL_UNAVAILABLE", "绑定的自主提案不可读，无法验证")
    stored_verdict = str(run.get("clean_status") or "")
    if stored_verdict in CLEAN_TERMINAL_STATUSES:
        if str(run.get("clean_rule") or "") == CLEAN_RULE_VERSION:
            return {
                "run_id": run_id,
                "clean_verification": stored_verdict,
                "clean_note": str(run.get("clean_note") or ""),
                "recipe_hash": str(run.get("recipe_hash") or ""),
                "deduped": True,
            }
        # 规则过期：继续向下重新验证覆盖（旧 passed 无新证明即 legacy）。
    if not _skip_verifying_check and stored_verdict == "verifying":
        return {"run_id": run_id, "clean_verification": "verifying",
                "deduped": True}
    scope = dict(proposal.get("scope") or {})
    if _wall_exhausted(run, scope):
        note = ("预算已耗尽（wall_time 到期），停止验证；"
                f"规则 {CLEAN_RULE_VERSION}。")
        runs_module.set_clean_verdict(run_id, "incomplete", note,
                                      rule=CLEAN_RULE_VERSION)
        return {"run_id": run_id, "clean_verification": "incomplete",
                "clean_note": note,
                "recipe_hash": str(run.get("recipe_hash") or ""),
                "deduped": False}
    try:
        frozen = await ensure_frozen_recipe(
            run_id=run_id, user_id=user_id, scope=scope, proposal=proposal,
            backend=None, curated=None)
    except CleanError:
        raise
    recipe = frozen.get("recipe")
    if recipe is None:
        row_status = str(run.get("recipe_status") or "")
        if row_status and row_status != "complete":
            # 报告期已判 incomplete：直接落 incomplete（读束取缺项，失败即通用注记）。
            missing: list[str] = []
            try:
                bundle = await _load_recipe_bundle(
                    run_id=run_id, user_id=user_id,
                    patch_artifact_id=str(run.get("recipe_patch_id") or ""),
                    expected_hash=str(run.get("recipe_hash") or ""),
                    require_complete=False)
                missing = list(bundle.get("missing") or [])
            except CleanError:
                missing = []
            note = (f"配方不完整（缺：{', '.join(missing) or '见配方产物'}），"
                    f"验证 incomplete；不判 passed（规则 {CLEAN_RULE_VERSION}）。")
            runs_module.set_clean_verdict(run_id, "incomplete", note,
                                          rule=CLEAN_RULE_VERSION)
            return {"run_id": run_id, "clean_verification": "incomplete",
                    "clean_note": note,
                    "recipe_hash": str(run.get("recipe_hash") or ""),
                    "deduped": False}
        # 行已有完整引用（报告期冻结）：读回补丁束产物供 B 消费。
        recipe = await _load_recipe_artifact(
            run_id=run_id, user_id=user_id,
            patch_artifact_id=str(run.get("recipe_patch_id") or ""),
            expected_hash=str(run.get("recipe_hash") or ""))
    if str((recipe or {}).get("completeness") or "incomplete") != "complete":
        missing = list((recipe or {}).get("missing") or [])
        note = (f"配方不完整（缺：{', '.join(missing) or '未知'}），"
                f"验证 incomplete；配方 {str((recipe or {}).get('recipe_id') or '未知')} 可下载，"
                f"不判 passed（规则 {CLEAN_RULE_VERSION}）。")
        runs_module.set_clean_verdict(run_id, "incomplete", note,
                                      rule=CLEAN_RULE_VERSION)
        return {"run_id": run_id, "clean_verification": "incomplete",
                "clean_note": note,
                "recipe_hash": str((recipe or {}).get("recipe_hash") or ""),
                "deduped": False}
    import uuid as _uuid

    if not (clean_id or "").strip():
        # 每次调度全新沙箱 id（单次使用）：cancel/终态不毒化后续重验。
        clean_id = clean_sandbox_id(run_id, _uuid.uuid4().hex[:6])
    active_backend = backend
    if active_backend is None:
        try:
            active_backend = _backend_for_clean(clean_id)
        except ExperimentSandboxError as error:
            raise CleanError("CLEAN_SANDBOX_UNAVAILABLE",
                             f"{getattr(error, 'code', type(error).__name__)}: {error}") from error
    try:
        outcome = await restore_and_replay(
            recipe=recipe, backend=active_backend, run_id=run_id,
            step_timeout_s=step_timeout_s)
    except CleanError as error:
        # B 未完成（超时/中断/恢复失败）：复位为空（报告仍 not_run，可重试），
        # 不伪装 passed/failed/incomplete。
        runs_module.set_clean_verdict(
            run_id, "", f"干净验证未完成（{error.code}），可重试。")
        raise
    verdict, note = _judge_restored(run=run, recipe=recipe, outcome=outcome,
                                    clean_id=clean_id)
    runs_module.set_clean_verdict(run_id, verdict, note,
                                  rule=CLEAN_RULE_VERSION)
    try:
        await active_backend.cancel()
    except Exception as error:  # noqa: BLE001 - 回收 best-effort
        logger.warning("clean sandbox recycle cancel failed for %s: %s",
                       clean_id, type(error).__name__)
    return {
        "run_id": run_id,
        "clean_verification": verdict,
        "clean_note": note,
        "recipe_hash": str(recipe.get("recipe_hash") or ""),
        "clean_sandbox_id": clean_id,
        "components": {"environment": {
            "matched": int(outcome.get("matched_env") or 0),
            "total": int(outcome.get("total_env") or 0)},
            "target": {
            "matched": int(outcome.get("matched_target") or 0),
            "total": int(outcome.get("total_target") or 0)}},
        "matched": int(outcome.get("matched_target") or 0),
        "total": int(outcome.get("total_target") or 0),
        "matched_env": int(outcome.get("matched_env") or 0),
        "total_env": int(outcome.get("total_env") or 0),
        "results": outcome.get("results") or [],
        "env_results": outcome.get("env_results") or [],
        "checked_at": time.time(),
        "deduped": False,
    }


def _wall_exhausted(run: dict[str, Any], scope: dict[str, Any]) -> bool:
    """F5：wall 预算是否耗尽（耗尽即停止，不偷偷增配）。"""
    try:
        wall = float((scope.get("resources") or {}).get("wall_time_s") or 0)
        if wall <= 0:
            return False
        created = float(run.get("created_at") or 0)
        if created <= 0:
            return False
        return time.time() - created >= wall
    except (TypeError, ValueError):
        return False


async def _load_recipe_bundle(
    *, run_id: str, user_id: str, patch_artifact_id: str, expected_hash: str,
    require_complete: bool = True,
) -> dict[str, Any]:
    """F5：读回行引用的补丁束产物（hash 对不上即拒绝，不猜）。

    require_complete=True（B 消费）：非 complete 即拒绝；False（缺项展示）：
    仅校验 hash 与形状。产物缺失/截断/错配一律 CleanError（RECIPE_UNAVAILABLE），
    复位可重试，不降级重冻（行引用即真相源，不静默改写）。
    """
    from nexus import artifact_client

    if not patch_artifact_id:
        raise CleanError("RECIPE_UNAVAILABLE", "行无补丁束产物引用，无法验证。")
    read = await artifact_client.read_artifact_via_backend(
        artifact_id=patch_artifact_id, user_id=user_id)
    if read.get("status") != "success":
        raise CleanError(
            "RECIPE_UNAVAILABLE",
            f"补丁束产物不可读（{read.get('code', '')}）：{read.get('detail', '')}"[:300])
    if read.get("truncated"):
        raise CleanError("RECIPE_UNAVAILABLE", "补丁束产物被截断，不得当完整配方。")
    import json as _json

    try:
        bundle = _json.loads(read.get("content") or "")
    except ValueError as error:
        raise CleanError("RECIPE_UNAVAILABLE", "补丁束产物非合法 JSON。") from error
    if not isinstance(bundle, dict) or (
            expected_hash and str(bundle.get("recipe_hash") or "") != expected_hash):
        raise CleanError("RECIPE_UNAVAILABLE", "补丁束产物与行引用不一致，拒绝使用。")
    if require_complete and str(bundle.get("completeness") or "") != "complete":
        raise CleanError("RECIPE_UNAVAILABLE",
                         "补丁束配方不完整（行引用与内容矛盾），拒绝使用。")
    return bundle


async def _load_recipe_artifact(
    *, run_id: str, user_id: str, patch_artifact_id: str, expected_hash: str,
) -> dict[str, Any]:
    """F5：读回行引用的补丁束并还原 B 所需配方子集（瘦身 recipe JSON 仅供人读，不进 B）。

    见 _load_recipe_bundle（require_complete=True）。
    """
    bundle = await _load_recipe_bundle(
        run_id=run_id, user_id=user_id, patch_artifact_id=patch_artifact_id,
        expected_hash=expected_hash, require_complete=True)
    return {
        "recipe_id": str(bundle.get("recipe_id") or ""),
        "recipe_hash": str(bundle.get("recipe_hash") or ""),
        "version": str(bundle.get("version") or ""),
        "mode": str(bundle.get("mode") or ""),
        "completeness": "complete",
        "missing": [],
        "repo": bundle.get("repo") or {},
        "commands": bundle.get("commands") or {},
        "image": bundle.get("image") or {},
        "dependencies": bundle.get("dependencies") or {},
        "data": bundle.get("data") or {},
        "patch": {"diff_text": str(bundle.get("diff_text") or ""),
                  "files": list(bundle.get("files") or []),
                  "deleted": list(bundle.get("deleted") or [])},
    }


def _judge_restored(*, run: dict[str, Any], recipe: dict[str, Any],
                    outcome: dict[str, Any], clean_id: str) -> tuple[str, str]:
    """F5：B 结论判定（环境/目标分别比对；同样失败不构成 passed）。

    - 任一 unknown（期望缺失）→ incomplete；
    - 环境或目标任一 mismatch → failed；
    - 全等 → passed。passed 隐含 A 目标成功（配方 target 非空且 exit 全 0，
      由 freeze 保证；空 target 的配方 incomplete，前置已拦）。
    """
    env_total = int(outcome.get("total_env") or 0)
    env_matched = int(outcome.get("matched_env") or 0)
    total = int(outcome.get("total_target") or 0)
    matched = int(outcome.get("matched_target") or 0)
    unknowns = sum(1 for item in (outcome.get("results") or [])
                   + (outcome.get("env_results") or [])
                   if item.get("unknown"))
    recipe_id = str(recipe.get("recipe_id") or "未知")
    base = (f"干净沙箱 {clean_id} 按冻结配方 {recipe_id} 重放："
            f"环境 {env_matched}/{env_total}，目标 {matched}/{total}；")
    rule_note = f"规则 {CLEAN_RULE_VERSION}，确定性重放，非 LLM 判定。"
    if unknowns:
        return ("incomplete",
                f"{base}有 {unknowns} 步无期望退出码，无法比对，验证 incomplete。" + rule_note)
    if env_matched != env_total or matched != total:
        return ("failed", f"{base}存在不一致，验证 failed。" + rule_note)
    return ("passed", f"{base}全等，验证 passed。" + rule_note)


def render_clean_log_markdown(run: dict[str, Any],
                              outcome: dict[str, Any]) -> str:
    """F5 干净验证日志 Markdown（产物留痕：配方、恢复了什么、对上没有）。"""
    components = outcome.get("components") or {}
    env = components.get("environment") or {}
    target = components.get("target") or {}
    lines = [
        f"# 干净验证日志 · {run.get('run_id', '')}",
        "",
        f"结论：**{outcome.get('clean_verification', '')}**"
        f"（环境 {env.get('matched', 0)}/{env.get('total', 0)}，"
        f"目标 {target.get('matched', 0)}/{target.get('total', 0)}）",
        f"冻结配方：`{outcome.get('recipe_hash', '')}`",
        f"干净沙箱：`{outcome.get('clean_sandbox_id', '')}`（一次性，重放后已回收）",
        "",
        "## 目标步骤比对",
        "",
    ]
    for item in outcome.get("results") or []:
        mark = "一致" if item.get("match") else (
            "未知（无期望）" if item.get("unknown") else "**不一致**")
        lines.append(
            f"- `{item.get('command', '')}`"
            f"：记录 exit={item.get('expected', '—')}，重放 exit={item.get('observed', '—')} → {mark}")
    env_results = outcome.get("env_results") or []
    if env_results:
        lines += ["", "## 环境步骤比对", ""]
        for item in env_results:
            mark = "一致" if item.get("match") else "**不一致**"
            lines.append(
                f"- `{item.get('command', '')}`"
                f"：记录 exit={item.get('expected', '—')}，重放 exit={item.get('observed', '—')} → {mark}")
    skipped = outcome.get("skipped") or []
    if skipped:
        lines += ["", "## 未重放（原生文件工具摘要，非 shell 命令）", ""]
        for item in skipped:
            lines.append(f"- #{item.get('attempt_no', '')} `{item.get('command', '')}`"
                         "（显示摘要，不可作 shell 执行，不计入结论）")
    lines += ["",
              "判定口径（规则 sr6-clean/3）：B 只重放最终方案；环境/目标分别比对；"
              "配方缺关键项即 incomplete；A 未成功即 failed（同样失败不构成 passed）；"
              "指标本身仍以报告为准，本日志只证明最终方案在干净环境可重复执行。",
              ""]
    return "\n".join(lines)
