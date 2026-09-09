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


def _attempt_op_kind(attempt: dict[str, Any]) -> str:
    """attempt 操作类型：优先存盘值，旧行按命令启发式回填（纯函数）。"""
    from nexus import experiment_contracts as contracts_module

    stored = str((attempt.get("config_changes") or {}).get("op_kind") or "")
    if stored in ("probe", "environment", "diagnostic", "target",
                  "verification", "file_tool"):
        return stored
    if str((attempt.get("config_changes") or {}).get("kind") or "") == "file_tool":
        return "file_tool"
    return contracts_module.classify_operation(
        str(attempt.get("actual_command") or ""))


def _operation_summary(attempts: list[dict[str, Any]]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for attempt in attempts:
        kind = _attempt_op_kind(attempt)
        summary[kind] = summary.get(kind, 0) + 1
    return summary


def build_experiment_report(
    *, run: dict[str, Any], scope: dict[str, Any],
    license_info: dict[str, Any] | None = None,
    image: str = "", image_digest: str = "",
    metrics: dict[str, Any] | None = None,
    clean: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """由 run 行＋scope 构建确定性报告（纯函数，可单测）。

    F1 口径（计划 §6）：
    - 目标差异：setup 不要求指标/目标执行；smoke 要求目标程序跑通；
      reproduce 要求可比较指标政策（无政策/无实测即 not_evaluated）。
    - 环境就绪：来自声明依赖/导入/入口检查的成功（environment 类 attempt
      exit 0），不来自“选了基础镜像路线”；仅有探测（probe）不算就绪。
    - 目标完成：来自目标类（target）命令及要求产物；目标失败后 `pwd`
      等探测/诊断成功不能覆盖结论；无 target 记录即未完成。
    - 指标：只有受控采集与比较依据齐全才给 PASS/FAIL；setup 模式即使给了
      metrics 也不评估（目标本就不含指标）；冻结 metric_policy 存在时，
      调用方 expected 与政策不一致即 not_evaluated（禁改阈值凑 PASS）。
    - clean：None → not_run；{"status": passed|failed, ...} → 原样透出
      （调用方负责规则版本；持久化路径见 build_stored_report 的版本门）。
    metrics：None → not_evaluated；{"observed", "expected"} → 确定性比较
    （容差只来自调用方给定的 expected，不编造）。
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
    from nexus import experiment_contracts as contracts_module

    # F1：终态口径按操作类型判定。文件工具只作对账记录，不参与判定；
    # 目标失败后探测/诊断成功（如 pwd）不得覆盖结论。
    kinds = [_attempt_op_kind(a) for a in attempts]
    target_exits = [a.get("exit_code") for a, k in zip(attempts, kinds)
                    if k == "target" and a.get("exit_code") is not None]
    last_target_exit: int | None = (
        int(target_exits[-1]) if target_exits else None)
    # 旧行无 target 记录：如实判未完成（无目标证据），并标记 legacy_target
    # （历史口径曾按末次 execute 判定，此处不再沿用；调用方/UI 不得当作
    # 新规则目标证据）。
    legacy_target = not any(k == "target" for k in kinds)
    if last_target_exit is not None:
        execution_succeeded = last_target_exit == 0
    else:
        execution_succeeded = False
    # F1：环境就绪来自依赖/导入/入口检查成功，不来自镜像路线。
    # environment 类 exit 0 即就绪；仅 probe/diagnostic 不算就绪。
    env_success = any(
        k == "environment" and a.get("exit_code") == 0
        for a, k in zip(attempts, kinds))
    environment_ready = env_success
    goal = contracts_module.derive_goal(scope)
    operation_summary = _operation_summary(attempts)
    target_evidence = next(
        ({"attempt_no": a.get("attempt_no", 0),
          "command": str(a.get("actual_command") or "")[:200],
          "exit_code": a.get("exit_code")}
         for a, k in zip(reversed(attempts), reversed(kinds)) if k == "target"),
        None)
    # F1：指标门。setup 模式本就不含指标→强制 not_evaluated；
    # 冻结 metric_policy 存在且调用方 expected 与之不一致→拒绝评估
    # （禁改阈值凑 PASS）；无依据一律 not_evaluated。
    metric_note = ""
    metric_basis = "none"
    if goal.get("mode") == "setup":
        metric_verdict = "not_evaluated"
        comparison = []
        if metrics is not None:
            metric_note = "setup 模式不评估指标（已忽略调用方传入的 metrics）。"
            metric_basis = "setup_ignored"
    elif metrics is None:
        metric_verdict = "not_evaluated"
        comparison = []
    else:
        observed = (metrics.get("observed") or {})
        expected = (metrics.get("expected") or {})
        policy = goal.get("metric_policy")
        if isinstance(policy, dict) and policy:
            if dict(expected or {}) != dict(policy or {}):
                metric_verdict = "not_evaluated"
                comparison = []
                metric_note = ("指标期望与冻结政策不一致，已拒绝评估"
                               "（禁改阈值凑 PASS；以批准 scope 的 metric_policy 为准）。")
                metric_basis = "policy_mismatch"
            else:
                comparison = repro_report.compare_metrics(observed, expected)
                metric_verdict = ("PASS" if comparison and all(c["pass"] for c in comparison)
                                  else "FAIL") if comparison else "not_evaluated"
                if metric_verdict == "not_evaluated":
                    comparison = []
                metric_basis = "frozen_policy" if metric_verdict != "not_evaluated" else "none"
        else:
            comparison = repro_report.compare_metrics(observed, expected)
            metric_verdict = ("PASS" if comparison and all(c["pass"] for c in comparison)
                              else "FAIL") if comparison else "not_evaluated"
            if metric_verdict == "not_evaluated":
                comparison = []
            metric_basis = "ad-hoc" if metric_verdict != "not_evaluated" else "none"
    # clean：调用方显式传入原样透出（纯函数兼容旧单测）；规则版本门在
    # build_stored_report 的持久化路径执行（旧规则→历史记录，不算新通过）。
    clean_verdict = str((clean or {}).get("status") or "not_run")
    if clean_verdict not in ("passed", "failed"):
        clean_verdict = "not_run"
    clean_note = str((clean or {}).get("note") or "")
    clean_rule = str((clean or {}).get("rule") or "")
    resources = scope.get("resources") or {}
    revision = str(scope.get("repo_revision") or "")
    # F4：构建身份（repo2docker 成功 attempt 的双镜像记录；无则空）。
    build_image = ""
    exec_image = ""
    for attempt in attempts:
        changes = attempt.get("config_changes") or {}
        if str(changes.get("route") or "") == "repo2docker" \
                and attempt.get("exit_code") == 0:
            build_image = str(changes.get("build_image") or "") or build_image
            exec_image = str(changes.get("exec_image") or "") or exec_image
    recipe = {
        "kind": "autonomous_experiment",
        "repo_url": str(scope.get("repo_url") or ""),
        "repo_revision": revision,
        "revision_pinned": _is_sha(revision),
        "base_image": image or "",
        "image_digest": image_digest or "",
        "build_image": build_image,
        "exec_image": exec_image,
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
        "clean_note": clean_note,
        "clean_rule": clean_rule,
        "goal": goal,
        "operation_summary": operation_summary,
        "target_evidence": target_evidence,
        "legacy_target": legacy_target,
        "metric_note": metric_note,
        "metric_basis": metric_basis,
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
        *(([
            f"- 构建镜像：{recipe.get('build_image', '')}",
            f"- 执行镜像：{recipe.get('exec_image', '')}（含固定版本运行时）",
        ] if recipe.get("exec_image") else [])),
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
    """报告 Markdown：做了什么/修了什么/跑出什么/如何再跑。

    F1：四分量分别成立，不用一个绿色成功覆盖整个实验；缺什么明确写缺什么。
    """
    recipe = report.get("recipe") or {}
    run_status = str(report.get("status") or "")
    goal = report.get("goal") or {}
    mode = str(goal.get("mode") or recipe.get("mode") or "")
    op_summary = report.get("operation_summary") or {}
    summary_text = ("、".join(f"{k}×{v}" for k, v in sorted(op_summary.items()))
                    if op_summary else "无已分类操作")
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
        f"- 运行状态：{run_status or '未知'}"
        + ("（与下方“目标完成”口径不同：后者只看目标类命令退出码，"
           "前者含图/服务层失败）" if run_status == "failed"
           and report.get("execution_succeeded") else ""),
        "",
        f"- 目标：{recipe.get('objective', '')}"
        + (f"（模式 {mode}）" if mode else ""),
        f"- 操作分类：{summary_text}（分类本身不是完成证据）",
        f"- 环境就绪：{'是' if report.get('environment_ready') else '否'}"
        "（来自依赖/导入/入口检查成功，不来自镜像路线选择）",
        f"- 目标完成：{'是' if report.get('execution_succeeded') else '否'}"
        "（来自目标类命令退出码；目标失败后探测/诊断成功不覆盖）",
        *((["- 目标证据为历史兼容口径（旧行无操作分类回填），"
            "不得当作新规则目标证据。"] if report.get("legacy_target") else [])),
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
        if report.get("metric_note"):
            lines.append(str(report["metric_note"]))
    else:
        lines.append(f"指标判定：{report['metric_verdict']}"
                     + (f"（依据：{report['metric_basis']}）"
                        if report.get("metric_basis") else ""))
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
    *, run_id: str, user_id: str, backend: Any = None,
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
    # F1：旧规则结论仅作“历史命令一致性记录”，不得当作新规则干净通过。
    persisted_clean: dict[str, Any] | None = None
    if str(run.get("clean_status") or "") in ("passed", "failed"):
        from nexus import experiment_clean as clean_module

        current_rule = str(getattr(clean_module, "CLEAN_RULE_VERSION", ""))
        stored_rule = str(run.get("clean_rule") or "")
        if current_rule and stored_rule and stored_rule != current_rule:
            persisted_clean = {
                "status": "not_run",
                "note": (f"历史命令一致性记录（旧规则 {stored_rule}）："
                         f"{run.get('clean_status')}；"
                         f"非新规则 {current_rule} 下的干净复现成功，需重验。"),
                "rule": stored_rule,
            }
        else:
            persisted_clean = {"status": str(run["clean_status"]),
                               "note": str(run.get("clean_note") or ""),
                               "rule": stored_rule}
    # 镜像来源取自控制面 lifecycle（tag 可被重指，digest 才是真实身份）；
    # 控制面不可达/未配置时如实留空＋备注，绝不编造。
    image = ""
    image_digest = ""
    if backend is not None:
        try:
            view = await backend.sandbox_status()
            image = str(view.get("image") or "")
            image_digest = str(view.get("image_digest") or "")
        except Exception as error:  # noqa: BLE001
            logger.warning("report image digest unavailable for %s: %s",
                           run_id, type(error).__name__)
    report = build_experiment_report(
        run=run, scope=scope,
        license_info=persisted_license,
        image=image, image_digest=image_digest,
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
        run_id=run_id, user_id=user_id, backend=backend)
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
        "clean_note": report.get("clean_note", ""),
        "goal": report.get("goal", {}),
        "operation_summary": report.get("operation_summary", {}),
        "target_evidence": report.get("target_evidence"),
        "legacy_target": bool(report.get("legacy_target", False)),
        "metric_note": report.get("metric_note", ""),
        "metric_basis": report.get("metric_basis", "none"),
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

    # 只读 lifecycle 取镜像来源（不执行任何命令）；控制面不可达如实留空。
    backend: Any = None
    try:
        from nexus.experiment_agent import _backend_from_settings

        backend = _backend_from_settings(run_id)
    except Exception:  # noqa: BLE001
        backend = None
    try:
        report, markdown, recipe_md = await build_stored_report(
            run_id=run_id, user_id=user_id, backend=backend)
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
