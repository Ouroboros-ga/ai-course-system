"""NX-LB2 结构化实验提案域（Runtime 自有存储，归 Runtime 业务编排）。

"在输入框提出修改"真实落地的核心：提案是"可版本化修改的计划草案"，
审批引用 proposal_id+version+hash，执行 run 保存批准时的不可变快照。

- 提案模型：proposal_id/owner+session/version/preset/parent_run/objective/
  parameters/environment/repo_revision/data+seed/steps/budget/metric_policy/
  plan_hash（提案hash）/status/created_at；
- 参数边界：首版仅 nanoGPT 审核过的 typed schema；未知字段/非法组合拒绝，
  不做 shell 字符串替换；服务端由参数**确定性生成**冻结命令；
- 指标基线：仅全默认参数＋默认数据/环境才继承预设已验证基线，否则
  exploratory（有实测值、无 PASS 宣称）；模型不得自填容差；
- 存储：PG ``nexus_checkpoints.nexus_proposals``＋内存降级（与 approvals
  同失败语义）；执行入口见 main.py，核销见 approvals.py 提案绑定分支。
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from typing import Any

logger = logging.getLogger("nexus.proposals")

PROPOSAL_ID_PREFIX = "pp_"

# T2 自主实验提案 kind 判别：缺省 preset；autonomous_experiment 消费
# ExperimentScope，不要求 preset_id（任务书 T2）。
PROPOSAL_KIND_PRESET = "preset"
PROPOSAL_KIND_AUTONOMOUS = "autonomous_experiment"
PROPOSAL_KINDS = frozenset({PROPOSAL_KIND_PRESET, PROPOSAL_KIND_AUTONOMOUS})

_memory_proposals: dict[str, dict[str, Any]] = {}


def _now() -> float:
    return time.time()


def new_proposal_id() -> str:
    return f"{PROPOSAL_ID_PREFIX}{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# 参数 schema（首版：nanoGPT 审核集；仅出现在此处的 train flags 可调）
# ---------------------------------------------------------------------------

NANOGPT_PARAM_SCHEMA: dict[str, dict[str, Any]] = {
    "max_iters": {"type": "int", "min": 100, "max": 5000, "default": 2000,
                  "metric_sensitive": True, "help": "训练总步数"},
    "batch_size": {"type": "int", "min": 4, "max": 32, "default": 12,
                   "metric_sensitive": True, "help": "每步 batch"},
    "eval_iters": {"type": "int", "min": 5, "max": 200, "default": 20,
                   "metric_sensitive": False, "help": "评估迭代数（仅测量）"},
    "eval_interval": {"type": "int", "min": 1, "max": 5000, "default": 2000,
                      "metric_sensitive": True,
                      "help": "评估/存档间隔（ckpt 只在整除步写盘）"},
    "block_size": {"type": "int", "min": 16, "max": 256, "default": 64,
                   "metric_sensitive": True, "help": "上下文长度"},
    "n_layer": {"type": "int", "min": 1, "max": 12, "default": 4,
                "metric_sensitive": True, "help": "Transformer 层数"},
    "n_head": {"type": "int", "min": 1, "max": 12, "default": 4,
               "metric_sensitive": True, "help": "注意力头数"},
    "n_embd": {"type": "int", "min": 32, "max": 512, "default": 128,
               "metric_sensitive": True, "help": "嵌入维度"},
    "dropout": {"type": "float", "min": 0.0, "max": 0.5, "default": 0.0,
                "metric_sensitive": True, "help": "dropout 率"},
    "log_interval": {"type": "int", "min": 1, "max": 100, "default": 1,
                     "metric_sensitive": False, "help": "日志间隔（仅显示）"},
}

REPRO_PARAM_SCHEMAS: dict[str, dict[str, dict[str, Any]]] = {
    "nanogpt": NANOGPT_PARAM_SCHEMA,
}

# 预置环境声明（preset 声明值，非探测值；来源标注 declared）。
PRESET_ENVIRONMENTS: dict[str, dict[str, Any]] = {
    "nanogpt": {
        "executor": "repro-worker",
        "compute": "cpu",
        "torch": "preinstalled-cpu",
        "worker_timeout_s": 900,
        "source": "preset-declared",
    },
}

# v1 唯一支持的数据配置（切换数据属后续批次；非默认值 422）。
NANOGPT_DEFAULT_DATA: dict[str, Any] = {"dataset": "shakespeare_char", "source": "prepare.py"}


class ProposalError(Exception):
    """提案域失败：携带机器可读 code（fail-closed 语义）。"""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


def validate_parameters(preset_id: str, parameters: dict[str, Any] | None) -> dict[str, Any]:
    """校验并归一化参数：未知字段/非法类型/越界一律拒绝（422 类错误码）。"""
    schema = REPRO_PARAM_SCHEMAS.get(preset_id.strip().lower())
    if schema is None:
        raise ProposalError("PROPOSAL_PRESET_UNSUPPORTED", f"该预设暂不支持参数化：{preset_id}")
    parameters = parameters or {}
    unknown = sorted(set(parameters) - set(schema))
    if unknown:
        raise ProposalError("PROPOSAL_PARAM_UNKNOWN", f"不支持的参数：{', '.join(unknown)}")
    normalized: dict[str, Any] = {}
    for name, spec in schema.items():
        raw = parameters.get(name, spec["default"])
        if spec["type"] == "int":
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                raise ProposalError("PROPOSAL_PARAM_TYPE", f"参数 {name} 须为整数")
            if isinstance(raw, float) and not raw.is_integer():
                raise ProposalError("PROPOSAL_PARAM_TYPE", f"参数 {name} 须为整数")
            value: Any = int(raw)
        elif spec["type"] == "float":
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                raise ProposalError("PROPOSAL_PARAM_TYPE", f"参数 {name} 须为数值")
            value = float(raw)
        else:  # pragma: no cover - 防御分支，schema 仅 int/float
            raise ProposalError("PROPOSAL_PARAM_TYPE", f"参数 {name} 类型未支持")
        if not (spec["min"] <= value <= spec["max"]):
            raise ProposalError(
                "PROPOSAL_PARAM_OUT_OF_RANGE",
                f"参数 {name} 超出范围 [{spec['min']}, {spec['max']}]",
            )
        normalized[name] = value
    return normalized


def compile_nanogpt_steps(parameters: dict[str, Any]) -> list[str]:
    """由参数确定性生成冻结命令（固定顺序/格式）。

    lr_decay_iters 跟随 max_iters，但必须大于 train.py 默认 warmup_iters=100，
    否则 get_lr 除零（线上 E2E 实证：max_iters=100 + decay=100 必炸）。
    取 max(max_iters, 101)——默认值 2000 不受影响（与预设命令逐字一致）。
    """
    p = parameters
    lr_decay_iters = max(int(p["max_iters"]), 101)
    # ckpt 只在 iter % eval_interval == 0 时写盘：钳到 <= max_iters，
    # 否则小步数运行无 ckpt 可采样。等于默认值 2000 时不拼 flag，
    # 保持默认编译与预设命令逐字一致。
    eval_iv = min(int(p["eval_interval"]), int(p["max_iters"]))
    eval_flag = "" if eval_iv == 2000 else f" --eval_interval={eval_iv}"
    return [
        "git clone https://github.com/karpathy/nanoGPT && cd nanoGPT",
        "pip install numpy transformers datasets tiktoken tqdm "
        "--index-url https://pypi.tuna.tsinghua.edu.cn/simple",
        "python data/shakespeare_char/prepare.py",
        "python train.py config/train_shakespeare_char.py --device=cpu --compile=False "
        f"--eval_iters={p['eval_iters']} --log_interval={p['log_interval']} "
        f"--block_size={p['block_size']} --batch_size={p['batch_size']} "
        f"--n_layer={p['n_layer']} --n_head={p['n_head']} --n_embd={p['n_embd']} "
        f"--max_iters={p['max_iters']} "
        f"--lr_decay_iters={lr_decay_iters} --dropout={p['dropout']}{eval_flag}",
        "python sample.py --out_dir=out-shakespeare-char --device=cpu",
    ]


def compile_steps(preset_id: str, parameters: dict[str, Any]) -> list[str]:
    """按预设分发确定性编译；未知预设抛错（调用方转 422）。"""
    if preset_id.strip().lower() == "nanogpt":
        return compile_nanogpt_steps(parameters)
    raise ProposalError("PROPOSAL_PRESET_UNSUPPORTED", f"该预设暂不支持参数化：{preset_id}")


def default_environment(preset_id: str) -> dict[str, Any]:
    env = PRESET_ENVIRONMENTS.get(preset_id.strip().lower())
    if env is None:
        raise ProposalError("PROPOSAL_PRESET_UNSUPPORTED", f"该预设暂无环境声明：{preset_id}")
    return dict(env)


def resolve_metric_policy(
    preset: dict[str, Any], parameters: dict[str, Any], data: dict[str, Any]
) -> dict[str, Any]:
    """判定指标基线：仅全默认参数＋默认数据/环境才继承已验证基线。

    任何偏离 → exploratory（有实测、无 PASS 宣称）；模型不得自填容差
    （容差只来自预设声明，exploratory 下 expected_metrics 为空）。
    """
    schema = REPRO_PARAM_SCHEMAS.get(str(preset.get("preset_id", "")).lower(), {})
    sensitive_changed = [
        name for name, spec in schema.items()
        if spec.get("metric_sensitive") and parameters.get(name) != spec.get("default")
    ]
    # v1 仅 nanogpt 有数据概念且只接受默认值；其他预设无数据维度。
    data_changed = (
        str(preset.get("preset_id", "")).lower() == "nanogpt"
        and (data or {}) != NANOGPT_DEFAULT_DATA
    )
    if not sensitive_changed and not data_changed:
        return {
            "basis": "verified",
            "expected_metrics": preset.get("expected_metrics") or {},
            "source": preset.get("expected_metrics_source", ""),
        }
    reasons = []
    if sensitive_changed:
        reasons.append(f"参数偏离默认：{', '.join(sorted(sensitive_changed))}")
    if data_changed:
        reasons.append("数据配置偏离默认")
    return {
        "basis": "exploratory",
        "expected_metrics": {},
        "source": "",
        "reason": "；".join(reasons),
    }


def proposal_hash_for(body: dict[str, Any]) -> str:
    """提案 hash：覆盖 preset/repo/revision/环境/数据/参数/步骤/预算/指标策略。

    标题、备注属非执行元数据，不入 hash（改名不使批准失效）。
    自主提案（kind=autonomous_experiment）不走此函数，见 scope_hash_for。
    """
    canonical = {
        "preset_id": body.get("preset_id", ""),
        "repo_url": body.get("repo_url", ""),
        "repo_revision": body.get("repo_revision", ""),
        "revision_status": body.get("revision_status", ""),
        "environment": body.get("environment", {}),
        "data": body.get("data", {}),
        "parameters": body.get("parameters", {}),
        "steps": list(body.get("steps") or []),
        "budget": body.get("budget", {}),
        "metric_policy": body.get("metric_policy", {}),
    }
    raw = json.dumps(canonical, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def scope_hash_for(scope: dict[str, Any]) -> str:
    """自主 scope hash：一次确认授权的目标/数据-访问/资源范围指纹。

    覆盖 objective/repo_url/repo_revision/source_refs/data_refs/
    network_profile/resources/mode/allow_environment_repair——实际安装命令、
    依赖版本变化写 attempt，不回写此 hash（任务书 §2）。attempt 排错不消耗
    新批准；此处任一字段变化即新 hash，旧批准失效。
    """
    canonical = {
        "objective": scope.get("objective", ""),
        "repo_url": scope.get("repo_url", ""),
        "repo_revision": scope.get("repo_revision", ""),
        "source_refs": list(scope.get("source_refs") or []),
        "data_refs": list(scope.get("data_refs") or []),
        "network_profile": scope.get("network_profile", ""),
        "resources": scope.get("resources", {}),
        "mode": scope.get("mode", ""),
        "allow_environment_repair": bool(scope.get("allow_environment_repair", True)),
    }
    raw = json.dumps(canonical, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def validate_autonomous_scope(scope: dict[str, Any] | None) -> dict[str, Any]:
    """校验自主 scope：经 ExperimentScope 强校验归一化（任务书 §2 原样）。

    失败抛 ProposalError（PROPOSAL_SCOPE_INVALID，调用方转 422）。
    """
    from nexus.experiment_contracts import ExperimentScope

    if not isinstance(scope, dict) or not scope:
        raise ProposalError("PROPOSAL_SCOPE_INVALID", "自主提案须提供 scope")
    try:
        normalized = ExperimentScope.model_validate(scope)
    except Exception as error:  # noqa: BLE001 - pydantic ValidationError 转域错误
        raise ProposalError("PROPOSAL_SCOPE_INVALID", f"scope 非法：{error}") from error
    return normalized.model_dump()


def budget_for_scope(scope: dict[str, Any]) -> dict[str, Any]:
    """自主提案预算快照（审批卡展示＋绑定：资源/最长时间）。"""
    resources = scope.get("resources") or {}
    wall_time_s = int(resources.get("wall_time_s") or 0)
    return {
        "estimated_minutes": max(1, (wall_time_s + 59) // 60) if wall_time_s else 0,
        "max_steps": 0,
        "cpu_friendly": True,
        "resources": resources,
    }


def budget_for_proposal(preset: dict[str, Any]) -> dict[str, Any]:
    """提案预算快照（展示＋绑定；与审批预算同源口径）。"""
    return {
        "estimated_minutes": preset.get("estimated_minutes"),
        "max_steps": len(list(preset.get("steps") or [])),
        "cpu_friendly": bool(preset.get("cpu_friendly", True)),
    }


def _row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    out = {
        "proposal_id": row["proposal_id"],
        "user_id": row["user_id"],
        "session_id": row["session_id"],
        "version": row["version"],
        "kind": row.get("kind", PROPOSAL_KIND_PRESET) or PROPOSAL_KIND_PRESET,
        "preset_id": row["preset_id"],
        "parent_run_id": row.get("parent_run_id", ""),
        "objective": row.get("objective", ""),
        "parameters": row["parameters"],
        "environment": row["environment"],
        "repo_revision": row.get("repo_revision", ""),
        "revision_status": row.get("revision_status", ""),
        "data": row["data"],
        "steps": row["steps"],
        "budget": row["budget"],
        "metric_policy": row["metric_policy"],
        "plan_hash": row["plan_hash"],
        # T2：自主 scope 与授权 hash（preset 行缺省空；plan_hash 即 scope_hash）。
        "scope": row.get("scope", {}),
        "scope_hash": row.get("scope_hash", "") or "",
        "status": row["status"],
        "client_request_id": row.get("client_request_id", ""),
        "history": row.get("history", []),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    return out


def _loads(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return {}
    return value if value is not None else {}


def _row_from_pg(found: Any) -> dict[str, Any]:
    keys = ("proposal_id", "user_id", "session_id", "version", "kind", "preset_id",
            "parent_run_id", "objective", "parameters", "environment",
            "repo_revision", "revision_status", "data", "steps", "budget",
            "metric_policy", "plan_hash", "scope", "scope_hash", "status",
            "client_request_id", "history", "created_at", "updated_at")
    row = dict(zip(keys, found))
    for k in ("parameters", "environment", "data", "steps", "budget", "metric_policy",
              "scope", "history"):
        row[k] = _loads(row[k])
    if not isinstance(row["history"], list):
        row["history"] = []
    if not isinstance(row.get("scope"), dict):
        row["scope"] = {}
    # 老行（迁移前写入）无 kind 列值 → 归一 preset。
    if row.get("kind") not in PROPOSAL_KINDS:
        row["kind"] = PROPOSAL_KIND_PRESET
    return _row_to_dict(row)


PROPOSALS_DDL = """
CREATE SCHEMA IF NOT EXISTS {schema};
CREATE TABLE IF NOT EXISTS {schema}.nexus_proposals (
    proposal_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT '',
    session_id TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL DEFAULT 1,
    kind TEXT NOT NULL DEFAULT 'preset',
    preset_id TEXT NOT NULL DEFAULT '',
    parent_run_id TEXT NOT NULL DEFAULT '',
    objective TEXT NOT NULL DEFAULT '',
    parameters JSONB NOT NULL DEFAULT '{{}}',
    environment JSONB NOT NULL DEFAULT '{{}}',
    repo_revision TEXT NOT NULL DEFAULT '',
    revision_status TEXT NOT NULL DEFAULT '',
    data JSONB NOT NULL DEFAULT '{{}}',
    steps JSONB NOT NULL DEFAULT '[]',
    budget JSONB NOT NULL DEFAULT '{{}}',
    metric_policy JSONB NOT NULL DEFAULT '{{}}',
    plan_hash TEXT NOT NULL DEFAULT '',
    scope JSONB NOT NULL DEFAULT '{{}}',
    scope_hash TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    client_request_id TEXT NOT NULL DEFAULT '',
    history JSONB NOT NULL DEFAULT '[]',
    created_at DOUBLE PRECISION NOT NULL DEFAULT 0,
    updated_at DOUBLE PRECISION NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_nexus_proposals_user_session
    ON {schema}.nexus_proposals (user_id, session_id, updated_at DESC);
"""


def _pg_settings() -> tuple[str, str] | None:
    from nexus.config import get_settings

    settings = get_settings()
    dsn = settings.postgres_dsn.strip()
    if not dsn:
        return None
    return dsn, settings.postgres_schema


def ensure_proposals_table(dsn: str, schema: str) -> None:
    """幂等建表＋T2 列补齐（老表逐列 ADD COLUMN IF NOT EXISTS，可重入）。

    与 approvals.ensure_approvals_table 同模式：新列只追加、有默认值，
    旧代码忽略新列（回退见验收记录）。
    """
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(PROPOSALS_DDL.format(schema=schema))
            for column, ddl in (
                ("kind", "TEXT NOT NULL DEFAULT 'preset'"),
                ("scope", "JSONB NOT NULL DEFAULT '{}'"),
                ("scope_hash", "TEXT NOT NULL DEFAULT ''"),
            ):
                cur.execute(
                    f"ALTER TABLE {schema}.nexus_proposals "
                    f"ADD COLUMN IF NOT EXISTS {column} {ddl}"
                )


def _build_body(
    *, preset: dict[str, Any], parent_run: dict[str, Any] | None,
    objective: str, parameters: dict[str, Any] | None, data: dict[str, Any] | None,
) -> dict[str, Any]:
    preset_id = str(preset.get("preset_id", ""))
    normalized = validate_parameters(preset_id, parameters)
    data = dict(data) if data else dict(NANOGPT_DEFAULT_DATA)
    if preset_id.strip().lower() == "nanogpt" and data != NANOGPT_DEFAULT_DATA:
        raise ProposalError("PROPOSAL_DATA_UNSUPPORTED", "首版仅支持默认数据集配置")
    steps = compile_steps(preset_id, normalized)
    metric_policy = resolve_metric_policy(preset, normalized, data)
    body = {
        "preset_id": preset_id,
        "repo_url": preset.get("repo_url", ""),
        "repo_revision": str(preset.get("repo_revision", "")),
        "revision_status": ("resolved" if preset.get("repo_revision") else "unresolved-seed-snapshot"),
        "environment": default_environment(preset_id),
        "data": data,
        "parameters": normalized,
        "steps": steps,
        "budget": budget_for_proposal(preset),
        "metric_policy": metric_policy,
    }
    body["plan_hash"] = proposal_hash_for(body)
    return body


def _history_entry(row: dict[str, Any]) -> dict[str, Any]:
    """版本历史条目（最近 10 版，供上一版本 diff；完整审计靠行快照）。"""
    return {
        "version": row["version"],
        "plan_hash": row["plan_hash"],
        "parameters": row["parameters"],
        "steps": row["steps"],
        "metric_basis": (row["metric_policy"] or {}).get("basis", ""),
        "scope_hash": row.get("scope_hash", ""),
        "updated_at": row["updated_at"],
    }


def create_proposal(
    *, user_id: str, session_id: str, preset: dict[str, Any] | None = None,
    parent_run: dict[str, Any] | None = None,
    objective: str = "", parameters: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None, client_request_id: str = "",
    kind: str = PROPOSAL_KIND_PRESET, scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """建草案（不执行）。client_request_id 幂等：同用户重复请求返原草案。

    kind 缺省 preset（旧语义不变）；kind=autonomous_experiment 时消费
    ExperimentScope，不要求 preset（preset 须为 None），plan_hash 即
    scope_hash，steps 为空（实际命令写 attempt，不冻结初始命令）。
    """
    now = _now()
    kind = (kind or PROPOSAL_KIND_PRESET).strip()
    if kind not in PROPOSAL_KINDS:
        raise ProposalError("PROPOSAL_KIND_UNSUPPORTED", f"不支持的提案类型：{kind}")
    client_request_id = (client_request_id or "").strip()[:64]
    if client_request_id:
        existing = get_proposal_by_client_request(user_id, client_request_id)
        if existing is not None:
            return {**existing, "deduped": True}
    if kind == PROPOSAL_KIND_AUTONOMOUS:
        if preset is not None:
            raise ProposalError("PROPOSAL_KIND_MISMATCH", "自主提案不接受 preset")
        normalized_scope = validate_autonomous_scope(scope)
        scope_hash = scope_hash_for(normalized_scope)
        row = {
            "proposal_id": new_proposal_id(),
            "user_id": user_id or "",
            "session_id": session_id or "",
            "version": 1,
            "kind": PROPOSAL_KIND_AUTONOMOUS,
            "preset_id": "",
            "parent_run_id": str((parent_run or {}).get("run_id", "")),
            "objective": normalized_scope["objective"].strip()[:500],
            "parameters": {},
            "environment": {},
            "repo_revision": normalized_scope["repo_revision"],
            "revision_status": "proposed",
            "data": {"data_refs": normalized_scope["data_refs"],
                     "source_refs": normalized_scope["source_refs"]},
            "steps": [],
            "budget": budget_for_scope(normalized_scope),
            "metric_policy": {"basis": "not_evaluated",
                              "mode": normalized_scope["mode"]},
            "plan_hash": scope_hash,
            "scope": normalized_scope,
            "scope_hash": scope_hash,
            "status": "draft",
            "client_request_id": client_request_id,
            "history": [],
            "created_at": now,
            "updated_at": now,
        }
        row["history"] = [_history_entry(row)]
        _insert_row(row)
        return _row_to_dict(row)
    if preset is None:
        raise ProposalError("PROPOSAL_PRESET_UNSUPPORTED", "该预设暂不支持参数化")
    body = _build_body(preset=preset, parent_run=parent_run, objective=objective,
                       parameters=parameters, data=data)
    row = {
        "proposal_id": new_proposal_id(),
        "user_id": user_id or "",
        "session_id": session_id or "",
        "version": 1,
        "kind": PROPOSAL_KIND_PRESET,
        "preset_id": body["preset_id"],
        "parent_run_id": str((parent_run or {}).get("run_id", "")),
        "objective": (objective or "").strip()[:500],
        "parameters": body["parameters"],
        "environment": body["environment"],
        "repo_revision": body["repo_revision"],
        "revision_status": body["revision_status"],
        "data": body["data"],
        "steps": body["steps"],
        "budget": body["budget"],
        "metric_policy": body["metric_policy"],
        "plan_hash": body["plan_hash"],
        "scope": {},
        "scope_hash": "",
        "status": "draft",
        "client_request_id": client_request_id,
        "history": [],
        "created_at": now,
        "updated_at": now,
    }
    row["history"] = [_history_entry({**row, "parameters": body["parameters"],
                                      "steps": body["steps"],
                                      "metric_policy": body["metric_policy"]})]
    _insert_row(row)
    return _row_to_dict(row)


def _insert_row(row: dict[str, Any]) -> None:
    """插入整行（PG 可用进 PG，异常回退内存；与旧 create 路径同失败语义）。"""
    pg = _pg_settings()
    if pg is not None:
        dsn, schema = pg
        try:
            ensure_proposals_table(dsn, schema)
            import psycopg

            with psycopg.connect(dsn, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"INSERT INTO {schema}.nexus_proposals "
                        "(proposal_id, user_id, session_id, version, kind, preset_id, "
                        "parent_run_id, objective, parameters, environment, "
                        "repo_revision, revision_status, data, steps, budget, "
                        "metric_policy, plan_hash, scope, scope_hash, status, "
                        "client_request_id, history, created_at, updated_at) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (
                            row["proposal_id"], row["user_id"], row["session_id"],
                            row["version"], row["kind"], row["preset_id"],
                            row["parent_run_id"], row["objective"],
                            json.dumps(row["parameters"], ensure_ascii=False),
                            json.dumps(row["environment"], ensure_ascii=False),
                            row["repo_revision"], row["revision_status"],
                            json.dumps(row["data"], ensure_ascii=False),
                            json.dumps(row["steps"], ensure_ascii=False),
                            json.dumps(row["budget"], ensure_ascii=False),
                            json.dumps(row["metric_policy"], ensure_ascii=False),
                            row["plan_hash"],
                            json.dumps(row.get("scope", {}), ensure_ascii=False),
                            row.get("scope_hash", ""),
                            row["status"], row["client_request_id"],
                            json.dumps(row["history"], ensure_ascii=False),
                            row["created_at"], row["updated_at"],
                        ),
                    )
            return
        except Exception as error:  # noqa: BLE001
            logger.warning("proposal pg insert failed, memory fallback: %s", error)
    _memory_proposals[row["proposal_id"]] = {k: (dict(v) if isinstance(v, dict) else list(v) if isinstance(v, list) else v) for k, v in row.items()}


_PROPOSAL_SELECT = (
    "proposal_id, user_id, session_id, version, kind, preset_id, "
    "parent_run_id, objective, parameters, environment, "
    "repo_revision, revision_status, data, steps, budget, "
    "metric_policy, plan_hash, scope, scope_hash, status, client_request_id, "
    "history, created_at, updated_at"
)


def get_proposal(proposal_id: str) -> dict[str, Any] | None:
    """读提案（归属由调用方/端点校验；此处不做 user 过滤）。"""
    pg = _pg_settings()
    if pg is not None:
        dsn, schema = pg
        try:
            import psycopg

            with psycopg.connect(dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT {_PROPOSAL_SELECT} "
                        f"FROM {schema}.nexus_proposals WHERE proposal_id = %s",
                        (proposal_id,),
                    )
                    found = cur.fetchone()
            if found is not None:
                return _row_from_pg(found)
        except Exception as error:  # noqa: BLE001
            logger.warning("proposal pg read failed: %s", error)
    stored = _memory_proposals.get(proposal_id)
    return _row_to_dict(dict(stored)) if stored is not None else None


def get_proposal_by_client_request(user_id: str, client_request_id: str) -> dict[str, Any] | None:
    """幂等键查询（仅 draft 可复用；已终态草案不复用，各自是独立提案）。"""
    if not client_request_id:
        return None
    pg = _pg_settings()
    if pg is not None:
        dsn, schema = pg
        try:
            import psycopg

            with psycopg.connect(dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT {_PROPOSAL_SELECT} "
                        f"FROM {schema}.nexus_proposals "
                        f"WHERE user_id = %s AND client_request_id = %s AND status = 'draft' "
                        f"ORDER BY updated_at DESC LIMIT 1",
                        (user_id or "", client_request_id),
                    )
                    found = cur.fetchone()
            if found is not None:
                return _row_from_pg(found)
        except Exception as error:  # noqa: BLE001
            logger.warning("proposal pg dedupe read failed: %s", error)
    for stored in _memory_proposals.values():
        if (stored.get("user_id") == (user_id or "")
                and stored.get("client_request_id") == client_request_id
                and stored.get("status") == "draft"):
            return _row_to_dict(dict(stored))
    return None


def _persist_row(row: dict[str, Any]) -> None:
    """写回整行（PG 按 proposal_id 更新；内存直接替换）。"""
    pg = _pg_settings()
    if pg is not None:
        dsn, schema = pg
        import psycopg

        with psycopg.connect(dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE {schema}.nexus_proposals SET version=%s, objective=%s, "
                    f"parameters=%s, steps=%s, metric_policy=%s, plan_hash=%s, "
                    f"scope=%s, scope_hash=%s, "
                    f"status=%s, history=%s, updated_at=%s WHERE proposal_id=%s",
                    (
                        row["version"], row["objective"],
                        json.dumps(row["parameters"], ensure_ascii=False),
                        json.dumps(row["steps"], ensure_ascii=False),
                        json.dumps(row["metric_policy"], ensure_ascii=False),
                        row["plan_hash"],
                        json.dumps(row.get("scope", {}), ensure_ascii=False),
                        row.get("scope_hash", ""),
                        row["status"],
                        json.dumps(row["history"], ensure_ascii=False),
                        row["updated_at"],
                        row["proposal_id"],
                    ),
                )
        return
    if row["proposal_id"] in _memory_proposals:
        _memory_proposals[row["proposal_id"]] = dict(row)


def proposal_diff(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """两版本结构化 diff：参数变更明细/步骤变化/基线变化/hash 变化/scope 变化。"""
    old_params, new_params = old.get("parameters", {}), new.get("parameters", {})
    changed = [
        {"name": name, "old": old_params.get(name), "new": new_params.get(name)}
        for name in sorted(set(old_params) | set(new_params))
        if old_params.get(name) != new_params.get(name)
    ]
    return {
        "from_version": old.get("version"),
        "to_version": new.get("version"),
        "parameters_changed": changed,
        "steps_changed": list(old.get("steps") or []) != list(new.get("steps") or []),
        "metric_basis_changed": (old.get("metric_policy") or {}).get("basis")
        != (new.get("metric_policy") or {}).get("basis"),
        "objective_changed": (old.get("objective") or "") != (new.get("objective") or ""),
        "plan_hash_changed": old.get("plan_hash") != new.get("plan_hash"),
        "scope_changed": (old.get("scope") or {}) != (new.get("scope") or {}),
    }


def patch_proposal(
    proposal_id: str, *, user_id: str, expected_version: int,
    objective: str | None = None, parameters: dict[str, Any] | None = None,
    scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """改提案：版本乐观锁（冲突 409 类错误）；仅 draft 可改；改后旧批准自然失效。

    preset 提案：objective/parameters（全量语义，缺省回默认值）；
    自主提案：objective/scope（parameters 传非空拒绝，scope 重校验重算 hash）。
    未传的键保持原值。返回 {"proposal": 行, "diff": 结构化差异}。
    """
    from nexus.tools.reproduction import REPRO_PRESETS

    current = get_proposal(proposal_id)
    if current is None:
        raise ProposalError("PROPOSAL_NOT_FOUND", "提案不存在或已不可恢复")
    if (user_id or "") != current["user_id"]:
        raise ProposalError("PROPOSAL_FORBIDDEN", "无权修改他人的提案")
    if current["status"] != "draft":
        raise ProposalError(
            "PROPOSAL_LOCKED",
            f"提案已{current['status']}，不可直接修改；请基于执行结果创建新提案",
        )
    if int(expected_version) != int(current["version"]):
        raise ProposalError(
            "PROPOSAL_VERSION_CONFLICT",
            f"版本冲突：当前版本={current['version']}",
        )
    kind = current.get("kind", PROPOSAL_KIND_PRESET) or PROPOSAL_KIND_PRESET
    if kind == PROPOSAL_KIND_AUTONOMOUS:
        if parameters:
            raise ProposalError("PROPOSAL_PARAM_UNKNOWN", "自主提案不支持 parameters")
        new_objective = current["objective"] if objective is None else objective
        new_scope = dict(current.get("scope") or {})
        if scope is not None:
            merged = {**new_scope, **scope}
            new_scope = validate_autonomous_scope(merged)
        new_hash = scope_hash_for(new_scope)
        updated = dict(current)
        updated.update({
            "version": int(current["version"]) + 1,
            "objective": (new_objective or "").strip()[:500],
            "repo_revision": new_scope.get("repo_revision", ""),
            "data": {"data_refs": new_scope.get("data_refs", []),
                     "source_refs": new_scope.get("source_refs", [])},
            "budget": budget_for_scope(new_scope),
            "metric_policy": {"basis": "not_evaluated",
                              "mode": new_scope.get("mode", "")},
            "plan_hash": new_hash,
            "scope": new_scope,
            "scope_hash": new_hash,
            "updated_at": _now(),
        })
        history = list(current.get("history") or [])
        history.append(_history_entry(updated))
        updated["history"] = history[-10:]
        diff = proposal_diff(current, updated)
        try:
            _persist_row(updated)
        except Exception as error:  # noqa: BLE001
            raise ProposalError("PROPOSAL_PERSIST_FAILED", f"提案保存失败：{type(error).__name__}") from error
        _memory_proposals[updated["proposal_id"]] = dict(updated)
        return {"proposal": _row_to_dict(updated), "diff": diff}
    if scope is not None:
        raise ProposalError("PROPOSAL_KIND_MISMATCH", "preset 提案不接受 scope")
    preset = REPRO_PRESETS.get(str(current["preset_id"]).lower())
    if preset is None:
        raise ProposalError("PROPOSAL_PRESET_UNSUPPORTED", "预设已不可用")
    new_objective = current["objective"] if objective is None else objective
    # parameters 语义：传增量（与创建时的全量一致）；以当前值为底合并后校验。
    raw_params = dict(current["parameters"])
    if parameters is not None:
        raw_params.update(parameters)
    normalized = validate_parameters(current["preset_id"], raw_params)
    # data 沿用创建时值（v1 仅默认数据）。
    body = _build_body(preset=preset, parent_run=None,
                       objective=new_objective, parameters=normalized,
                       data=dict(current["data"]))
    updated = dict(current)
    updated.update({
        "version": int(current["version"]) + 1,
        "objective": (new_objective or "").strip()[:500],
        "parameters": normalized,
        "steps": body["steps"],
        "metric_policy": body["metric_policy"],
        "plan_hash": body["plan_hash"],
        "updated_at": _now(),
    })
    history = list(current.get("history") or [])
    history.append(_history_entry({**updated, "parameters": normalized,
                                   "steps": body["steps"],
                                   "metric_policy": body["metric_policy"]}))
    updated["history"] = history[-10:]
    diff = proposal_diff(current, updated)
    try:
        _persist_row(updated)
    except Exception as error:  # noqa: BLE001
        raise ProposalError("PROPOSAL_PERSIST_FAILED", f"提案保存失败：{type(error).__name__}") from error
    # 内存路径下 _persist_row 静默跳过不存在的行——此处行必存在，直接同步。
    _memory_proposals[updated["proposal_id"]] = dict(updated)
    return {"proposal": _row_to_dict(updated), "diff": diff}


def mark_proposal_executed(proposal_id: str, version: int) -> bool:
    """执行成功后冻结提案版本（best-effort；后续修改须走新提案）。

    行仍为该版本且状态为 draft（直批兼容）或 approved（核销锁定）时转换；
    返回是否成功标记。
    """
    current = get_proposal(proposal_id)
    if current is None:
        return False
    if int(current["version"]) != int(version) or current["status"] not in ("draft", "approved"):
        return False
    current["status"] = "executed"
    current["updated_at"] = _now()
    try:
        _persist_row(current)
    except Exception as error:  # noqa: BLE001
        logger.warning("mark proposal executed failed: %s", error)
        return False
    _memory_proposals[current["proposal_id"]] = dict(current)
    return True


_LOCK_SELECT = _PROPOSAL_SELECT


def lock_proposal_for_execution(
    proposal_id: str, *, user_id: str, expected_version: int, expected_hash: str,
) -> dict[str, Any] | None:
    """NX-N0/P1-A：核销时 CAS 锁定提案（draft→approved），返回锁定后行。

    版本＋hash＋归属＋draft 四重匹配才转换；任何失配返回 None（调用方按
    旧批准失效拒绝——核验与锁定之间被修改即落入此分支）。内存路径单进程
    check-set；PG 路径单条 UPDATE ... WHERE ... RETURNING 原子转换。
    PG 异常 fail-closed 返回 None（不回退内存，避免双写脑裂）。
    """
    pg = _pg_settings()
    if pg is not None:
        dsn, schema = pg
        try:
            import psycopg

            with psycopg.connect(dsn, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"UPDATE {schema}.nexus_proposals SET status='approved', updated_at=%s "
                        f"WHERE proposal_id=%s AND user_id=%s AND version=%s "
                        f"AND plan_hash=%s AND status='draft' "
                        f"RETURNING {_LOCK_SELECT}",
                        (_now(), proposal_id, user_id or "",
                         int(expected_version), expected_hash or ""),
                    )
                    found = cur.fetchone()
            if found is None:
                return None
            return _row_from_pg(found)
        except Exception as error:  # noqa: BLE001
            logger.warning("proposal lock pg failed: %s", error)
            return None
    row = _memory_proposals.get(proposal_id)
    if row is None:
        return None
    if ((row.get("user_id") or "") != (user_id or "")
            or int(row.get("version", 0)) != int(expected_version)
            or (row.get("plan_hash") or "") != (expected_hash or "")
            or row.get("status") != "draft"):
        return None
    row = dict(row)
    row["status"] = "approved"
    row["updated_at"] = _now()
    _memory_proposals[proposal_id] = row
    return _row_to_dict(row)


def clear_memory_store() -> None:
    """测试隔离：清空内存提案（PG 行不受影响，测试不用真实 PG）。"""
    _memory_proposals.clear()


def request_approval_for_proposal(
    proposal_id: str, *, user_id: str, expected_version: int,
) -> dict[str, Any]:
    """NX-LB4 共享核心：pin 住版本+hash 生成/复用审批（不直接执行）。

    main.py 的 HTTP 端点与工具路径（request_reproduction_approval）共用；
    成功返回 {"approval": 公开投影, "deduped": 是否复用同版本待办}，
    失败抛 ProposalError（NOT_FOUND/FORBIDDEN/LOCKED/VERSION_CONFLICT/
    PRESET_UNSUPPORTED）。模型只准备执行材料，批准永远由用户发起。
    """
    from nexus import approvals
    from nexus.tools.reproduction import _approval_ttl_s, _public_approval

    row = get_proposal(proposal_id)
    if row is None or (user_id or "") != row["user_id"]:
        raise ProposalError("PROPOSAL_NOT_FOUND", "提案不存在或不可恢复")
    if row["status"] != "draft":
        raise ProposalError(
            "PROPOSAL_LOCKED", f"提案已{row['status']}，不可请求审批")
    if int(row["version"]) != int(expected_version):
        raise ProposalError(
            "PROPOSAL_VERSION_CONFLICT",
            f"版本冲突：当前版本={row['version']}",
        )
    kind = row.get("kind", PROPOSAL_KIND_PRESET) or PROPOSAL_KIND_PRESET
    if kind == PROPOSAL_KIND_AUTONOMOUS:
        # 自主提案：幂等（同版本 pending 复用）＋绑定 scope_hash/冻结 scope。
        for approval in approvals.list_approvals(
                user_id=user_id, status="pending", session_id=row["session_id"]):
            if (approval.get("proposal_id") == row["proposal_id"]
                    and int(approval.get("proposal_version", 0)) == int(row["version"])):
                return {"approval": _public_approval(approval, None), "deduped": True}
        try:
            created = approvals.create_approval(
                user_id=user_id, session_id=row["session_id"],
                tool="run_reproduction", preset={}, ttl_s=_approval_ttl_s(),
                proposal_binding={
                    "proposal_id": row["proposal_id"],
                    "proposal_version": row["version"],
                    "proposal_hash": row["scope_hash"],
                    "proposal_kind": PROPOSAL_KIND_AUTONOMOUS,
                    "scope_hash": row["scope_hash"],
                    "frozen_steps": [],
                    "frozen_scope": dict(row.get("scope") or {}),
                },
            )
        except Exception as error:  # noqa: BLE001
            raise ProposalError(
                "PROPOSAL_APPROVAL_CREATE_FAILED",
                f"审批创建失败：{type(error).__name__}",
            ) from error
        return {"approval": _public_approval(created, None), "deduped": False}
    preset = _preset_for(row["preset_id"])
    if preset is None:
        raise ProposalError("PROPOSAL_PRESET_UNSUPPORTED", "预设已不可用")
    # 幂等：同版本已有 pending 审批则复用。
    for approval in approvals.list_approvals(
            user_id=user_id, status="pending", session_id=row["session_id"]):
        if (approval.get("proposal_id") == row["proposal_id"]
                and int(approval.get("proposal_version", 0)) == int(row["version"])):
            return {"approval": _public_approval(approval, preset), "deduped": True}
    try:
        created = approvals.create_approval(
            user_id=user_id, session_id=row["session_id"],
            tool="run_reproduction", preset=preset, ttl_s=_approval_ttl_s(),
            proposal_binding={
                "proposal_id": row["proposal_id"],
                "proposal_version": row["version"],
                "proposal_hash": row["plan_hash"],
                "frozen_steps": list(row["steps"]),
            },
        )
    except Exception as error:  # noqa: BLE001
        raise ProposalError(
            "PROPOSAL_APPROVAL_CREATE_FAILED",
            f"审批创建失败：{type(error).__name__}",
        ) from error
    return {"approval": _public_approval(created, preset), "deduped": False}


def _preset_for(preset_id: str) -> dict[str, Any] | None:
    from nexus.tools.reproduction import REPRO_PRESETS

    return REPRO_PRESETS.get(str(preset_id or "").strip().lower())


# ---------------------------------------------------------------------------
# NX-LB1：preset 可见投影（Backend /repro/presets 经内部 HTTP 拉取，不跨
# Python 环境 import）。只读：无凭据、内部路径、任意命令入口。
# ---------------------------------------------------------------------------


def preset_projection(preset_id: str) -> dict[str, Any] | None:
    """单个 preset 的公开投影；未知 id 返回 None（调用方 404）。"""
    from nexus.tools.reproduction import REPRO_PRESETS

    preset = REPRO_PRESETS.get(preset_id.strip().lower())
    if preset is None:
        return None
    schema = REPRO_PARAM_SCHEMAS.get(preset_id.strip().lower(), {})
    return {
        "preset_id": preset.get("preset_id", ""),
        "display_name": preset.get("display_name") or preset.get("preset_id", ""),
        "paper_title": preset.get("paper_title", ""),
        "repo_url": preset.get("repo_url", ""),
        "repo_license": preset.get("repo_license", ""),
        "repo_stars": preset.get("repo_stars"),
        "environment": default_environment(preset_id),
        "parameters": {
            "schema": schema,
            "defaults": {name: spec["default"] for name, spec in schema.items()},
        },
        "budget": budget_for_proposal(preset),
        "expected_metrics": preset.get("expected_metrics") or {},
        "expected_metrics_source": preset.get("expected_metrics_source", ""),
        "capability_limits": [
            "仅已核验仓库与固定命令集（或审核参数编译的命令）",
            "未知仓库/任意命令拒绝执行",
            "修改参数后无已验证基线时只出探索性结论，不宣称复现通过",
        ],
    }


def list_preset_projections() -> list[dict[str, Any]]:
    """全部可见 preset 投影（按 preset_id 排序，稳定顺序）。"""
    from nexus.tools.reproduction import REPRO_PRESETS

    out = []
    for preset_id in sorted(REPRO_PRESETS):
        projection = preset_projection(preset_id)
        if projection is not None:
            out.append(projection)
    return out


def public_proposal_view(row: dict[str, Any] | None) -> dict[str, Any] | None:
    """提案公开投影：完整方案＋校验结果（供浮窗/审阅展示，无内部令牌）。

    自主提案额外带 kind/scope/scope_hash（审批卡本身不展示 hash，见
    工具 _public_approval 的自主卡片投影）。
    """
    if row is None:
        return None
    view: dict[str, Any] = {
        "proposal_id": row["proposal_id"],
        "version": row["version"],
        "kind": row.get("kind", PROPOSAL_KIND_PRESET) or PROPOSAL_KIND_PRESET,
        "status": row["status"],
        "preset_id": row["preset_id"],
        "parent_run_id": row.get("parent_run_id", ""),
        "objective": row.get("objective", ""),
        "parameters": row["parameters"],
        "environment": row["environment"],
        "repo_revision": row.get("repo_revision", ""),
        "revision_status": row.get("revision_status", ""),
        "data": row["data"],
        "steps": row["steps"],
        "budget": row["budget"],
        "metric_policy": row["metric_policy"],
        "plan_hash": row["plan_hash"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    if view["kind"] == PROPOSAL_KIND_AUTONOMOUS:
        view["scope"] = row.get("scope", {})
        view["scope_hash"] = row.get("scope_hash", "")
    return view
