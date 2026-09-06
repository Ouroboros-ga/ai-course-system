"""NX-G2 服务端执行审批（Hard Workflow，v1.3 A3）。

UI 抽屉、前后端确认文案、Research Mode、白名单都不等于批准。本模块是
`run_reproduction` 及后续危险/昂贵操作的**唯一放行点**：

- 提案：工具调用先创建持久化的 ApprovalRequest（pending），**此时零 Worker
  提交**；归属（user/session/tool/preset/plan hash/预算）在这一步落库，
  不依赖提交后的 best-effort 登记；
- 批准：本人（服务端登录身份）批准/拒绝；票据一次性、幂等、有有效期；
- 执行：批准被消费（approved→consumed 原子转换）后才提交 Worker；重试
  同一票据返回原 job，不重复启动实验。

存储：PG 可用时进 ``nexus_checkpoints.nexus_approvals``（与 threads 表同
schema/同失败语义）；本地/测试无 DSN 时用进程内存（重启即失——pending
审批在重启后查不到，读侧如实返回 NOT_FOUND，不伪造状态）。

票据绝不经模型生成：批准 id 由服务端创建，经请求上下文（request_scope，
非工具参数）注入工具；工具只做服务端校验。
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from typing import Any

logger = logging.getLogger("nexus.approvals")

APPROVAL_ID_PREFIX = "apv_"

# 内存降级存储（无 DSN 时）。结构与 PG 行同构，见 _row_to_dict。
_memory_approvals: dict[str, dict[str, Any]] = {}


def _now() -> float:
    return time.time()


def new_approval_id() -> str:
    return f"{APPROVAL_ID_PREFIX}{uuid.uuid4().hex[:12]}"


def plan_hash_for(preset: dict[str, Any]) -> str:
    """绑定计划内容：preset 实质变化（仓库/命令/License）即失配，旧批准失效。"""
    canonical = {
        "preset_id": preset.get("preset_id", ""),
        "repo_url": preset.get("repo_url", ""),
        "repo_license": preset.get("repo_license", ""),
        "steps": list(preset.get("steps") or []),
    }
    raw = json.dumps(canonical, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def budget_for(preset: dict[str, Any]) -> dict[str, Any]:
    """批准绑定的资源预算快照（展示 + 失配即失效的依据之一）。"""
    return {
        "estimated_minutes": preset.get("estimated_minutes"),
        "max_steps": len(list(preset.get("steps") or [])),
        "cpu_friendly": bool(preset.get("cpu_friendly", True)),
    }


def _row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "approval_id": row["approval_id"],
        "user_id": row["user_id"],
        "session_id": row["session_id"],
        "tool": row["tool"],
        "preset_id": row["preset_id"],
        "plan_hash": row["plan_hash"],
        "budget": row["budget"],
        "status": row["status"],
        "job_id": row.get("job_id"),
        "detail": row.get("detail", ""),
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
    }


def _is_expired(row: dict[str, Any], now: float | None = None) -> bool:
    return (now if now is not None else _now()) >= float(row["expires_at"])


APPROVALS_DDL = """
CREATE SCHEMA IF NOT EXISTS {schema};
CREATE TABLE IF NOT EXISTS {schema}.nexus_approvals (
    approval_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT '',
    session_id TEXT NOT NULL DEFAULT '',
    tool TEXT NOT NULL DEFAULT '',
    preset_id TEXT NOT NULL DEFAULT '',
    plan_hash TEXT NOT NULL DEFAULT '',
    budget JSONB NOT NULL DEFAULT '{{}}',
    status TEXT NOT NULL DEFAULT 'pending',
    job_id TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '',
    created_at DOUBLE PRECISION NOT NULL DEFAULT 0,
    expires_at DOUBLE PRECISION NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_nexus_approvals_user
    ON {schema}.nexus_approvals (user_id, created_at DESC);
"""


def _pg_settings() -> tuple[str, str] | None:
    """PG 可用返回 (dsn, schema)，否则 None（调用方走内存）。"""
    from nexus.config import get_settings

    settings = get_settings()
    dsn = settings.postgres_dsn.strip()
    if not dsn:
        return None
    return dsn, settings.postgres_schema


def ensure_approvals_table(dsn: str, schema: str) -> None:
    """幂等建表（lifespan/首次写入前调用；失败抛异常由调用方降级）。"""
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(APPROVALS_DDL.format(schema=schema))


def create_approval(
    *,
    user_id: str,
    session_id: str,
    tool: str,
    preset: dict[str, Any],
    ttl_s: int,
) -> dict[str, Any]:
    """创建 pending 审批（提案持久化）。零外部调用，可安全在工具内执行。"""
    now = _now()
    row = {
        "approval_id": new_approval_id(),
        "user_id": user_id or "",
        "session_id": session_id or "",
        "tool": tool,
        "preset_id": str(preset.get("preset_id", "")),
        "plan_hash": plan_hash_for(preset),
        "budget": budget_for(preset),
        "status": "pending",
        "job_id": "",
        "detail": "",
        "created_at": now,
        "expires_at": now + max(1, int(ttl_s)),
    }
    pg = _pg_settings()
    if pg is not None:
        dsn, schema = pg
        try:
            ensure_approvals_table(dsn, schema)
            import psycopg

            with psycopg.connect(dsn, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"INSERT INTO {schema}.nexus_approvals "
                        "(approval_id, user_id, session_id, tool, preset_id, plan_hash, "
                        "budget, status, job_id, detail, created_at, expires_at) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (
                            row["approval_id"], row["user_id"], row["session_id"],
                            row["tool"], row["preset_id"], row["plan_hash"],
                            json.dumps(row["budget"], ensure_ascii=False),
                            row["status"], row["job_id"], row["detail"],
                            row["created_at"], row["expires_at"],
                        ),
                    )
            return _row_to_dict(row)
        except Exception as error:  # noqa: BLE001 - PG 故障降级内存，不阻断提案
            logger.warning("approval pg insert failed, memory fallback: %s", error)
    _memory_approvals[row["approval_id"]] = dict(row)
    return _row_to_dict(row)


def get_approval(approval_id: str) -> dict[str, Any] | None:
    """读审批（含过期懒标记：pending 过期读作 expired，不改库内终态）。"""
    pg = _pg_settings()
    row: dict[str, Any] | None = None
    if pg is not None:
        dsn, schema = pg
        try:
            import psycopg

            with psycopg.connect(dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT approval_id, user_id, session_id, tool, preset_id, "
                        f"plan_hash, budget, status, job_id, detail, created_at, expires_at "
                        f"FROM {schema}.nexus_approvals WHERE approval_id = %s",
                        (approval_id,),
                    )
                    found = cur.fetchone()
            if found is not None:
                keys = ("approval_id", "user_id", "session_id", "tool", "preset_id",
                        "plan_hash", "budget", "status", "job_id", "detail",
                        "created_at", "expires_at")
                row = dict(zip(keys, found))
                if isinstance(row["budget"], str):
                    row["budget"] = json.loads(row["budget"])
        except Exception as error:  # noqa: BLE001
            logger.warning("approval pg read failed: %s", error)
            row = None
    if row is None:
        stored = _memory_approvals.get(approval_id)
        row = dict(stored) if stored is not None else None
    if row is None:
        return None
    if row["status"] == "pending" and _is_expired(row):
        return {**_row_to_dict(row), "status": "expired"}
    return _row_to_dict(row)


class ApprovalError(Exception):
    """批准/消费失败：携带机器可读 code（fail-closed 语义）。"""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


def _pg_transition(
    approval_id: str, expect: str, update_sql: str, params: tuple
) -> dict[str, Any] | None:
    """PG 原子状态转换（期望状态行级过滤）；不匹配返回 None。"""
    pg = _pg_settings()
    if pg is None:
        return None
    dsn, schema = pg
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE {schema}.nexus_approvals SET {update_sql} "
                f"WHERE approval_id = %s AND status = %s "
                f"RETURNING approval_id, user_id, session_id, tool, preset_id, "
                f"plan_hash, budget, status, job_id, detail, created_at, expires_at",
                (*params, approval_id, expect),
            )
            found = cur.fetchone()
    if found is None:
        return None
    keys = ("approval_id", "user_id", "session_id", "tool", "preset_id",
            "plan_hash", "budget", "status", "job_id", "detail",
            "created_at", "expires_at")
    row = dict(zip(keys, found))
    if isinstance(row["budget"], str):
        row["budget"] = json.loads(row["budget"])
    return _row_to_dict(row)


def decide_approval(approval_id: str, user_id: str, decision: str) -> dict[str, Any]:
    """本人批准/拒绝（pending→approved/rejected；幂等：重复同决定返回现态）。

    跨用户一律拒绝（APPROVAL_FORBIDDEN），不泄露审批归属以外的任何信息。
    """
    current = get_approval(approval_id)
    if current is None:
        raise ApprovalError("APPROVAL_NOT_FOUND", "审批不存在或已不可恢复")
    if (user_id or "") != current["user_id"]:
        raise ApprovalError("APPROVAL_FORBIDDEN", "无权操作他人的审批")
    if decision not in ("approved", "rejected"):
        raise ApprovalError("APPROVAL_BAD_DECISION", "decision 仅支持 approved/rejected")
    if current["status"] == decision:
        return current  # 幂等：重复提交同决定
    if current["status"] == "expired" or (
        current["status"] == "pending" and _is_expired(current)
    ):
        raise ApprovalError("APPROVAL_EXPIRED", "审批已过期，请重新提案")
    if current["status"] != "pending":
        raise ApprovalError(
            "APPROVAL_STATE_CONFLICT",
            f"审批已终态（{current['status']}），不可再决定",
        )
    transitioned = _pg_transition(
        approval_id, "pending", "status = %s", (decision,)
    )
    if transitioned is not None:
        return transitioned
    stored = _memory_approvals.get(approval_id)
    if stored is None or stored["status"] != "pending":
        # 并发竞争：重读现态（对方已终态则按终态报错/幂等）。
        return decide_approval(approval_id, user_id, decision)
    stored["status"] = decision
    return _row_to_dict(stored)


def consume_approval(
    approval_id: str, *, user_id: str, session_id: str, preset: dict[str, Any]
) -> dict[str, Any]:
    """消费批准（approved→consumed 原子转换），返回可执行的审批行。

    校验全部绑定：本人/同会话/同工具无关（tool 由调用方固定）/plan_hash
    一致/未过期。已消费返回原行（含 job_id，供幂等重试直接返回原 job）。
    任何失配一律抛 ApprovalError——调用方不得提交 Worker。
    """
    current = get_approval(approval_id)
    if current is None:
        raise ApprovalError("APPROVAL_NOT_FOUND", "审批不存在或已不可恢复")
    if (user_id or "") != current["user_id"]:
        raise ApprovalError("APPROVAL_FORBIDDEN", "无权消费他人的审批")
    if (session_id or "") != current["session_id"]:
        raise ApprovalError("APPROVAL_SESSION_MISMATCH", "审批与当前会话不一致")
    if current["status"] == "consumed":
        return current  # 幂等：重试返回原行，调用方凭 job_id 返回原 job
    if current["status"] != "approved":
        raise ApprovalError(
            "APPROVAL_NOT_APPROVED",
            f"审批未批准（现态 {current['status']}），不得执行",
        )
    if _is_expired(current):
        raise ApprovalError("APPROVAL_EXPIRED", "审批已过期，请重新提案")
    if plan_hash_for(preset) != current["plan_hash"]:
        raise ApprovalError(
            "APPROVAL_PLAN_CHANGED",
            "复现计划已变化，旧批准失效，请重新提案",
        )
    transitioned = _pg_transition(
        approval_id, "approved", "status = 'consumed'", ()
    )
    if transitioned is not None:
        return transitioned
    stored = _memory_approvals.get(approval_id)
    if stored is None:
        raise ApprovalError("APPROVAL_NOT_FOUND", "审批已不可恢复")
    if stored["status"] == "consumed":
        return _row_to_dict(stored)
    if stored["status"] != "approved":
        # 并发竞争：重读裁决。
        return consume_approval(approval_id, user_id=user_id, session_id=session_id, preset=preset)
    stored["status"] = "consumed"
    return _row_to_dict(stored)


def attach_job(approval_id: str, job_id: str) -> None:
    """消费后绑定 job_id（best-effort  linkage；失败只记日志，不影响已提交作业）。"""
    pg = _pg_settings()
    if pg is not None:
        dsn, schema = pg
        try:
            import psycopg

            with psycopg.connect(dsn, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"UPDATE {schema}.nexus_approvals SET job_id = %s "
                        f"WHERE approval_id = %s",
                        (job_id, approval_id),
                    )
            return
        except Exception as error:  # noqa: BLE001
            logger.warning("approval attach_job pg failed: %s", error)
    stored = _memory_approvals.get(approval_id)
    if stored is not None:
        stored["job_id"] = job_id


def clear_memory_store() -> None:
    """测试隔离：清空内存审批（PG 行不受影响，测试不用真实 PG）。"""
    _memory_approvals.clear()
