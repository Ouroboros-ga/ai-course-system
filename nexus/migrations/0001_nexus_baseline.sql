-- 0001_nexus_baseline：Nexus 域基线（schema ＋ 5 张表 ＋ 全部增量列 ＋ 索引）
--
-- 幂等：所有语句都是 CREATE ... IF NOT EXISTS / ADD COLUMN IF NOT EXISTS，
-- 对既有线上库等价 no-op（表/列由历史启动 DDL 建出），对新库一次建齐。
-- {schema} 由 scripts/apply_nexus_migrations.py 用 NEXUS_POSTGRES_SCHEMA 替换。
--
-- 回退说明（人工执行，本文件为基线）：
--   DROP TABLE {schema}.nexus_session_prefs / nexus_experiment_runs /
--              nexus_approvals / nexus_proposals / nexus_threads;
--   并删除 ledger 行：DELETE FROM {schema}.nexus_schema_migrations WHERE version='0001_nexus_baseline';
-- 后续迁移必须另起编号文件，不得修改本文件（校验和会漂移并被 runner 拒绝）。

CREATE SCHEMA IF NOT EXISTS {schema};

-- 会话线程（P1-C：重启后同 thread 续聊）
CREATE TABLE IF NOT EXISTS {schema}.nexus_threads (
    thread_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT '',
    session_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE {schema}.nexus_threads
    ADD COLUMN IF NOT EXISTS title TEXT NOT NULL DEFAULT '';

-- 提案（NX-LB2 ＋ T2 kind/scope ＋ T7 license）
CREATE TABLE IF NOT EXISTS {schema}.nexus_proposals (
    proposal_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT '',
    session_id TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL DEFAULT 1,
    kind TEXT NOT NULL DEFAULT 'preset',
    preset_id TEXT NOT NULL DEFAULT '',
    parent_run_id TEXT NOT NULL DEFAULT '',
    objective TEXT NOT NULL DEFAULT '',
    parameters JSONB NOT NULL DEFAULT '{}',
    environment JSONB NOT NULL DEFAULT '{}',
    repo_revision TEXT NOT NULL DEFAULT '',
    revision_status TEXT NOT NULL DEFAULT '',
    data JSONB NOT NULL DEFAULT '{}',
    steps JSONB NOT NULL DEFAULT '[]',
    budget JSONB NOT NULL DEFAULT '{}',
    metric_policy JSONB NOT NULL DEFAULT '{}',
    plan_hash TEXT NOT NULL DEFAULT '',
    scope JSONB NOT NULL DEFAULT '{}',
    scope_hash TEXT NOT NULL DEFAULT '',
    license JSONB NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'draft',
    client_request_id TEXT NOT NULL DEFAULT '',
    history JSONB NOT NULL DEFAULT '[]',
    created_at DOUBLE PRECISION NOT NULL DEFAULT 0,
    updated_at DOUBLE PRECISION NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_nexus_proposals_user_session
    ON {schema}.nexus_proposals (user_id, session_id, updated_at DESC);
ALTER TABLE {schema}.nexus_proposals
    ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'preset';
ALTER TABLE {schema}.nexus_proposals
    ADD COLUMN IF NOT EXISTS scope JSONB NOT NULL DEFAULT '{}';
ALTER TABLE {schema}.nexus_proposals
    ADD COLUMN IF NOT EXISTS scope_hash TEXT NOT NULL DEFAULT '';
ALTER TABLE {schema}.nexus_proposals
    ADD COLUMN IF NOT EXISTS license JSONB NOT NULL DEFAULT '{}';

-- 审批（NX-LB2 提案绑定 ＋ T2 自主绑定 ＋ T7 冻结 License）
CREATE TABLE IF NOT EXISTS {schema}.nexus_approvals (
    approval_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT '',
    session_id TEXT NOT NULL DEFAULT '',
    tool TEXT NOT NULL DEFAULT '',
    preset_id TEXT NOT NULL DEFAULT '',
    plan_hash TEXT NOT NULL DEFAULT '',
    budget JSONB NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    job_id TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '',
    created_at DOUBLE PRECISION NOT NULL DEFAULT 0,
    expires_at DOUBLE PRECISION NOT NULL DEFAULT 0,
    proposal_kind TEXT NOT NULL DEFAULT '',
    scope_hash TEXT NOT NULL DEFAULT '',
    frozen_scope TEXT NOT NULL DEFAULT '{}',
    frozen_license TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_nexus_approvals_user
    ON {schema}.nexus_approvals (user_id, created_at DESC);
ALTER TABLE {schema}.nexus_approvals
    ADD COLUMN IF NOT EXISTS proposal_id TEXT NOT NULL DEFAULT '';
ALTER TABLE {schema}.nexus_approvals
    ADD COLUMN IF NOT EXISTS proposal_version INTEGER NOT NULL DEFAULT 0;
ALTER TABLE {schema}.nexus_approvals
    ADD COLUMN IF NOT EXISTS proposal_hash TEXT NOT NULL DEFAULT '';
ALTER TABLE {schema}.nexus_approvals
    ADD COLUMN IF NOT EXISTS frozen_steps TEXT NOT NULL DEFAULT '[]';
ALTER TABLE {schema}.nexus_approvals
    ADD COLUMN IF NOT EXISTS proposal_kind TEXT NOT NULL DEFAULT '';
ALTER TABLE {schema}.nexus_approvals
    ADD COLUMN IF NOT EXISTS scope_hash TEXT NOT NULL DEFAULT '';
ALTER TABLE {schema}.nexus_approvals
    ADD COLUMN IF NOT EXISTS frozen_scope TEXT NOT NULL DEFAULT '{}';
ALTER TABLE {schema}.nexus_approvals
    ADD COLUMN IF NOT EXISTS frozen_license TEXT NOT NULL DEFAULT '{}';

-- 自主实验 run（T2 run 登记 ＋ T4 线程/取消 ＋ SR6 干净B结论）
CREATE TABLE IF NOT EXISTS {schema}.nexus_experiment_runs (
    run_id TEXT PRIMARY KEY,
    owner TEXT NOT NULL DEFAULT '',
    session_id TEXT NOT NULL DEFAULT '',
    proposal_id TEXT NOT NULL DEFAULT '',
    proposal_version INTEGER NOT NULL DEFAULT 0,
    scope_hash TEXT NOT NULL DEFAULT '',
    approval_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'running',
    attempt_no INTEGER NOT NULL DEFAULT 0,
    attempts JSONB NOT NULL DEFAULT '[]',
    graph_thread_id TEXT NOT NULL DEFAULT '',
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    detail TEXT NOT NULL DEFAULT '',
    clean_status TEXT NOT NULL DEFAULT '',
    clean_note TEXT NOT NULL DEFAULT '',
    clean_checked_at DOUBLE PRECISION NOT NULL DEFAULT 0,
    clean_rule TEXT NOT NULL DEFAULT '',
    created_at DOUBLE PRECISION NOT NULL DEFAULT 0,
    updated_at DOUBLE PRECISION NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_nexus_experiment_runs_owner
    ON {schema}.nexus_experiment_runs (owner, updated_at DESC);
ALTER TABLE {schema}.nexus_experiment_runs
    ADD COLUMN IF NOT EXISTS graph_thread_id TEXT NOT NULL DEFAULT '';
ALTER TABLE {schema}.nexus_experiment_runs
    ADD COLUMN IF NOT EXISTS cancel_requested INTEGER NOT NULL DEFAULT 0;
ALTER TABLE {schema}.nexus_experiment_runs
    ADD COLUMN IF NOT EXISTS detail TEXT NOT NULL DEFAULT '';
ALTER TABLE {schema}.nexus_experiment_runs
    ADD COLUMN IF NOT EXISTS clean_status TEXT NOT NULL DEFAULT '';
ALTER TABLE {schema}.nexus_experiment_runs
    ADD COLUMN IF NOT EXISTS clean_note TEXT NOT NULL DEFAULT '';
ALTER TABLE {schema}.nexus_experiment_runs
    ADD COLUMN IF NOT EXISTS clean_checked_at DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE {schema}.nexus_experiment_runs
    ADD COLUMN IF NOT EXISTS clean_rule TEXT NOT NULL DEFAULT '';

-- 会话执行模式偏好（T2 Ask/Auto）
CREATE TABLE IF NOT EXISTS {schema}.nexus_session_prefs (
    user_id TEXT NOT NULL DEFAULT '',
    session_id TEXT NOT NULL DEFAULT '',
    research_execution_mode TEXT NOT NULL DEFAULT 'ask',
    updated_at DOUBLE PRECISION NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, session_id)
);
