"""F2 操作意图与执行租约（持久执行基础，不建通用调度框架）。

能力判定结论（2026-09-10，见计划 §4.1/§7）：
- LangGraph Postgres checkpoint 可用（main lifespan 已接 AsyncPostgresSaver，
  saver.setup() 管其原生表迁移；应用启动只读检查 Nexus 域表）；
- SWE-ReX 1.4.0 有 BashInterruptAction/run_in_session/RemoteRuntime.from_config
 （已读其安装源码验证），但本机 adapter 走 one-shot execute 且 DockerDeployment
  无 attach 已有容器 API——控制重启后容器存活也无法重连，本批如实标
  unknown/不可自动恢复，不自研 attach（F3 再评估会话语义）；
- 控制面同 operation_id 返回旧记录但不校验命令（缺口，本批补 request_hash＋
  OPERATION_ID_CONFLICT）。

本模块只做三件事：
1. OperationIntent：外部副作用前原子登记（stable operation_id＋请求哈希＋
   待提交状态）。身份由持久意图派生，Backend 重建不重置；写失败即不执行。
2. ExecutionLease：DB 租约＋单调 fencing token，防止两个恢复者同时接管；
   控制端拒绝旧 token 的新提交（控制面实现见 deploy/repro-runtime）。
3. 对账决策：已知未提交 prepared→可提交；已接受/未知→先查（终态证据回写
   并继续，running 接管，unknown 进 reconciling 不重交）。

存储：PG（nexus_operation_intents／nexus_execution_leases，见
nexus/migrations/0002_f2_operations.sql）＋内存降级（与 experiment_runs
同失败语义）。Nexus 与控制服务各持己方持久状态，不直接写对方表。
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from typing import Any

logger = logging.getLogger("nexus.experiment_operations")

INTENT_STATUSES = (
    "prepared", "submitted", "running",
    "succeeded", "failed", "cancelled", "timed_out", "reconciling",
)
INTENT_TERMINAL = ("succeeded", "failed", "cancelled", "timed_out")

_memory_intents: dict[str, dict[str, Any]] = {}
_memory_leases: dict[str, dict[str, Any]] = {}


class OperationError(Exception):
    """操作意图域失败：携带机器可读 code（fail-closed 语义）。"""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


def _now() -> float:
    return time.time()


def request_hash(command: str, timeout_s: float | None = None) -> str:
    """请求哈希（稳定：命令 strip＋超时归一；同请求同哈希，不同即冲突）。"""
    normalized = (command or "").strip()
    try:
        timeout_part = "" if timeout_s is None else f"{float(timeout_s):.3f}"
    except (TypeError, ValueError):
        timeout_part = str(timeout_s)
    digest = hashlib.sha256(
        f"{normalized}\x00{timeout_part}".encode("utf-8")).hexdigest()
    return digest[:32]


def stable_operation_id(run_id: str, seq: int) -> str:
    """稳定 operation_id（run-op-NNNN；重试不重随机，重启不重置）。"""
    return f"{(run_id or '').strip()[:64]}-op-{max(0, int(seq)):04d}"[:128]


def _intent_key(run_id: str, operation_id: str) -> str:
    return f"{(run_id or '').strip()[:64]}|{(operation_id or '').strip()[:128]}"


def _pg_settings() -> tuple[str, str] | None:
    from nexus.experiment_runs import _pg_settings as runs_pg_settings

    try:
        return runs_pg_settings()
    except Exception:  # noqa: BLE001 - 配置不可读即内存降级
        return None


def _row_to_intent(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "intent_key": str(row.get("intent_key") or ""),
        "run_id": str(row.get("run_id") or ""),
        "operation_id": str(row.get("operation_id") or ""),
        "seq": int(row.get("seq") or 0),
        "request_hash": str(row.get("request_hash") or ""),
        "command": str(row.get("command") or ""),
        "timeout_s": row.get("timeout_s"),
        "op_type": str(row.get("op_type") or "execute"),
        "status": str(row.get("status") or "prepared"),
        "exit_code": row.get("exit_code"),
        "output_tail": str(row.get("output_tail") or ""),
        "created_at": float(row.get("created_at") or 0),
        "updated_at": float(row.get("updated_at") or 0),
    }


def get_intent(run_id: str, operation_id: str) -> dict[str, Any] | None:
    """读意图（PG 优先，失败记日志后读内存；与 runs 同降级语义）。"""
    key = _intent_key(run_id, operation_id)
    pg = _pg_settings()
    if pg is not None:
        dsn, schema = pg
        try:
            import psycopg

            with psycopg.connect(dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT intent_key, run_id, operation_id, seq, "
                        f"request_hash, command, timeout_s, op_type, status, "
                        f"exit_code, output_tail, created_at, updated_at "
                        f"FROM {schema}.nexus_operation_intents "
                        f"WHERE intent_key = %s", (key,))
                    found = cur.fetchone()
            if found is not None:
                cols = ("intent_key", "run_id", "operation_id", "seq",
                        "request_hash", "command", "timeout_s", "op_type",
                        "status", "exit_code", "output_tail",
                        "created_at", "updated_at")
                return _row_to_intent(dict(zip(cols, found)))
        except Exception as error:  # noqa: BLE001
            logger.warning("operation intent pg read failed: %s", error)
    stored = _memory_intents.get(key)
    return dict(stored) if stored is not None else None


def prepare_intent(
    *, run_id: str, seq: int, command: str,
    timeout_s: float | None = None, op_type: str = "execute",
    operation_id: str = "",
) -> dict[str, Any]:
    """执行前原子登记意图（副作用前必须调用；失败即不得 submit）。

    - 新 key → prepared 落盘，返回 {"intent", "deduped": False}；
    - 同 key 同哈希 → 返回原意图 deduped（调用方先对账，不重交）；
    - 同 key 不同哈希 → OperationError(OPERATION_ID_CONFLICT)，不得重跑。
    operation_id 缺省按 (run, seq) 稳定派生；重放等需唯一后缀的调用方
    可显式传入（如干净B的 per-replay nonce id），seq 仍用于排序。
    """
    cleaned_run = (run_id or "").strip()
    if not cleaned_run:
        raise OperationError("INTENT_RUN_EMPTY", "run_id 不能为空")
    cleaned_command = (command or "").strip()
    if not cleaned_command:
        raise OperationError("INTENT_COMMAND_EMPTY", "实际命令不能为空")
    operation_id = (operation_id or "").strip()[:128] or stable_operation_id(
        cleaned_run, seq)
    digest = request_hash(cleaned_command, timeout_s)
    key = _intent_key(cleaned_run, operation_id)
    now = _now()
    existing = get_intent(cleaned_run, operation_id)
    if existing is not None:
        if str(existing.get("request_hash") or "") == digest:
            return {"intent": existing, "deduped": True}
        raise OperationError(
            "OPERATION_ID_CONFLICT",
            f"operation_id {operation_id} 已登记不同请求；旧进程无退出证明"
            "不得重跑，先对账（query）再定夺。")
    row = {
        "intent_key": key, "run_id": cleaned_run, "operation_id": operation_id,
        "seq": int(seq), "request_hash": digest,
        "command": cleaned_command[:2000], "timeout_s": timeout_s,
        "op_type": (op_type or "execute")[:32], "status": "prepared",
        "exit_code": None, "output_tail": "",
        "created_at": now, "updated_at": now,
    }
    pg = _pg_settings()
    if pg is not None:
        dsn, schema = pg
        try:
            import psycopg

            with psycopg.connect(dsn, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"INSERT INTO {schema}.nexus_operation_intents "
                        f"(intent_key, run_id, operation_id, seq, request_hash, "
                        f"command, timeout_s, op_type, status, exit_code, "
                        f"output_tail, created_at, updated_at) "
                        f"VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                        f"ON CONFLICT (intent_key) DO NOTHING",
                        (key, cleaned_run, operation_id, int(seq), digest,
                         cleaned_command[:2000], timeout_s,
                         (op_type or "execute")[:32], "prepared", None, "",
                         now, now))
            stored = get_intent(cleaned_run, operation_id)
            if stored is None:  # pragma: no cover - 极小竞态窗口
                raise OperationError("INTENT_PERSIST_FAILED", "意图落盘后不可读")
            if str(stored.get("request_hash") or "") != digest:
                raise OperationError(
                    "OPERATION_ID_CONFLICT",
                    f"operation_id {operation_id} 已被他人登记；不得重跑，先对账。")
            return {"intent": stored,
                    "deduped": str(stored.get("request_hash") or "") == digest
                    and float(stored.get("created_at") or 0) < now}
        except OperationError:
            raise
        except Exception as error:  # noqa: BLE001 - PG 故障记日志后内存登记
            logger.warning("operation intent pg insert failed, memory: %s", error)
    _memory_intents[key] = dict(row)
    return {"intent": dict(row), "deduped": False}


def set_intent_status(
    run_id: str, operation_id: str, status: str, *,
    exit_code: int | None = None, output_tail: str = "",
) -> dict[str, Any] | None:
    """推进意图状态（终态只可由非终态进入；终态不可改写）。"""
    if status not in INTENT_STATUSES:
        raise OperationError("INTENT_STATUS_UNKNOWN", f"未知意图状态：{status}")
    intent = get_intent(run_id, operation_id)
    if intent is None:
        return None
    if intent["status"] in INTENT_TERMINAL and status != intent["status"]:
        return intent
    updated = dict(intent)
    updated["status"] = status
    if exit_code is not None:
        updated["exit_code"] = exit_code
    if output_tail:
        updated["output_tail"] = str(output_tail)[-2000:]
    updated["updated_at"] = _now()
    key = _intent_key(run_id, operation_id)
    pg = _pg_settings()
    if pg is not None:
        dsn, schema = pg
        try:
            import psycopg

            with psycopg.connect(dsn, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"UPDATE {schema}.nexus_operation_intents SET status=%s, "
                        f"exit_code=%s, output_tail=%s, updated_at=%s "
                        f"WHERE intent_key=%s", (
                            updated["status"], updated["exit_code"],
                            updated["output_tail"], updated["updated_at"], key))
            return updated
        except Exception as error:  # noqa: BLE001
            logger.warning("operation intent pg update failed: %s", error)
    _memory_intents[key] = dict(updated)
    return updated


def list_run_intents(run_id: str) -> list[dict[str, Any]]:
    """列某 run 全部意图（恢复对账用；按 seq 升序）。"""
    cleaned = (run_id or "").strip()
    pg = _pg_settings()
    if pg is not None:
        dsn, schema = pg
        try:
            import psycopg

            with psycopg.connect(dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT intent_key, run_id, operation_id, seq, "
                        f"request_hash, command, timeout_s, op_type, status, "
                        f"exit_code, output_tail, created_at, updated_at "
                        f"FROM {schema}.nexus_operation_intents "
                        f"WHERE run_id = %s ORDER BY seq ASC", (cleaned,))
                    cols = ("intent_key", "run_id", "operation_id", "seq",
                            "request_hash", "command", "timeout_s", "op_type",
                            "status", "exit_code", "output_tail",
                            "created_at", "updated_at")
                    return [_row_to_intent(dict(zip(cols, found)))
                            for found in cur.fetchall()]
        except Exception as error:  # noqa: BLE001
            logger.warning("operation intent pg list failed: %s", error)
    items = [dict(v) for v in _memory_intents.values()
             if str(v.get("run_id") or "") == cleaned]
    return sorted(items, key=lambda item: int(item.get("seq") or 0))


def reconcile_decision(intent: dict[str, Any] | None,
                       remote: dict[str, Any] | None) -> str:
    """对账决策（纯函数，可单测；未知先对账，不自动重交）。

    - 无意图 → "no_intent"（调用方不得执行）；
    - prepared 且远端无记录/unknown → "submittable"（唯一可提交路径）；
    - 远端终态（succeeded/failed/cancelled）→ "adopt_terminal"（回写并继续）；
    - 远端 running → "adopt_running"（接管等待，不重交）；
    - 其余（submitted/running/reconciling 意图＋远端未知）→ "unknown_hold"
      （进 reconciling 展示，可重试查询，禁重交）。
    """
    if not intent:
        return "no_intent"
    remote_status = str((remote or {}).get("status") or "unknown")
    if remote_status in ("succeeded", "failed", "cancelled"):
        return "adopt_terminal"
    if remote_status == "running":
        return "adopt_running"
    if str(intent.get("status") or "") == "prepared":
        return "submittable"
    return "unknown_hold"


# -- 执行租约 ------------------------------------------------------------

def acquire_lease(run_id: str, holder: str, ttl_s: float = 120.0) -> dict[str, Any]:
    """获取 run 执行租约（拿不到只观察，不执行）。

    返回 {"acquired", "fencing", "holder"}：acquired 为 True 即本 holder 持有；
    fencing 为单调 token（旧 token 的提交必须被拒绝）。过期租约可被接管，
    但接管者须先核对控制面/容器（锁过期≠旧命令已停止）。
    """
    cleaned_run = (run_id or "").strip()
    if not cleaned_run:
        raise OperationError("LEASE_RUN_EMPTY", "run_id 不能为空")
    cleaned_holder = (holder or "").strip()[:128] or f"holder-{uuid.uuid4().hex[:8]}"
    now = _now()
    ttl = max(5.0, float(ttl_s or 120.0))
    pg = _pg_settings()
    if pg is not None:
        dsn, schema = pg
        try:
            import psycopg

            fencing = ""
            acquired = False
            with psycopg.connect(dsn, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT holder, fencing, expires_at "
                        f"FROM {schema}.nexus_execution_leases WHERE run_id=%s",
                        (cleaned_run,))
                    found = cur.fetchone()
                    if found is None:
                        fencing = uuid.uuid4().hex[:12]
                        cur.execute(
                            f"INSERT INTO {schema}.nexus_execution_leases "
                            f"(run_id, holder, fencing, expires_at, updated_at) "
                            f"VALUES (%s,%s,%s,%s,%s) "
                            f"ON CONFLICT (run_id) DO NOTHING",
                            (cleaned_run, cleaned_holder, fencing,
                             now + ttl, now))
                        cur.execute(
                            f"SELECT holder, fencing, expires_at "
                            f"FROM {schema}.nexus_execution_leases WHERE run_id=%s",
                            (cleaned_run,))
                        found = cur.fetchone()
                    holder_now, fencing_now, expires_now = (
                        str(found[0] or ""), str(found[1] or ""),
                        float(found[2] or 0))
                    if holder_now == cleaned_holder or expires_now <= now:
                        fencing = uuid.uuid4().hex[:12]
                        cur.execute(
                            f"UPDATE {schema}.nexus_execution_leases SET holder=%s, "
                            f"fencing=%s, expires_at=%s, updated_at=%s "
                            f"WHERE run_id=%s AND (holder=%s OR expires_at<=%s)",
                            (cleaned_holder, fencing, now + ttl, now,
                             cleaned_run, holder_now, now))
                        acquired = cur.rowcount > 0
                        if not acquired:  # 竞态输了：读回现持有者
                            cur.execute(
                                f"SELECT holder, fencing FROM "
                                f"{schema}.nexus_execution_leases WHERE run_id=%s",
                                (cleaned_run,))
                            refound = cur.fetchone()
                            if refound is not None:
                                holder_now, fencing_now = (
                                    str(refound[0] or ""), str(refound[1] or ""))
                                fencing = fencing_now
                    else:
                        fencing = fencing_now
            return {"acquired": acquired, "fencing": fencing,
                    "holder": cleaned_holder if acquired else holder_now}
        except Exception as error:  # noqa: BLE001
            logger.warning("lease pg acquire failed, memory: %s", error)
    current = _memory_leases.get(cleaned_run)
    if current is None or float(current.get("expires_at") or 0) <= now \
            or str(current.get("holder") or "") == cleaned_holder:
        fencing = uuid.uuid4().hex[:12]
        _memory_leases[cleaned_run] = {
            "run_id": cleaned_run, "holder": cleaned_holder,
            "fencing": fencing, "expires_at": now + ttl, "updated_at": now}
        return {"acquired": True, "fencing": fencing, "holder": cleaned_holder}
    return {"acquired": False, "fencing": str(current.get("fencing") or ""),
            "holder": str(current.get("holder") or "")}


def release_lease(run_id: str, holder: str, fencing: str = "") -> bool:
    """释放租约（完成/取消/失败均调用；holder 不符不释放，返回 False）。"""
    cleaned_run = (run_id or "").strip()
    cleaned_holder = (holder or "").strip()
    pg = _pg_settings()
    if pg is not None:
        dsn, schema = pg
        try:
            import psycopg

            with psycopg.connect(dsn, autocommit=True) as conn:
                with conn.cursor() as cur:
                    if fencing:
                        cur.execute(
                            f"DELETE FROM {schema}.nexus_execution_leases "
                            f"WHERE run_id=%s AND holder=%s AND fencing=%s",
                            (cleaned_run, cleaned_holder, fencing))
                    else:
                        cur.execute(
                            f"DELETE FROM {schema}.nexus_execution_leases "
                            f"WHERE run_id=%s AND holder=%s",
                            (cleaned_run, cleaned_holder))
                    return (cur.rowcount or 0) > 0
        except Exception as error:  # noqa: BLE001
            logger.warning("lease pg release failed: %s", error)
            return False
    current = _memory_leases.get(cleaned_run)
    if current is None:
        return True
    if str(current.get("holder") or "") != cleaned_holder:
        return False
    if fencing and str(current.get("fencing") or "") != fencing:
        return False
    _memory_leases.pop(cleaned_run, None)
    return True


def clear_memory_store() -> None:
    """测试隔离：清空内存意图＋租约（PG 行不受影响）。"""
    _memory_intents.clear()
    _memory_leases.clear()


def force_release_run(run_id: str) -> None:
    """终态强制回收 run 租约（完成/取消/失败/收敛路径调用）。

    终态 run 不再接受新执行者，残留租约只会阻塞恢复认领的诚实判断；
    新执行本就被 run 状态机拒绝，此处按 run 全量删除（best-effort）。
    """
    cleaned_run = (run_id or "").strip()
    if not cleaned_run:
        return
    pg = _pg_settings()
    if pg is not None:
        dsn, schema = pg
        try:
            import psycopg

            with psycopg.connect(dsn, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"DELETE FROM {schema}.nexus_execution_leases "
                        f"WHERE run_id=%s", (cleaned_run,))
            return
        except Exception as error:  # noqa: BLE001
            logger.warning("lease force-release pg failed: %s", error)
    _memory_leases.pop(cleaned_run, None)
