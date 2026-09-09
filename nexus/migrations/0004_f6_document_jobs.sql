-- 0004_f6_document_jobs：F6 文档作业（单行存引用＋快照＋分格式状态）
--
-- 幂等：CREATE ... IF NOT EXISTS，对既有库 no-op。
-- {schema} 由 scripts/apply_nexus_migrations.py 替换。
--
-- 回退说明（人工执行）：
--   DROP TABLE {schema}.nexus_document_jobs;
--   DELETE FROM {schema}.nexus_schema_migrations WHERE version='0004_f6_document_jobs';
-- 作业行是渲染账本：回退前确认无 rendering 作业依赖其重试，否则先停新作业。

CREATE SCHEMA IF NOT EXISTS {schema};

-- 文档作业：一份冻结内容＋模板＋格式集合；产物字节走 Artifact 链，不进本表。
-- source JSONB 内含 _frozen{markdown,title,template}（重试复用同一快照）与
-- 来源引用（run_id/artifact_id）；formats JSONB 为每格式独立状态。
CREATE TABLE IF NOT EXISTS {schema}.nexus_document_jobs (
    job_id TEXT PRIMARY KEY,
    owner TEXT NOT NULL DEFAULT '',
    session_id TEXT NOT NULL DEFAULT '',
    idempotency_key TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    template TEXT NOT NULL DEFAULT '',
    template_version TEXT NOT NULL DEFAULT '',
    source JSONB NOT NULL DEFAULT '{}',
    formats JSONB NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'queued',
    created_at DOUBLE PRECISION NOT NULL DEFAULT 0,
    updated_at DOUBLE PRECISION NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_nexus_document_jobs_owner
    ON {schema}.nexus_document_jobs (owner, updated_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_nexus_document_jobs_owner_key
    ON {schema}.nexus_document_jobs (owner, idempotency_key)
    WHERE idempotency_key <> '';
