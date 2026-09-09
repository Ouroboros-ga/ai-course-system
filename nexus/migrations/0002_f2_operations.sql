-- 0002_f2_operations：F2 操作意图＋执行租约（持久执行基础）
--
-- 幂等：CREATE ... IF NOT EXISTS / ADD COLUMN IF NOT EXISTS，对既有库 no-op。
-- {schema} 由 scripts/apply_nexus_migrations.py 替换。
--
-- 回退说明（人工执行）：
--   DROP TABLE {schema}.nexus_execution_leases;
--   DROP TABLE {schema}.nexus_operation_intents;
--   DELETE FROM {schema}.nexus_schema_migrations WHERE version='0002_f2_operations';
-- 意图行是执行账本：回退前确认无 running run 依赖其对账，否则先停新实验。

CREATE SCHEMA IF NOT EXISTS {schema};

-- 操作意图：外部副作用前原子登记（stable operation_id＋请求哈希）。
-- Nexus 与控制服务各持己方持久状态，不直接写对方表。
CREATE TABLE IF NOT EXISTS {schema}.nexus_operation_intents (
    intent_key TEXT PRIMARY KEY,
    run_id TEXT NOT NULL DEFAULT '',
    operation_id TEXT NOT NULL DEFAULT '',
    seq INTEGER NOT NULL DEFAULT 0,
    request_hash TEXT NOT NULL DEFAULT '',
    command TEXT NOT NULL DEFAULT '',
    timeout_s DOUBLE PRECISION,
    op_type TEXT NOT NULL DEFAULT 'execute',
    status TEXT NOT NULL DEFAULT 'prepared',
    exit_code INTEGER,
    output_tail TEXT NOT NULL DEFAULT '',
    created_at DOUBLE PRECISION NOT NULL DEFAULT 0,
    updated_at DOUBLE PRECISION NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_nexus_operation_intents_run
    ON {schema}.nexus_operation_intents (run_id, seq);

-- 执行租约：单调 fencing token，防双恢复者同时接管。
-- 完成/取消/失败均释放；过期只允许接管观察权，接管者须先核对控制面/容器。
CREATE TABLE IF NOT EXISTS {schema}.nexus_execution_leases (
    run_id TEXT PRIMARY KEY,
    holder TEXT NOT NULL DEFAULT '',
    fencing TEXT NOT NULL DEFAULT '',
    expires_at DOUBLE PRECISION NOT NULL DEFAULT 0,
    updated_at DOUBLE PRECISION NOT NULL DEFAULT 0
);

-- run 恢复状态列（独立于 status；UI 可不消费新枚举，报告/控制台直通）。
ALTER TABLE {schema}.nexus_experiment_runs
    ADD COLUMN IF NOT EXISTS recovery_status TEXT NOT NULL DEFAULT '';
ALTER TABLE {schema}.nexus_experiment_runs
    ADD COLUMN IF NOT EXISTS completion_reason TEXT NOT NULL DEFAULT '';
