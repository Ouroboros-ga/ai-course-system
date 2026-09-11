-- 0003_f5_recipe：F5 冻结配方引用（run 行只存引用，内容进 Artifact）
--
-- 幂等：ADD COLUMN IF NOT EXISTS，对既有库 no-op。
-- {schema} 由 scripts/apply_nexus_migrations.py 替换。
--
-- 回退说明（人工执行）：
--   ALTER TABLE {schema}.nexus_experiment_runs
--     DROP COLUMN recipe_hash, DROP COLUMN recipe_status,
--     DROP COLUMN recipe_artifact_id;
--   DELETE FROM {schema}.nexus_schema_migrations WHERE version='0003_f5_recipe';

-- 冻结配方引用（内容见 run 关联的 recipe/patch Artifact；hash 供干净B对账）。
ALTER TABLE {schema}.nexus_experiment_runs
    ADD COLUMN IF NOT EXISTS recipe_hash TEXT NOT NULL DEFAULT '';
ALTER TABLE {schema}.nexus_experiment_runs
    ADD COLUMN IF NOT EXISTS recipe_status TEXT NOT NULL DEFAULT '';
ALTER TABLE {schema}.nexus_experiment_runs
    ADD COLUMN IF NOT EXISTS recipe_artifact_id TEXT NOT NULL DEFAULT '';
ALTER TABLE {schema}.nexus_experiment_runs
    ADD COLUMN IF NOT EXISTS recipe_patch_id TEXT NOT NULL DEFAULT '';
