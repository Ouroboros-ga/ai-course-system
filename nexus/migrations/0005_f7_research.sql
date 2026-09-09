-- 0005_f7_research：F7 研究任务＋证据持久化
--
-- 幂等：CREATE ... IF NOT EXISTS，对既有库 no-op。
-- {schema} 由 scripts/apply_nexus_migrations.py 替换。
--
-- 回退说明（人工执行）：
--   DROP TABLE {schema}.nexus_research_evidence;
--   DROP TABLE {schema}.nexus_research_tasks;
--   DELETE FROM {schema}.nexus_schema_migrations WHERE version='0005_f7_research';
-- 任务行是研究账本：回退前确认无 running 任务依赖其对账，否则先停新任务。

CREATE SCHEMA IF NOT EXISTS {schema};

-- 研究任务：Brief＋子问题＋预算/用量＋结果摘要（全文不进本表，只存摘要与引用）。
CREATE TABLE IF NOT EXISTS {schema}.nexus_research_tasks (
    task_id TEXT PRIMARY KEY,
    parent_task_id TEXT NOT NULL DEFAULT '',
    owner TEXT NOT NULL DEFAULT '',
    session_id TEXT NOT NULL DEFAULT '',
    brief JSONB NOT NULL DEFAULT '{}',
    questions JSONB NOT NULL DEFAULT '[]',
    budget JSONB NOT NULL DEFAULT '{}',
    used JSONB NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'open',
    findings JSONB NOT NULL DEFAULT '[]',
    evidence_ids JSONB NOT NULL DEFAULT '[]',
    gaps JSONB NOT NULL DEFAULT '[]',
    conflicts JSONB NOT NULL DEFAULT '[]',
    experiment_run_ids JSONB NOT NULL DEFAULT '[]',
    report_artifact_id TEXT NOT NULL DEFAULT '',
    cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
    detail TEXT NOT NULL DEFAULT '',
    created_at DOUBLE PRECISION NOT NULL DEFAULT 0,
    updated_at DOUBLE PRECISION NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_nexus_research_tasks_owner
    ON {schema}.nexus_research_tasks (owner, updated_at DESC);

-- 研究证据：来源版本＋内容 hash＋locator＋覆盖范围＋权限（重启不丢失）。
CREATE TABLE IF NOT EXISTS {schema}.nexus_research_evidence (
    evidence_id TEXT PRIMARY KEY,
    owner TEXT NOT NULL DEFAULT '',
    session_id TEXT NOT NULL DEFAULT '',
    task_id TEXT NOT NULL DEFAULT '',
    attachment_id TEXT NOT NULL DEFAULT '',
    source_title TEXT NOT NULL DEFAULT '',
    source_version TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL DEFAULT '',
    locator TEXT NOT NULL DEFAULT '',
    excerpt TEXT NOT NULL DEFAULT '',
    coverage TEXT NOT NULL DEFAULT '',
    truncated BOOLEAN NOT NULL DEFAULT FALSE,
    created_at DOUBLE PRECISION NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_nexus_research_evidence_owner
    ON {schema}.nexus_research_evidence (owner, session_id);
