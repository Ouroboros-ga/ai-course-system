-- 0006_f8_compares：F8 受控 A/B 对照持久化
--
-- 幂等：CREATE ... IF NOT EXISTS，对既有库 no-op。
-- {schema} 由 scripts/apply_nexus_migrations.py 替换。
--
-- 回退说明（人工执行）：
--   DROP TABLE {schema}.nexus_compares;
--   DELETE FROM {schema}.nexus_schema_migrations WHERE version='0006_f8_compares';
-- 对照行是关联账本：回退前确认无 running 对照依赖其关联，否则先停新对照。

CREATE SCHEMA IF NOT EXISTS {schema};

-- 受控对照：对照说明（共同数据/指标/预算）＋两组冻结配方引用＋关联结果。
-- 只存关联与判定，不存执行过程；执行走既有批准/run 通道。
CREATE TABLE IF NOT EXISTS {schema}.nexus_compares (
    compare_id TEXT PRIMARY KEY,
    owner TEXT NOT NULL DEFAULT '',
    session_id TEXT NOT NULL DEFAULT '',
    objective TEXT NOT NULL DEFAULT '',
    common JSONB NOT NULL DEFAULT '{}',
    allowed_varied JSONB NOT NULL DEFAULT '[]',
    arms JSONB NOT NULL DEFAULT '[]',
    arm_results JSONB NOT NULL DEFAULT '{}',
    approval_ref TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    detail TEXT NOT NULL DEFAULT '',
    created_at DOUBLE PRECISION NOT NULL DEFAULT 0,
    updated_at DOUBLE PRECISION NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_nexus_compares_owner
    ON {schema}.nexus_compares (owner, updated_at DESC);
