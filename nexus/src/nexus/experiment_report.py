"""T6 交付环境配方与真实结果（接既有 Artifact）。

- 配方：固定 repo 修订＋实际执行命令序列＋环境（镜像 digest/网络/资源）＋
  数据声明＋日志引用；seed 未跟踪如实 null；同一 run 可重复生成同一配方。
- 判定四分量：environment_ready / execution_succeeded / metric_verdict /
  clean_verification。exit 0 ≠论文复现成功：无指标即 not_evaluated，
  B 未执行即 not_run，绝不合成 reproducible=true。
- 交付：Markdown 报告＋Markdown 配方，经既有 artifact_client 写入并关联
  run；两个产物都落盘成功后才回收可变工作区（控制 cancel，best-effort）。
- 冻结内容版本 content_version（供 NX-O1 复用；正式 Word/LaTeX 由 SR6 经
  Pandoc 等成熟转换器另行完成）。
- 不新建 Evidence/Claim 产品，不建第二套对象存储，不解析指标（指标提取
  是调用方的事；本模块只做确定性比较与诚实缺席）。
"""

from __future__ import annotations

import logging
from typing import Any

from nexus import artifact_client

logger = logging.getLogger("nexus.experiment_report")

REPORT_CONTENT_VERSION = "experiment-report/1"


class ReportError(Exception):
    """报告域失败：携带机器可读 code（fail-closed 语义）。"""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


def _is_sha(value: str) -> bool:
    cleaned = (value or "").strip()
    return len(cleaned) >= 7 and all(
        c in "0123456789abcdefABCDEF" for c in cleaned)


def build_experiment_report(
    *, run: dict[str, Any], scope: dict[str, Any],
    license_info: dict[str, Any] | None = None,
    image: str = "", image_digest: str = "",
    metrics: dict[str, Any] | None = None,
    clean: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """由 run 行＋scope 构建确定性报告（纯函数，可单测）。

    metrics：None → not_evaluated；{"observed", "expected"} → 确定性比较
    （容差只来自调用方给定的 expected，不编造）。
    clean：None → not_run；{"status": passed|failed, ...} → 原样透出。
    """
    from nexus import repro_report

    attempts = list(run.get("attempts", []) or [])
    failures = [
        {"attempt_no": a.get("attempt_no", 0),
         "command": str(a.get("actual_command") or "")[:200],
         "exit_code": a.get("exit_code"),
         "log_tail": str(a.get("log_ref") or "")[-1000:],
         "operation_id": str(a.get("operation_id") or "")}
        for a in attempts if (a.get("exit_code") not in (None, 0))
    ]
    last_exit: int | None = None
    for attempt in reversed(attempts):
        if attempt.get("exit_code") is not None:
            last_exit = int(attempt["exit_code"])
            break
    execution_succeeded = bool(attempts) and last_exit == 0
    environment_ready = bool(attempts) and any(
        str((a.get("config_changes") or {}).get("route") or "") in
        ("base_container", "repo2docker") for a in attempts)
    if metrics is None:
        metric_verdict: str = "not_evaluated"
        comparison: list[dict[str, Any]] = []
    else:
        observed = (metrics.get("observed") or {})
        expected = (metrics.get("expected") or {})
        comparison = repro_report.compare_metrics(observed, expected)
        metric_verdict = ("PASS" if comparison and all(c["pass"] for c in comparison)
                          else "FAIL") if comparison else "not_evaluated"
        if metric_verdict == "not_evaluated":
            comparison = []
    clean_verdict = str((clean or {}).get("status") or "not_run")
    if clean_verdict not in ("passed", "failed"):
        clean_verdict = "not_run"
    resources = scope.get("resources") or {}
    revision = str(scope.get("repo_revision") or "")
    recipe = {
        "kind": "autonomous_experiment",
        "repo_url": str(scope.get("repo_url") or ""),
        "repo_revision": revision,
        "revision_pinned": _is_sha(revision),
        "base_image": image or "",
        "image_digest": image_digest or "",
        "network_profile": str(scope.get("network_profile") or ""),
        "resources": dict(resources),
        "mode": str(scope.get("mode") or ""),
        "objective": str(scope.get("objective") or ""),
        "data_refs": list(scope.get("data_refs") or []),
        "source_refs": list(scope.get("source_refs") or []),
        "steps": [
            {"attempt_no": a.get("attempt_no", 0),
             "command": str(a.get("actual_command") or ""),
             "exit_code": a.get("exit_code")}
            for a in attempts
            if str(a.get("actual_command") or "")
            and not str(a.get("actual_command") or "").startswith("ls /workspace")
        ],
        "seed": None,
        "seed_note": "随机种子未跟踪；重跑结果可能因随机性漂移。",
        "log_refs": [str(a.get("operation_id") or "") for a in attempts
                     if a.get("operation_id")],
        "generated_from_run": run.get("run_id", ""),
    }
    created = float(run.get("created_at") or 0)
    updated = float(run.get("updated_at") or created)
    duration_s = max(0.0, updated - created) if created else None
    return {
        "content_version": REPORT_CONTENT_VERSION,
        "run_id": run.get("run_id", ""),
        "proposal_id": run.get("proposal_id", ""),
        "scope_hash": run.get("scope_hash", ""),
        "status": run.get("status", ""),
        "environment_ready": environment_ready,
        "execution_succeeded": execution_succeeded,
        "metric_verdict": metric_verdict,
        "comparison": comparison,
        "clean_verification": clean_verdict,
        "clean_note": str((clean or {}).get("note") or ""),
        "failures": failures,
        "attempt_no": run.get("attempt_no", 0),
        "duration_s": duration_s,
        "license": dict(license_info or {"spdx": "", "status": "unknown"}),
        "recipe": recipe,
    }


def render_recipe_markdown(report: dict[str, Any]) -> str:
    """配方 Markdown：可重复执行的最小指令集（人读＋可复制跑）。"""
    recipe = report.get("recipe") or {}
    resources = recipe.get("resources") or {}
    lines = [
        f"# 实验配方 · {recipe.get('repo_url', '')}",
        "",
        f"由运行 `{recipe.get('generated_from_run', '')}` 生成；"
        "按序执行以下命令即可重现本次环境操作。",
        "",
        "## 来源与环境",
        "",
        f"- 仓库：{recipe.get('repo_url', '')}",
        f"- 修订：{recipe.get('repo_revision', '')}"
        + ("（已固定 commit）" if recipe.get("revision_pinned")
           else "（未固定到 commit，重跑时以实际解析为准）"),
        f"- 基础镜像：{recipe.get('base_image', '')}"
        + (f"@{recipe.get('image_digest', '')}" if recipe.get("image_digest") else ""),
        f"- 网络策略：{recipe.get('network_profile', '')}",
        f"- 资源：cpu={resources.get('cpu', '—')} "
        f"mem={resources.get('memory_mb', '—')}MB "
        f"disk={resources.get('disk_mb', '—')}MB "
        f"限时={resources.get('wall_time_s', '—')}s",
        f"- 数据：{', '.join(recipe.get('data_refs') or []) or '（无声明）'}",
        f"- 种子：未跟踪（{recipe.get('seed_note', '')}）",
        "",
        "## 执行步骤（按实际执行顺序）",
        "",
        "```bash",
    ]
    steps = recipe.get("steps") or []
    if not steps:
        lines.append("# 本次运行没有记录到可重放的执行命令")
    for step in steps:
        lines.append(f"# #{step.get('attempt_no', '')} exit={step.get('exit_code')}")
        lines.append(step.get("command", ""))
    lines += [
        "```",
        "",
        "## 日志引用",
        "",
    ]
    log_refs = recipe.get("log_refs") or []
    if log_refs:
        lines.append("操作 id（凭此向执行器查询完整日志）：`" + "`, `".join(log_refs) + "`")
    else:
        lines.append("（无日志引用）")
    lines.append("")
    return "\n".join(lines)


def render_report_markdown(report: dict[str, Any]) -> str:
    """报告 Markdown：做了什么/修了什么/跑出什么/如何再跑。"""
    recipe = report.get("recipe") or {}
    verdict_line = (
        f"执行{'成功' if report.get('execution_succeeded') else '失败'} · "
        f"指标 {report.get('metric_verdict')} · 干净验证 {report.get('clean_verification')}"
    )
    license_info = report.get("license") or {}
    lines = [
        f"# 自主实验报告 · {report.get('run_id', '')}",
        "",
        f"**结论：{verdict_line}**（确定性拼装，非 LLM 判定；"
        "exit 0 只表示命令跑通，不等于论文复现成功）",
        "",
        f"- 目标：{recipe.get('objective', '')}",
        f"- 仓库：{recipe.get('repo_url', '')}@{recipe.get('repo_revision', '')}",
        f"- 镜像：{recipe.get('base_image', '')}"
        + (f"@{recipe.get('image_digest', '')}" if recipe.get("image_digest") else ""),
        f"- License：{license_info.get('spdx', '') or '未知'}"
        f"（{license_info.get('status', 'unknown')}）",
        f"- 尝试次数：{report.get('attempt_no', 0)}"
        + (f" · 耗时约 {report['duration_s']:.0f}s" if report.get("duration_s") else ""),
        "",
        "## 做了什么",
        "",
    ]
    steps = [
        f"{s.get('attempt_no', '')}. `{s.get('command', '')}`"
        f"（exit={s.get('exit_code', '—')}）"
        for s in (recipe.get("steps") or [])
    ]
    lines.extend(steps or ["（无已记录的执行命令）"])
    lines += ["", "## 修了什么", ""]
    failures = report.get("failures") or []
    if not failures:
        lines.append("本次运行没有记录到失败的尝试（一次通过或失败即停）。")
    else:
        for failure in failures:
            lines.append(
                f"- #{failure.get('attempt_no', '')} "
                f"`{failure.get('command', '')}` "
                f"exit={failure.get('exit_code', '—')}"
            )
            if failure.get("log_tail"):
                lines += ["  ```text", f"  {failure['log_tail'][:800]}", "  ```"]
        lines.append("")
        lines.append("以上失败发生后，执行器换了命令继续尝试（见上节顺序）；"
                     "最终是否跑通见下节结论，不把中间失败删掉，也不把成功归因于某一次修复。")
    lines += ["", "## 跑出什么", ""]
    if report.get("metric_verdict") == "not_evaluated":
        lines.append("指标：未评估（没有可比对的指标依据；运行成功只表示命令跑通）。")
    else:
        lines.append(f"指标判定：{report['metric_verdict']}")
        for item in report.get("comparison") or []:
            lines.append(
                f"- {item['metric']}：期望 {item['target']}±{item['tolerance']}，"
                f"实测 {item['observed']} → {'PASS' if item['pass'] else 'FAIL'}"
            )
    lines.append(f"干净验证（B）：{report['clean_verification']}"
                 + (f"（{report['clean_note']}）" if report.get("clean_note") else ""))
    lines += ["", "## 如何再跑", "",
              "完整可重复指令见配方产物（与本报告一同生成，同属本 run）；"
              "按配方顺序执行即可重现本次环境操作。",
              f"内容版本：{report.get('content_version', '')}（供多格式转换复用；"
              "正式 Word/LaTeX 由 SR6 经成熟转换器另行完成）。",
              ""]
    return "\n".join(lines)


async def build_stored_report(
    *, run_id: str, user_id: str,
) -> tuple[dict[str, Any], str, str]:
    """构建冻结报告结构＋双 Markdown（无副作用：不写产物、不回收）。

    - 只接受本人终态 succeeded/failed 的 run（与 generate 同门）；
    - License 取提案持久化结论；clean 取 run 持久化干净B结论
      （无→not_run；调用方显式 clean 覆盖见 build_experiment_report）。
    generate_run_report 与 formats 端点共用同一构建，保证三格式同源。
    """
    from nexus import experiment_runs as runs_module
    from nexus import proposals as proposals_module

    run = runs_module.get_run(run_id)
    if run is None:
        raise ReportError("RUN_NOT_FOUND", "运行不存在或已不可恢复")
    if (user_id or "") != run["owner"]:
        raise ReportError("RUN_FORBIDDEN", "无权操作他人的运行")
    if run["status"] not in ("succeeded", "failed"):
        if run["status"] == "cancelled":
            raise ReportError("RUN_CANCELLED", "运行已取消，无可结论的结果")
        raise ReportError(
            "RUN_NOT_FINISHED", f"运行尚未结束（现态 {run['status']}），不得生成报告")
    proposal = proposals_module.get_proposal(run.get("proposal_id", ""))
    if proposal is None or proposal.get("kind") != "autonomous_experiment":
        raise ReportError("RUN_PROPOSAL_UNAVAILABLE", "绑定的自主提案不可读，无法生成报告")
    scope = proposal.get("scope") or {}
    # T7：License 取提案持久化结论（intake 核验快照）；旧行缺失回退 unknown
    # ＋备注（不伪装 verified，执行前核验门已在执行侧拦过）。
    persisted_license = proposal.get("license")
    if not isinstance(persisted_license, dict) or not persisted_license:
        persisted_license = {"spdx": "", "status": "unknown",
                      "note": "提案未持久化 License 结论；复现引用前需核验允许复现用途"}
    # SR6：clean 取 run 持久化干净B结论（无→not_run）。
    persisted_clean: dict[str, Any] | None = None
    if str(run.get("clean_status") or "") in ("passed", "failed"):
        persisted_clean = {"status": str(run["clean_status"]),
                           "note": str(run.get("clean_note") or "")}
    report = build_experiment_report(
        run=run, scope=scope,
        license_info=persisted_license,
        image=str((scope.get("resources") or {}).get("image") or ""),
        image_digest=str(scope.get("image_digest") or ""),
        clean=persisted_clean)
    return report, render_report_markdown(report), render_recipe_markdown(report)


async def generate_run_report(
    *, run_id: str, user_id: str, backend: Any = None,
) -> dict[str, Any]:
    """生成 run 报告产物（报告＋配方）并关联本 run；成功后回收工作区。

    - 只接受终态 succeeded/failed 的 run（running→RUN_NOT_FINISHED，
      cancelled→RUN_CANCELLED；跨用户→RUN_FORBIDDEN）；
    - scope 取提案冻结值（提案不可读→RUN Proposal 缺失则拒绝，不编造）；
    - 两个产物都写入成功后才调控制 cancel 回收；写入失败抛
      REPORT_ARTIFACT_WRITE_FAILED 且不回收。
    """
    report, markdown, recipe_md = await build_stored_report(
        run_id=run_id, user_id=user_id)
    title_base = f"自主实验报告 · {run_id[:12]}"
    artifacts: list[dict[str, Any]] = []
    for artifact_type, title, content in (
        ("markdown", title_base, markdown),
        ("markdown", f"{title_base}（实验配方）", recipe_md),
    ):
        written = await artifact_client.write_artifact_via_backend(
            artifact_type=artifact_type, title=title, content=content,
            user_id=user_id, run_id=run_id)
        if written.get("status") != "success":
            raise ReportError(
                "REPORT_ARTIFACT_WRITE_FAILED",
                f"产物写入失败（{written.get('code', '')}）：{written.get('detail', '')}"[:300])
        artifacts.append(written["artifact"])
    # 保存后才回收：控制 cancel best-effort（失败只记日志，不推翻已落盘产物）。
    if backend is not None:
        try:
            await backend.cancel()
        except Exception as error:  # noqa: BLE001
            logger.warning("report recycle cancel failed for %s: %s",
                           run_id, type(error).__name__)
    return {
        "run_id": run_id,
        "content_version": REPORT_CONTENT_VERSION,
        "environment_ready": report["environment_ready"],
        "execution_succeeded": report["execution_succeeded"],
        "metric_verdict": report["metric_verdict"],
        "comparison": report["comparison"],
        "clean_verification": report["clean_verification"],
        "artifacts": artifacts,
    }


class FormatError(Exception):
    """正式格式域失败：携带机器可读 code（fail-closed 语义）。"""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


async def generate_run_formats(*, run_id: str, user_id: str) -> dict[str, Any]:
    """生成 run 正式格式产物（Word .docx＋LaTeX .tex）并关联本 run。

    - 同报告门：只接受本人终态 succeeded/failed 的 run（门码与报告一致，
      便于调用方统一处理）；
    - 内容与 T6 Markdown 同源（build_stored_report），derived_from 标记
      experiment-report/1；转换不改写事实；
    - 两个产物都写入成功才返回；任一失败抛 FORMAT_ARTIFACT_WRITE_FAILED。
      不触碰沙箱（纯渲染），Ask 下可用。
    """
    from nexus import document_output as formats_module

    try:
        report, markdown, recipe_md = await build_stored_report(
            run_id=run_id, user_id=user_id)
    except ReportError as error:
        raise FormatError(error.code, str(error)) from error
    title_base = f"自主实验报告 · {run_id[:12]}"
    try:
        built = formats_module.build_formats(markdown, recipe_md, title_base)
    except Exception as error:  # noqa: BLE001 - 转换异常 fail-closed
        raise FormatError("FORMAT_BUILD_FAILED",
                          f"格式构建失败（{type(error).__name__}）") from error
    artifacts: list[dict[str, Any]] = []
    written = await artifact_client.write_binary_artifact_via_backend(
        artifact_type="word", title=title_base, raw=built["docx_bytes"],
        user_id=user_id, run_id=run_id)
    if written.get("status") != "success":
        raise FormatError(
            "FORMAT_ARTIFACT_WRITE_FAILED",
            f"Word 产物写入失败（{written.get('code', '')}）：{written.get('detail', '')}"[:300])
    artifacts.append(written["artifact"])
    written_tex = await artifact_client.write_artifact_via_backend(
        artifact_type="latex", title=f"{title_base}（LaTeX）",
        content=built["tex"], user_id=user_id, run_id=run_id)
    if written_tex.get("status") != "success":
        raise FormatError(
            "FORMAT_ARTIFACT_WRITE_FAILED",
            f"LaTeX 产物写入失败（{written_tex.get('code', '')}）：{written_tex.get('detail', '')}"[:300])
    artifacts.append(written_tex["artifact"])
    checks = built["checks"]
    return {
        "run_id": run_id,
        "content_version": REPORT_CONTENT_VERSION,
        "derived_from": built["derived_from"],
        "clean_verification": report["clean_verification"],
        "artifacts": artifacts,
        "checks": {
            "docx": {"ok": bool(checks["docx"].get("ok")),
                     "detail": str(checks["docx"].get("detail") or ""),
                     "paragraphs": int(checks["docx"].get("checks", {}).get("paragraphs") or 0),
                     "tables": int(checks["docx"].get("checks", {}).get("tables") or 0)},
            "tex": {"ok": bool(checks["tex"].get("ok")),
                    "detail": str(checks["tex"].get("detail") or "")},
            "compile": {"compiled": bool(checks["compile"].get("compiled")),
                        "code": str(checks["compile"].get("code") or ""),
                        "detail": str(checks["compile"].get("detail") or "")},
        },
    }
