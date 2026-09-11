"""F7 研究任务域（ResearchTask/Brief）：持续研究的持久状态机。

- Brief 保留用户要求的分析维度、数据/时间范围与交付格式；解析（parsed）、
  读过（read）、理解（understood）分别表达，不把上传完成等同已读懂全文。
- 任务状态：open → running → waiting（等子任务/补读）→ succeeded /
  partial / failed / cancelled；取消随时可达，取消后不再推进。
- 预算（父任务分配，服务端强制）：max_rounds / max_subtasks /
  max_evidence_calls；用尽即停，不无限循环。
- 子任务恢复用明确 namespace（`rstask-{task_id}`），不只靠内存列表。
- 实验是研究分支：experiment_run_ids 只做引用关联，不复用实验 operation
  表做研究状态机；preset Worker 恢复走其真实 job 标识，不在本域冒充。
- 存储：PG ``nexus_checkpoints.nexus_research_tasks``＋内存降级（与
  experiment_runs 同失败语义）。
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

logger = logging.getLogger("nexus.research_state")

TASK_OPEN = "open"
TASK_RUNNING = "running"
TASK_WAITING = "waiting"
TASK_SUCCEEDED = "succeeded"
TASK_PARTIAL = "partial"
TASK_FAILED = "failed"
TASK_CANCELLED = "cancelled"

TASK_TERMINAL = (TASK_SUCCEEDED, TASK_PARTIAL, TASK_FAILED, TASK_CANCELLED)

DEFAULT_BUDGET = {"max_rounds": 8, "max_subtasks": 8, "max_evidence_calls": 24}

_memory_tasks: dict[str, dict[str, Any]] = {}


class ResearchError(Exception):
    """研究任务域失败：携带机器可读 code（fail-closed 语义）。"""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


def _now() -> float:
    return time.time()


def _pg_settings() -> tuple[str, str] | None:
    from nexus.experiment_runs import _pg_settings as runs_pg_settings

    try:
        return runs_pg_settings()
    except Exception:  # noqa: BLE001 - 配置不可读即内存降级
        return None


def parse_dimensions(raw: str) -> list[str]:
    """分析维度解析（逗号/顿号/分号/换行切分，去重保序，≤8；纯函数）。"""
    import re as _re

    parts = [part.strip()[:60] for part in _re.split(r"[,，;；、\n]+", raw or "")
             if part.strip()]
    seen: list[str] = []
    for part in parts:
        if part not in seen:
            seen.append(part)
        if len(seen) >= 8:
            break
    return seen


def task_namespace(task_id: str) -> str:
    """子任务恢复命名空间（稳定派生，不依赖内存列表）。"""
    return f"rstask-{(task_id or '').strip()[:48]}"


_JOB_KEYS = (
    "task_id", "parent_task_id", "owner", "session_id", "brief",
    "questions", "budget", "used", "status", "findings", "evidence_ids",
    "gaps", "conflicts", "experiment_run_ids", "report_artifact_id",
    "cancel_requested", "detail", "created_at", "updated_at",
)
_JOB_SELECT = ", ".join(_JOB_KEYS)


def _decode_json(value: Any, default: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return default
    return value if value is not None else default


def _row_to_task(row: dict[str, Any]) -> dict[str, Any]:
    questions = _decode_json(row.get("questions"), [])
    budget = _decode_json(row.get("budget"), {})
    used = _decode_json(row.get("used"), {})
    merged_budget = dict(DEFAULT_BUDGET)
    if isinstance(budget, dict):
        for key in DEFAULT_BUDGET:
            try:
                merged_budget[key] = max(1, int(budget.get(key, DEFAULT_BUDGET[key])))
            except (TypeError, ValueError):
                pass
    merged_used = {"rounds": 0, "subtasks": 0, "evidence_calls": 0}
    if isinstance(used, dict):
        for key in merged_used:
            try:
                merged_used[key] = max(0, int(used.get(key, 0)))
            except (TypeError, ValueError):
                pass
    return {
        "task_id": str(row.get("task_id") or ""),
        "parent_task_id": str(row.get("parent_task_id") or ""),
        "owner": str(row.get("owner") or ""),
        "session_id": str(row.get("session_id") or ""),
        "brief": _decode_json(row.get("brief"), {}),
        "questions": questions if isinstance(questions, list) else [],
        "budget": merged_budget,
        "used": merged_used,
        "status": str(row.get("status") or TASK_OPEN),
        "findings": _decode_json(row.get("findings"), []),
        "evidence_ids": _decode_json(row.get("evidence_ids"), []),
        "gaps": _decode_json(row.get("gaps"), []),
        "conflicts": _decode_json(row.get("conflicts"), []),
        "experiment_run_ids": _decode_json(row.get("experiment_run_ids"), []),
        "report_artifact_id": str(row.get("report_artifact_id") or ""),
        "cancel_requested": bool(row.get("cancel_requested", False)),
        "detail": str(row.get("detail") or ""),
        "namespace": task_namespace(str(row.get("task_id") or "")),
        "created_at": float(row.get("created_at") or 0),
        "updated_at": float(row.get("updated_at") or 0),
    }


def _row_from_pg(found: Any) -> dict[str, Any]:
    return _row_to_task(dict(zip(_JOB_KEYS, found)))


def _insert_row(row: dict[str, Any]) -> None:
    pg = _pg_settings()
    if pg is not None:
        dsn, schema = pg
        try:
            import psycopg

            with psycopg.connect(dsn, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"INSERT INTO {schema}.nexus_research_tasks "
                        f"({_JOB_SELECT}) "
                        f"VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                        f"ON CONFLICT (task_id) DO NOTHING",
                        (
                            row["task_id"], row.get("parent_task_id", ""),
                            row["owner"], row.get("session_id", ""),
                            json.dumps(row.get("brief") or {}, ensure_ascii=False),
                            json.dumps(row.get("questions") or [], ensure_ascii=False),
                            json.dumps(row.get("budget") or {}, ensure_ascii=False),
                            json.dumps(row.get("used") or {}, ensure_ascii=False),
                            row.get("status", TASK_OPEN),
                            json.dumps(row.get("findings") or [], ensure_ascii=False),
                            json.dumps(row.get("evidence_ids") or [], ensure_ascii=False),
                            json.dumps(row.get("gaps") or [], ensure_ascii=False),
                            json.dumps(row.get("conflicts") or [], ensure_ascii=False),
                            json.dumps(row.get("experiment_run_ids") or [],
                                       ensure_ascii=False),
                            row.get("report_artifact_id", ""),
                            bool(row.get("cancel_requested", False)),
                            row.get("detail", ""),
                            row.get("created_at", 0), row.get("updated_at", 0),
                        ),
                    )
            return
        except Exception as error:  # noqa: BLE001
            logger.warning("research task pg insert failed, memory: %s", error)
    _memory_tasks[row["task_id"]] = dict(row)


def _update_row(row: dict[str, Any]) -> None:
    pg = _pg_settings()
    if pg is not None:
        dsn, schema = pg
        try:
            import psycopg

            with psycopg.connect(dsn, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"UPDATE {schema}.nexus_research_tasks SET questions=%s, "
                        f"budget=%s, used=%s, status=%s, findings=%s, "
                        f"evidence_ids=%s, gaps=%s, conflicts=%s, "
                        f"experiment_run_ids=%s, report_artifact_id=%s, "
                        f"cancel_requested=%s, detail=%s, updated_at=%s "
                        f"WHERE task_id=%s",
                        (
                            json.dumps(row.get("questions") or [], ensure_ascii=False),
                            json.dumps(row.get("budget") or {}, ensure_ascii=False),
                            json.dumps(row.get("used") or {}, ensure_ascii=False),
                            row.get("status", TASK_OPEN),
                            json.dumps(row.get("findings") or [], ensure_ascii=False),
                            json.dumps(row.get("evidence_ids") or [], ensure_ascii=False),
                            json.dumps(row.get("gaps") or [], ensure_ascii=False),
                            json.dumps(row.get("conflicts") or [], ensure_ascii=False),
                            json.dumps(row.get("experiment_run_ids") or [],
                                       ensure_ascii=False),
                            row.get("report_artifact_id", ""),
                            bool(row.get("cancel_requested", False)),
                            row.get("detail", ""),
                            row.get("updated_at", _now()),
                            row["task_id"],
                        ),
                    )
            return
        except Exception as error:  # noqa: BLE001
            logger.warning("research task pg update failed: %s", error)
    _memory_tasks[row["task_id"]] = dict(row)


def get_task(task_id: str) -> dict[str, Any] | None:
    """读任务（归属由调用方校验；PG 优先，失败记日志后读内存）。"""
    task_id = (task_id or "").strip()[:64]
    if not task_id:
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
                        f"FROM {schema}.nexus_research_tasks WHERE task_id=%s",
                        (task_id,),
                    )
                    found = cur.fetchone()
            if found is not None:
                return _row_from_pg(found)
        except Exception as error:  # noqa: BLE001
            logger.warning("research task pg read failed: %s", error)
    stored = _memory_tasks.get(task_id)
    return _row_to_task(dict(stored)) if stored is not None else None


def list_tasks(owner: str, session_id: str = "") -> list[dict[str, Any]]:
    """列某用户的任务（session 为空即不过滤；按更新倒序，≤50）。"""
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
                            f"FROM {schema}.nexus_research_tasks "
                            f"WHERE owner=%s AND session_id=%s "
                            f"ORDER BY updated_at DESC LIMIT 50",
                            (owner, session_id),
                        )
                    else:
                        cur.execute(
                            f"SELECT {_JOB_SELECT} "
                            f"FROM {schema}.nexus_research_tasks "
                            f"WHERE owner=%s ORDER BY updated_at DESC LIMIT 50",
                            (owner,),
                        )
                    return [_row_from_pg(found)
                            for found in cur.fetchall()]
        except Exception as error:  # noqa: BLE001
            logger.warning("research task pg list failed: %s", error)
    items = [dict(v) for v in _memory_tasks.values()
             if str(v.get("owner") or "") == owner
             and (not session_id or str(v.get("session_id") or "") == session_id)]
    items.sort(key=lambda item: float(item.get("updated_at") or 0), reverse=True)
    return [_row_to_task(item) for item in items[:50]]


def create_task(
    *, owner: str, session_id: str = "", objective: str = "",
    dimensions: str | list[str] = "", data_range: str = "",
    time_range: str = "", delivery_format: str = "",
    questions: list[dict[str, Any]] | None = None,
    budget: dict[str, Any] | None = None,
    parent_task_id: str = "",
) -> dict[str, Any]:
    """创建研究任务（含 Brief 解析；子问题缺省由维度派生，占位待模型细化）。

    questions 项 {text, criteria}；空问题即单问题任务（以 objective 为题）。
    """
    owner = (owner or "").strip()
    if not owner:
        raise ResearchError("TASK_OWNER_EMPTY", "owner 不能为空。")
    objective = (objective or "").strip()[:500]
    if not objective:
        raise ResearchError("TASK_OBJECTIVE_EMPTY", "研究目标不能为空。")
    dims = (list(dimensions) if isinstance(dimensions, list)
            else parse_dimensions(str(dimensions or "")))
    dims = [str(part)[:60] for part in dims if str(part).strip()][:8]
    normalized_questions: list[dict[str, Any]] = []
    for index, item in enumerate(questions or []):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()[:300]
        if not text:
            continue
        normalized_questions.append({
            "id": f"q{index + 1}",
            "text": text,
            "criteria": str(item.get("criteria") or "")[:300],
            "status": "open",
        })
        if len(normalized_questions) >= 12:
            break
    if not normalized_questions:
        if dims:
            normalized_questions = [
                {"id": f"q{index + 1}",
                 "text": f"就维度“{dim}”回答：{objective}",
                 "criteria": "引用已登记证据，给出结论与缺口",
                 "status": "open"}
                for index, dim in enumerate(dims[:6])
            ]
        else:
            normalized_questions = [
                {"id": "q1", "text": objective,
                 "criteria": "引用已登记证据，给出结论与缺口", "status": "open"}
            ]
    merged_budget = dict(DEFAULT_BUDGET)
    if isinstance(budget, dict):
        for key in merged_budget:
            try:
                merged_budget[key] = max(1, min(int(budget.get(key, merged_budget[key])), 64))
            except (TypeError, ValueError):
                pass
    now = _now()
    row = {
        "task_id": f"rst-{uuid.uuid4().hex[:12]}",
        "parent_task_id": (parent_task_id or "").strip()[:64],
        "owner": owner, "session_id": (session_id or "").strip()[:128],
        "brief": {"objective": objective, "dimensions": dims,
                  "data_range": str(data_range or "")[:200],
                  "time_range": str(time_range or "")[:200],
                  "delivery_format": str(delivery_format or "")[:120]},
        "questions": normalized_questions,
        "budget": merged_budget,
        "used": {"rounds": 0, "subtasks": 0, "evidence_calls": 0},
        "status": TASK_OPEN,
        "findings": [], "evidence_ids": [], "gaps": [], "conflicts": [],
        "experiment_run_ids": [], "report_artifact_id": "",
        "cancel_requested": False, "detail": "",
        "created_at": now, "updated_at": now,
    }
    _insert_row(row)
    stored = get_task(row["task_id"])
    return dict(stored) if stored is not None else _row_to_task(row)


def _require_owned(task_id: str, owner: str) -> dict[str, Any]:
    task = get_task(task_id)
    if task is None:
        raise ResearchError("TASK_NOT_FOUND", "研究任务不存在或已不可恢复。")
    if (owner or "") != task["owner"]:
        raise ResearchError("TASK_FORBIDDEN", "无权操作他人的研究任务。")
    return task


def check_budget(task: dict[str, Any]) -> str:
    """预算检查（纯逻辑）：返回 "" 即充足，否则为耗尽原因。"""
    if bool(task.get("cancel_requested")):
        return "cancelled"
    budget = task.get("budget") or {}
    used = task.get("used") or {}
    for used_key, budget_key in (("rounds", "max_rounds"),
                                 ("subtasks", "max_subtasks"),
                                 ("evidence_calls", "max_evidence_calls")):
        try:
            if int(used.get(used_key, 0)) >= int(budget.get(
                    budget_key, DEFAULT_BUDGET[budget_key])):
                return f"budget_exhausted:{used_key}"
        except (TypeError, ValueError, KeyError):
            continue
    return ""


def _save(task: dict[str, Any]) -> dict[str, Any]:
    task["updated_at"] = _now()
    _update_row(task)
    stored = get_task(task["task_id"])
    return dict(stored) if stored is not None else task


def assign_next_question(task_id: str, owner: str) -> dict[str, Any]:
    """取下一个开放子问题并交办（原子：预算→配额→running）。

    返回 {"task", "question"} 或 {"task", "stopped": reason}（no_pending/
    budget_exhausted/cancelled/terminal）。配额在交办时扣除（rounds＋
    subtasks 各一），避免无预算的委派。
    """
    task = _require_owned(task_id, owner)
    if task["status"] in TASK_TERMINAL:
        return {"task": task, "stopped": "terminal"}
    if bool(task.get("cancel_requested")):
        task["status"] = TASK_CANCELLED
        task["detail"] = "用户已取消。"
        return {"task": _save(task), "stopped": "cancelled"}
    exhausted = check_budget(task)
    if exhausted:
        task["status"] = TASK_PARTIAL
        task["detail"] = f"研究预算已用尽（{exhausted}）；已保存材料保留。"
        return {"task": _save(task), "stopped": "budget_exhausted"}
    pending = [item for item in task.get("questions") or []
               if str(item.get("status") or "") == "open"]
    if not pending:
        if task["status"] != TASK_WAITING:
            task["status"] = TASK_WAITING
            task["detail"] = "子问题已交办完，待结果回收或交付。"
            task = _save(task)
        return {"task": task, "stopped": "no_pending"}
    # 配额先验后扣（rounds＋subtasks 各一）：任一不够即停，不透支。
    for used_key, budget_key in (("rounds", "max_rounds"),
                                 ("subtasks", "max_subtasks")):
        try:
            if int(task["used"].get(used_key, 0)) + 1 > int(
                    task["budget"].get(budget_key, DEFAULT_BUDGET[budget_key])):
                task["status"] = TASK_PARTIAL
                task["detail"] = (f"研究预算已用尽（budget_exhausted:{used_key}）；"
                                  "已保存材料保留。")
                return {"task": _save(task), "stopped": "budget_exhausted"}
        except (TypeError, ValueError, KeyError):
            continue
    for used_key in ("rounds", "subtasks"):
        task["used"][used_key] = int(task["used"].get(used_key, 0)) + 1
    if task["status"] == TASK_OPEN:
        task["status"] = TASK_RUNNING
    question = pending[0]
    for item in task.get("questions") or []:
        if str(item.get("id") or "") == str(question.get("id") or ""):
            item["status"] = "running"
    return {"task": _save(task), "question": question}


def consume_budget(task_id: str, owner: str, field: str) -> dict[str, Any]:
    """扣预算（rounds/subtasks/evidence_calls；超限即 ResearchError）。"""
    if field not in ("rounds", "subtasks", "evidence_calls"):
        raise ResearchError("BUDGET_FIELD_UNKNOWN", f"未知预算项：{field}")
    task = _require_owned(task_id, owner)
    if task["status"] in TASK_TERMINAL:
        raise ResearchError("TASK_TERMINAL", f"任务已终态（{task['status']}），不再扣预算。")
    if check_budget(task):
        raise ResearchError("RESEARCH_BUDGET_EXHAUSTED",
                            f"研究预算已用尽（{check_budget(task)}）；不再派生新工作。")
    task["used"][field] = int(task["used"].get(field, 0)) + 1
    if task["status"] == TASK_OPEN:
        task["status"] = TASK_RUNNING
    return _save(task)


def submit_finding(
    *, task_id: str, owner: str, question_id: str, summary: str,
    evidence_ids: list[str] | None = None, gaps: list[str] | None = None,
    conflicts: list[str] | None = None,
) -> dict[str, Any]:
    """登记子任务结果（只收摘要＋引用＋缺口＋冲突，不收全文）。

    evidence_ids 须可解析（内存登记或持久化证据，归属一致）；非法 id 即
    拒绝（引用 ID 合法不等于支持结论——综合仍须核对，此处只验存在性）。
    """
    from nexus import paper_evidence as evidence_module

    task = _require_owned(task_id, owner)
    if task["status"] in TASK_TERMINAL:
        raise ResearchError("TASK_TERMINAL", f"任务已终态（{task['status']}），不再接受结果。")
    question = next((item for item in task.get("questions") or []
                     if str(item.get("id") or "") == (question_id or "").strip()), None)
    if question is None:
        raise ResearchError("QUESTION_UNKNOWN", f"未知子问题：{question_id}")
    summary = (summary or "").strip()[:2000]
    if not summary:
        raise ResearchError("FINDING_EMPTY", "子任务结论摘要不能为空。")
    resolved: list[str] = []
    invalid: list[str] = []
    for raw in evidence_ids or []:
        eid = str(raw or "").strip()[:32]
        if not eid or eid in resolved:
            continue
        hit = evidence_module.get_registry().resolve(
            eid, user_id=owner, session_id=task.get("session_id") or "")
        if hit is None:
            hit = evidence_module.resolve_persisted(
                eid, user_id=owner, session_id=task.get("session_id") or "")
        if hit is None:
            invalid.append(eid)
        else:
            resolved.append(eid)
    if invalid:
        raise ResearchError(
            "EVIDENCE_ID_INVALID",
            f"以下引用无法解析（不存在/非本会话/他人证据）：{','.join(invalid[:10])}。")
    question["status"] = "done"
    findings = list(task.get("findings") or [])
    findings.append({"question_id": str(question.get("id") or ""),
                     "summary": summary, "evidence_ids": resolved,
                     "gaps": [str(item)[:300] for item in (gaps or [])][:10],
                     "conflicts": [str(item)[:300] for item in (conflicts or [])][:10]})
    task["findings"] = findings
    known = list(task.get("evidence_ids") or [])
    for eid in resolved:
        if eid not in known:
            known.append(eid)
    task["evidence_ids"] = known[:200]
    for item in (gaps or []):
        text = str(item)[:300]
        if text and text not in task.get("gaps", []):
            task["gaps"] = [*task.get("gaps", []), text][:50]
    for item in (conflicts or []):
        text = str(item)[:300]
        if text and text not in task.get("conflicts", []):
            task["conflicts"] = [*task.get("conflicts", []), text][:50]
    if task["status"] not in (TASK_RUNNING, TASK_WAITING):
        task["status"] = TASK_RUNNING
    return _save(task)


def link_experiment(task_id: str, owner: str, run_id: str) -> dict[str, Any]:
    """关联实验运行（引用同一研究任务启动的既有提案流结果）。

    只校验归属与 run 存在性；实验结论由实验域负责，本域只记引用。
    自主实验 run 才可关联（preset Worker 走其真实 job 标识，不在此冒充）。
    """
    from nexus import experiment_runs as runs_module

    task = _require_owned(task_id, owner)
    run = runs_module.get_run((run_id or "").strip()[:64])
    if run is None or (owner or "") != run.get("owner", ""):
        raise ResearchError("RUN_NOT_FOUND", "实验运行不存在或无权引用。")
    proposal_id = str(run.get("proposal_id") or "")
    if proposal_id:
        try:
            from nexus import proposals as proposals_module

            proposal = proposals_module.get_proposal(proposal_id)
            if proposal is not None and proposal.get("kind") != "autonomous_experiment":
                raise ResearchError(
                    "RUN_KIND_MISMATCH",
                    "仅自主实验 run 可关联；preset Worker 走其真实 job 标识。")
        except ResearchError:
            raise
        except Exception:  # noqa: BLE001 - 提案不可读不阻断引用（run 归属已验）
            pass
    linked = list(task.get("experiment_run_ids") or [])
    if run["run_id"] not in linked:
        linked.append(run["run_id"])
    task["experiment_run_ids"] = linked[:20]
    return _save(task)


def request_cancel(task_id: str, owner: str) -> dict[str, Any]:
    """用户取消任务（置旗；终态任务返回现态，不改写）。"""
    task = _require_owned(task_id, owner)
    if task["status"] in TASK_TERMINAL:
        return task
    task["cancel_requested"] = True
    task["status"] = TASK_CANCELLED
    task["detail"] = "用户已取消；已保存材料保留，可凭 namespace 恢复查看。"
    return _save(task)


def set_status(task_id: str, owner: str, status: str, detail: str = "") -> dict[str, Any]:
    """推进任务状态（终态不可改写；取消旗置位时只收敛到 cancelled）。"""
    if status not in (TASK_OPEN, TASK_RUNNING, TASK_WAITING, TASK_SUCCEEDED,
                      TASK_PARTIAL, TASK_FAILED, TASK_CANCELLED):
        raise ResearchError("TASK_STATUS_UNKNOWN", f"未知任务状态：{status}")
    task = _require_owned(task_id, owner)
    if task["status"] in TASK_TERMINAL:
        return task
    if status != TASK_CANCELLED and bool(task.get("cancel_requested")):
        task["status"] = TASK_CANCELLED
        task["detail"] = detail or "用户已取消。"
    else:
        task["status"] = status
        if detail:
            task["detail"] = detail[:2000]
    return _save(task)


def set_report(task_id: str, owner: str, artifact_id: str) -> dict[str, Any]:
    """登记研究报告产物（FrozenDocument 链路落盘后调用）。"""
    task = _require_owned(task_id, owner)
    task["report_artifact_id"] = (artifact_id or "").strip()[:64]
    return _save(task)


def delivery_checklist(task: dict[str, Any]) -> list[dict[str, Any]]:
    """交付核对（逐项确定性检查；完成看清单不看 Todo 全勾）。

    - has_evidence：至少一条已登记证据；
    - questions_done：子问题是否还有 open（有则未完成）；
    - gaps_acknowledged：缺口已记录或明确无缺口（gaps 为空＋全 done 即过）；
    - synthesis_report：研究报告产物已登记；
    - experiment_linked：仅当 brief 要求实验时检查（delivery_format 或
      objective 含“实验”），否则记不适用。
    """
    findings = task.get("findings") or []
    questions = task.get("questions") or []
    open_questions = [item for item in questions
                      if str(item.get("status") or "") != "done"]
    brief = task.get("brief") or {}
    wants_experiment = any("实验" in str(brief.get(key) or "")
                           for key in ("objective", "delivery_format"))
    items = [
        {"item": "has_evidence",
         "met": len(task.get("evidence_ids") or []) > 0,
         "detail": f"已登记证据 {len(task.get('evidence_ids') or [])} 条"},
        {"item": "questions_done",
         "met": not open_questions,
         "detail": ("子问题全 done" if not open_questions
                    else f"剩余 {len(open_questions)} 个子问题未完成")},
        {"item": "gaps_acknowledged",
         "met": bool(task.get("gaps")) or (not open_questions and bool(findings)),
         "detail": (f"已记录缺口 {len(task.get('gaps') or [])} 条"
                    if task.get("gaps") else "无已记录缺口")},
        {"item": "synthesis_report",
         "met": bool(str(task.get("report_artifact_id") or "")),
         "detail": ("研究报告已登记" if task.get("report_artifact_id")
                    else "研究报告未生成（经 create_document_output 落盘后登记）")},
    ]
    if wants_experiment:
        items.append({
            "item": "experiment_linked",
            "met": len(task.get("experiment_run_ids") or []) > 0,
            "detail": (f"已关联实验 {len(task.get('experiment_run_ids') or [])} 个"
                       if task.get("experiment_run_ids") else "Brief 要求实验但未关联运行"),
        })
    return items


def clear_memory_store() -> None:
    """测试隔离：清空内存任务（PG 行不受影响）。"""
    _memory_tasks.clear()
