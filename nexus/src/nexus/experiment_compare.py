"""F8 受控 A/B：同一实验问题下两个明确配置的对照比较。

定位（计划 §13）：A/B 只是关联两份冻结配置和结果，不引入 MLflow 或
通用实验追踪，不新建执行内核。

- 对照说明：共同数据/指标政策/预算 scope＋允许变化的参数，创建时一次
  声明；自动排错不能改变控制变量；
- 两组各引用冻结配方（recipe_hash），各在独立环境执行——执行走既有
  批准/run 通道，本模块不执行、不审批，只做关联与判定；
- 预算内按一次批准的对照 scope 执行：arm 运行沿用各自既有审批，超出
  原目标/资源范围的重跑不自动纳入，需新对照；
- 报告并列实际指标、运行条件、失败与缺失；永不自动声称显著提升
  （verdict 只有 descriptive_ready/incomplete＋固定免责声明）。

关键诚实门：
- 关联运行必须终态（succeeded/failed；失败也并列，不隐藏）；
- 运行必须自带冻结配方引用，且与 arm 声明的 recipe_hash 一致——排错
  改了方案会换 hash，旧 arm 拒绝关联（COMPARE_RECIPE_MISMATCH），
  要比就建新对照；
- 指标只取运行存储报告的实测值，取不到即 metrics_missing，不编造。
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

logger = logging.getLogger("nexus.experiment_compare")

COMPARE_VERSION = "compare-spec/1"
COMPARE_ID_PREFIX = "cmp-"
COMPARE_OPEN = "open"
COMPARE_RUNNING = "running"
COMPARE_CANCELLED = "cancelled"
COMPARE_TERMINAL = (COMPARE_CANCELLED,)
COMPARE_RUN_FINAL = ("succeeded", "failed")

SIGNIFICANCE_DISCLAIMER = (
    "本对照只做描述性并列；未设计统计检验、重复次数不足，"
    "不声称任何显著提升，结论以各组实测与缺失说明为准。"
)

_memory_compares: dict[str, dict[str, Any]] = {}


class CompareError(Exception):
    """对照领域错误（code 即线上 detail，便于端点直通）。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _now() -> float:
    return time.time()


def _pg_settings() -> tuple[str, str] | None:
    from nexus.experiment_runs import _pg_settings as runs_pg_settings

    try:
        return runs_pg_settings()
    except Exception:  # noqa: BLE001 - 配置不可读则读内存
        return None


def new_compare_id() -> str:
    return f"{COMPARE_ID_PREFIX}{uuid.uuid4().hex[:12]}"


def _decode_json(value: Any, default: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return default
    return value if value is not None else default


def _row_to_compare(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "compare_id": str(row.get("compare_id") or ""),
        "version": COMPARE_VERSION,
        "owner": str(row.get("owner") or ""),
        "session_id": str(row.get("session_id") or ""),
        "objective": str(row.get("objective") or ""),
        "common": _decode_json(row.get("common"), {}),
        "allowed_varied": _decode_json(row.get("allowed_varied"), []),
        "arms": _decode_json(row.get("arms"), []),
        "arm_results": _decode_json(row.get("arm_results"), {}),
        "approval_ref": str(row.get("approval_ref") or ""),
        "status": str(row.get("status") or COMPARE_OPEN),
        "detail": str(row.get("detail") or ""),
        "created_at": float(row.get("created_at") or 0),
        "updated_at": float(row.get("updated_at") or 0),
    }


def _row_from_pg(found: Any) -> dict[str, Any]:
    # 注意：调用方必须传原始行元组，禁止先 dict(zip(...)) 再传入
    # （F7 线上事故：对列名二次 zip 致列表恒空）。
    return _row_to_compare(dict(zip(_JOB_KEYS, found)))


_JOB_KEYS = (
    "compare_id", "owner", "session_id", "objective", "common",
    "allowed_varied", "arms", "arm_results", "approval_ref",
    "status", "detail", "created_at", "updated_at",
)
_JOB_SELECT = ", ".join(_JOB_KEYS)


def _insert_row(row: dict[str, Any]) -> None:
    pg = _pg_settings()
    if pg is not None:
        dsn, schema = pg
        try:
            import psycopg

            with psycopg.connect(dsn, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"INSERT INTO {schema}.nexus_compares "
                        f"({_JOB_SELECT}) "
                        f"VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                        f"ON CONFLICT (compare_id) DO NOTHING",
                        (
                            row["compare_id"], row.get("owner", ""),
                            row.get("session_id", ""), row.get("objective", ""),
                            json.dumps(row.get("common") or {}, ensure_ascii=False),
                            json.dumps(row.get("allowed_varied") or [], ensure_ascii=False),
                            json.dumps(row.get("arms") or [], ensure_ascii=False),
                            json.dumps(row.get("arm_results") or {}, ensure_ascii=False),
                            row.get("approval_ref", ""),
                            row.get("status", COMPARE_OPEN),
                            row.get("detail", ""),
                            row.get("created_at", 0), row.get("updated_at", 0),
                        ),
                    )
            return
        except Exception as error:  # noqa: BLE001
            logger.warning("compare pg insert failed, memory: %s", error)
    _memory_compares[row["compare_id"]] = dict(row)


def _update_row(row: dict[str, Any]) -> None:
    pg = _pg_settings()
    if pg is not None:
        dsn, schema = pg
        try:
            import psycopg

            with psycopg.connect(dsn, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"UPDATE {schema}.nexus_compares SET arms=%s, "
                        f"arm_results=%s, status=%s, detail=%s, updated_at=%s "
                        f"WHERE compare_id=%s",
                        (
                            json.dumps(row.get("arms") or [], ensure_ascii=False),
                            json.dumps(row.get("arm_results") or {}, ensure_ascii=False),
                            row.get("status", COMPARE_OPEN),
                            row.get("detail", ""),
                            row.get("updated_at", _now()),
                            row["compare_id"],
                        ),
                    )
            return
        except Exception as error:  # noqa: BLE001
            logger.warning("compare pg update failed: %s", error)
    _memory_compares[row["compare_id"]] = dict(row)


def get_compare(compare_id: str) -> dict[str, Any] | None:
    """读对照（归属由调用方校验；PG 优先，失败记日志后读内存）。"""
    compare_id = (compare_id or "").strip()[:64]
    if not compare_id:
        return None
    pg = _pg_settings()
    if pg is not None:
        dsn, schema = pg
        try:
            import psycopg

            with psycopg.connect(dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT {_JOB_SELECT} "
                        f"FROM {schema}.nexus_compares WHERE compare_id=%s",
                        (compare_id,),
                    )
                    found = cur.fetchone()
            if found is not None:
                return _row_from_pg(found)
        except Exception as error:  # noqa: BLE001
            logger.warning("compare pg read failed: %s", error)
    stored = _memory_compares.get(compare_id)
    return _row_to_compare(dict(stored)) if stored is not None else None


def list_compares(owner: str, session_id: str = "") -> list[dict[str, Any]]:
    """列某用户的对照（session 为空即不过滤；按更新倒序，≤50）。"""
    owner = (owner or "").strip()
    session_id = (session_id or "").strip()
    pg = _pg_settings()
    if pg is not None:
        dsn, schema = pg
        try:
            import psycopg

            with psycopg.connect(dsn) as conn:
                with conn.cursor() as cur:
                    if session_id:
                        cur.execute(
                            f"SELECT {_JOB_SELECT} "
                            f"FROM {schema}.nexus_compares "
                            f"WHERE owner=%s AND session_id=%s "
                            f"ORDER BY updated_at DESC LIMIT 50",
                            (owner, session_id),
                        )
                    else:
                        cur.execute(
                            f"SELECT {_JOB_SELECT} "
                            f"FROM {schema}.nexus_compares "
                            f"WHERE owner=%s ORDER BY updated_at DESC LIMIT 50",
                            (owner,),
                        )
                    # 原始行直传 _row_from_pg（禁止预先 dict(zip)）。
                    return [_row_from_pg(found) for found in cur.fetchall()]
        except Exception as error:  # noqa: BLE001
            logger.warning("compare pg list failed: %s", error)
    items = [dict(v) for v in _memory_compares.values()
             if str(v.get("owner") or "") == owner
             and (not session_id or str(v.get("session_id") or "") == session_id)]
    items.sort(key=lambda item: float(item.get("updated_at") or 0), reverse=True)
    return [_row_to_compare(item) for item in items[:50]]


def _save(compare: dict[str, Any]) -> dict[str, Any]:
    compare["updated_at"] = _now()
    _update_row(compare)
    stored = get_compare(compare["compare_id"])
    return dict(stored) if stored is not None else _row_to_compare(compare)


def _require_owned(compare_id: str, owner: str) -> dict[str, Any]:
    compare = get_compare(compare_id)
    if compare is None:
        raise CompareError("COMPARE_NOT_FOUND", "对照不存在或已不可恢复。")
    if (owner or "") != compare["owner"]:
        raise CompareError("COMPARE_FORBIDDEN", "无权操作他人的对照。")
    return compare


def _check_recipe_hash(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) < 7:
        raise CompareError(
            "COMPARE_RECIPE_UNPINNED",
            "arm 必须引用已冻结配方的 hash（≥7 位），未冻结的方案不能进对照。")
    return text[:128]


def create_compare(
    *, owner: str, session_id: str = "", objective: str = "",
    common: dict[str, Any] | None = None,
    allowed_varied: list[str] | None = None,
    arms: list[dict[str, Any]] | None = None,
    approval_ref: str = "",
) -> dict[str, Any]:
    """创建受控对照（只建对照、不执行；执行走既有批准/run 通道）。

    common：{data_ref, data_hash, metric_policy, budget}——对照说明，
    缺数据/指标政策即拒绝；
    allowed_varied：允许变化的参数名白名单；
    arms：每组 {name, recipe_hash, recipe_artifact_id, varied_params}。
    """
    owner = (owner or "").strip()
    if not owner:
        raise CompareError("COMPARE_OWNER_EMPTY", "owner 不能为空。")
    objective = (objective or "").strip()[:500]
    if not objective:
        raise CompareError("COMPARE_OBJECTIVE_EMPTY", "对照目标不能为空。")
    common = dict(common or {})
    data_ref = str(common.get("data_ref") or "").strip()
    data_hash = str(common.get("data_hash") or "").strip()
    metric_policy = common.get("metric_policy")
    if not data_ref or not data_hash or not isinstance(metric_policy, dict) \
            or not metric_policy:
        raise CompareError(
            "COMPARE_COMMON_INCOMPLETE",
            "对照说明不完整：共同数据引用＋hash＋指标政策缺一不可，"
            "否则两组结果不可比。")
    allowed = [str(item).strip()[:64] for item in (allowed_varied or [])
               if str(item or "").strip()][:16]
    raw_arms = [item for item in (arms or []) if isinstance(item, dict)]
    if len(raw_arms) < 2:
        raise CompareError("COMPARE_ARMS_TOO_FEW", "对照至少需要两组（arm）。")
    if len(raw_arms) > 8:
        raise CompareError("COMPARE_ARMS_TOO_MANY", "单次对照至多 8 组。")
    seen_names: set[str] = set()
    normalized_arms: list[dict[str, Any]] = []
    for index, item in enumerate(raw_arms):
        name = str(item.get("name") or "").strip()[:64] or f"arm-{index + 1}"
        if name in seen_names:
            raise CompareError("COMPARE_ARM_NAME_DUP", f"组名重复：{name}")
        seen_names.add(name)
        recipe_hash = _check_recipe_hash(item.get("recipe_hash"))
        varied = item.get("varied_params") or {}
        if not isinstance(varied, dict):
            raise CompareError("COMPARE_PARAM_VALUE", f"{name} 的 varied_params 须为对象。")
        clean_varied: dict[str, Any] = {}
        for key, value in varied.items():
            key_text = str(key or "").strip()[:64]
            if not key_text:
                continue
            if key_text not in allowed:
                raise CompareError(
                    "COMPARE_PARAM_UNDECLARED",
                    f"{name} 变化了未声明的参数 {key_text}；允许变化的只有 "
                    f"{'、'.join(allowed) if allowed else '（无）'}。")
            if not isinstance(value, (str, int, float, bool)) and value is not None:
                raise CompareError(
                    "COMPARE_PARAM_VALUE",
                    f"{name}.{key_text} 须为标量（str/int/float/bool），"
                    "复杂结构请先冻结成配方。")
            clean_varied[key_text] = value
        normalized_arms.append({
            "name": name,
            "recipe_hash": recipe_hash,
            "recipe_artifact_id": str(item.get("recipe_artifact_id") or "")[:64],
            "varied_params": clean_varied,
        })
    signatures = [json.dumps(arm["varied_params"], ensure_ascii=False, sort_keys=True)
                  for arm in normalized_arms]
    if len(set(signatures)) < len(signatures):
        raise CompareError(
            "COMPARE_ARMS_INDISTINGUISHABLE",
            "存在变化参数完全相同的两组，对照无法区分，请检查控制变量。")
    now = _now()
    row = {
        "compare_id": new_compare_id(),
        "owner": owner, "session_id": (session_id or "").strip()[:128],
        "objective": objective,
        "common": {"data_ref": data_ref, "data_hash": data_hash,
                   "metric_policy": metric_policy,
                   "budget": common.get("budget") or {}},
        "allowed_varied": allowed,
        "arms": normalized_arms,
        "arm_results": {},
        "approval_ref": (approval_ref or "").strip()[:64],
        "status": COMPARE_OPEN,
        "detail": "",
        "created_at": now, "updated_at": now,
    }
    _insert_row(row)
    stored = get_compare(row["compare_id"])
    return dict(stored) if stored is not None else _row_to_compare(row)


async def link_arm_run(
    *, compare_id: str, owner: str, arm_name: str, run_id: str,
) -> dict[str, Any]:
    """关联 arm 的执行运行（只关联终态运行；排错改了方案即拒绝）。

    - 运行须终态（succeeded/failed；失败也并列，不隐藏）；
    - 运行须自带冻结配方引用，且与 arm 声明一致；
    - 指标只取运行存储报告的实测值，取不到即 metrics_missing。
    """
    from nexus import experiment_runs as runs_module

    compare = _require_owned(compare_id, owner)
    if compare["status"] in COMPARE_TERMINAL:
        raise CompareError("COMPARE_TERMINAL", "对照已取消，不再接受关联。")
    arm = next((item for item in compare.get("arms") or []
                if str(item.get("name") or "") == (arm_name or "").strip()), None)
    if arm is None:
        raise CompareError("COMPARE_ARM_UNKNOWN", f"未知对照组：{arm_name}")
    run = runs_module.get_run((run_id or "").strip()[:64])
    if run is None or (owner or "") != run.get("owner", ""):
        raise CompareError("COMPARE_RUN_NOT_FOUND", "运行不存在或无权关联。")
    if str(run.get("status") or "") not in COMPARE_RUN_FINAL:
        raise CompareError(
            "COMPARE_RUN_NOT_TERMINAL",
            f"运行未终态（{run.get('status')}），终态后才能进入对照。")
    run_recipe = str(run.get("recipe_hash") or "")
    if not run_recipe:
        raise CompareError(
            "COMPARE_RUN_UNFROZEN",
            "该运行没有冻结配方引用（历史未验证），不能进入对照。")
    if run_recipe != arm.get("recipe_hash"):
        raise CompareError(
            "COMPARE_RECIPE_MISMATCH",
            "运行实际配方与本组声明不一致（排错可能改变了控制变量）；"
            "要比就用声明配方重跑，或建新对照。")
    attempts = run.get("attempts") or []
    exit_code: Any = None
    if isinstance(attempts, list) and attempts:
        last = attempts[-1] if isinstance(attempts[-1], dict) else {}
        exit_code = last.get("exit_code")
    metrics: dict[str, Any] | None = None
    metric_verdict = ""
    metric_comparison: list[Any] = []
    metrics_missing = ""
    try:
        from nexus import experiment_report as report_module

        report, _markdown, _recipe_md = await report_module.build_stored_report(
            run_id=str(run.get("run_id") or ""), user_id=owner)
        metrics = report.get("metrics_observed")
        if not isinstance(metrics, dict):
            metrics = None
            metrics_missing = "存储报告无实测指标"
        metric_verdict = str(report.get("metric_verdict") or "")
        raw_comparison = report.get("comparison") or []
        metric_comparison = list(raw_comparison) if isinstance(raw_comparison, list) else []
        if metrics is None and not metrics_missing:
            metrics_missing = "存储报告无实测指标"
    except Exception as error:  # noqa: BLE001 - 报告不可用即标缺失，不阻断关联
        metrics_missing = f"运行报告不可用（{type(error).__name__}），指标缺失"
    results = dict(compare.get("arm_results") or {})
    results[str(arm.get("name") or "")] = {
        "run_id": str(run.get("run_id") or ""),
        "run_status": str(run.get("status") or ""),
        "recipe_hash": run_recipe,
        "scope_hash": str(run.get("scope_hash") or ""),
        "proposal_version": int(run.get("proposal_version") or 0),
        "clean_status": str(run.get("clean_status") or ""),
        "exit_code": exit_code,
        "metrics": metrics,
        "metric_verdict": metric_verdict,
        "metric_comparison": metric_comparison,
        "metrics_missing": metrics_missing,
        "linked_at": _now(),
    }
    compare["arm_results"] = results
    if compare["status"] == COMPARE_OPEN:
        compare["status"] = COMPARE_RUNNING
    return _save(compare)


def request_cancel(compare_id: str, owner: str) -> dict[str, Any]:
    """取消对照（置终态；已关联结果保留，不删除）。"""
    compare = _require_owned(compare_id, owner)
    if compare["status"] in COMPARE_TERMINAL:
        return compare
    compare["status"] = COMPARE_CANCELLED
    compare["detail"] = "用户已取消对照；已关联结果保留。"
    return _save(compare)


def compare_report(compare: dict[str, Any]) -> dict[str, Any]:
    """对照报告（描述性并列；永不做显著性判定）。

    - 每组：配方、运行、条件、实测指标或缺失原因；
    - 可比性存疑（scope 不一致/指标口径不一致）如实注记，不隐藏；
    - verdict 只有 descriptive_ready/incomplete。
    """
    arms = compare.get("arms") or []
    results = compare.get("arm_results") or {}
    rows = []
    for arm in arms:
        name = str(arm.get("name") or "")
        result = results.get(name) or {}
        rows.append({
            "arm": name,
            "recipe_hash": str(arm.get("recipe_hash") or ""),
            "varied_params": arm.get("varied_params") or {},
            "run_id": str(result.get("run_id") or ""),
            "run_status": str(result.get("run_status") or ""),
            "exit_code": result.get("exit_code"),
            "scope_hash": str(result.get("scope_hash") or ""),
            "proposal_version": int(result.get("proposal_version") or 0),
            "clean_status": str(result.get("clean_status") or ""),
            "metrics": result.get("metrics"),
            "metric_verdict": str(result.get("metric_verdict") or ""),
            "metrics_missing": str(result.get("metrics_missing") or ""),
        })
    linked = [row for row in rows if row["run_id"]]
    notes: list[str] = []
    scope_hashes = {row["scope_hash"] for row in linked if row["scope_hash"]}
    if len(scope_hashes) > 1:
        notes.append("各组运行 scope 不一致，对照可比性存疑，请检查执行条件。")
    verdicts = {row["metric_verdict"] for row in linked
                if row["metrics"] is not None and row["metric_verdict"]}
    if len(verdicts) > 1:
        notes.append("各组指标判定口径不一致，仅并列实测值，不做横向结论。")
    missing_arms = [row["arm"] for row in rows if not row["run_id"]]
    if missing_arms:
        notes.append(f"以下组尚未关联终态运行，结果缺失：{'、'.join(missing_arms)}。")
    failed_arms = [row["arm"] for row in linked if row["run_status"] == "failed"]
    if failed_arms:
        notes.append(f"以下组运行失败，失败如实并列：{'、'.join(failed_arms)}。")
    ready = len(linked) >= 2 and len(linked) == len(rows)
    verdict = "descriptive_ready" if ready else "incomplete"
    reasons = []
    if len(linked) < 2:
        reasons.append("关联终态运行不足两组，无法对照。")
    if missing_arms:
        reasons.append("部分组结果缺失。")
    return {
        "rows": rows,
        "common": compare.get("common") or {},
        "allowed_varied": compare.get("allowed_varied") or [],
        "verdict": verdict,
        "verdict_reasons": reasons,
        "comparability_notes": notes,
        "significance": SIGNIFICANCE_DISCLAIMER,
    }


def public_compare_view(compare: dict[str, Any]) -> dict[str, Any]:
    """对照对外视图（完整规格＋并列报告；无密钥类字段）。"""
    return {
        "compare_id": compare.get("compare_id", ""),
        "version": COMPARE_VERSION,
        "owner": compare.get("owner", ""),
        "session_id": compare.get("session_id", ""),
        "objective": compare.get("objective", ""),
        "common": compare.get("common", {}),
        "allowed_varied": compare.get("allowed_varied", []),
        "arms": compare.get("arms", []),
        "arm_results": compare.get("arm_results", {}),
        "approval_ref": compare.get("approval_ref", ""),
        "status": compare.get("status", ""),
        "detail": compare.get("detail", ""),
        "report": compare_report(compare),
        "created_at": compare.get("created_at", 0),
        "updated_at": compare.get("updated_at", 0),
    }


def clear_memory_store() -> None:
    _memory_compares.clear()
