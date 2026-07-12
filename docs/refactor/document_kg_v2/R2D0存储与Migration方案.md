# R2D0 存储与 Migration 方案

## 1. 原则

本文件是后续 migration 设计，不在 R2D0 执行。第一实现使用现有关系数据库能力，业务层只依赖 `GraphStore`，Neo4j/OpenSPG 是可选 provider。V2 表与 V1 `Course/DoclingDocument/CourseScript/ScriptNode/KnowledgePoint` 隔离；shadow 不双写 V1。

### 1.1 ID 与执行术语

- `artifact_id/document_id/unit_id/block_id` 是 DocumentIR 的稳定对象身份，规则以 `R2D0-DocumentIR设计.md` 为准；不得由执行时间、状态、duration 或重试派生。
- `run_id` 是一次 DocumentPipelineRun 的执行身份；每次执行新建 UUIDv7/ULID。
- `parser_run_id` 是该 `run_id` 内一次 ParserProvider 调用的执行身份；每次调用新建 UUIDv7/ULID。
- `idempotency_key` 是用于复用已完成结果的确定性查询键，独立于 `run_id/parser_run_id`，不能反向替代执行身份。

## 2. 表设计

通用约定：主键 UUID/ULID 字符串；`created_at/updated_at`；JSON 字段必须有 schema_version；大 raw 文件放 artifact storage，DB 保存 URI、checksum、size。

| 表 | 核心字段 | 主外键/唯一约束 | 关键索引 | 删除策略 |
|---|---|---|---|---|
| `source_artifact` | `artifact_id, course_id, sha256, filename, mime, size, uri, status` | FK course；unique `(course_id,sha256)` | course/status, sha256 | course 删除时软删；物理文件延迟 GC |
| `document_pipeline_run` | `run_id, course_id, artifact_id, pipeline_version, runtime_mode, config_hash, idempotency_key, status, error, started/finished` | FK SourceArtifact；unique `(artifact_id,pipeline_version,config_hash,idempotency_key)` | course/status/created | 审计保留，不级联清除 |
| `parser_run` | `parser_run_id, run_id, provider, provider_version, config_hash, status, error, started/finished/duration` | FK DocumentPipelineRun；unique `(run_id,parser_run_id)` | run/provider/status | 审计保留；raw output 由 artifact 引用 |
| `document_artifact` | `document_artifact_id, run_id, kind, schema_version, uri, checksum, size` | unique `(run_id,kind,checksum)` | run/kind | run 保留期后 GC，已发布引用不可删 |
| `document_block` | `block_id, run_id, document_id, unit_id, page, kind, block_type, reading_order, bbox_json, text, confidence, provenance_json` | stable unique `(document_id,block_id,schema_version)` | run/page/order, kind；文本检索索引后加 | run 级级联仅限未发布 shadow |
| `educational_unit` | `unit_id, run_id, document_id, course_id, parent_id, type, ordinal, title, block_refs_json, quality` | stable unique `(document_id,unit_id,schema_version)` | course/run/parent | 与 run 一致 |
| `graph_snapshot` | `id, course_id, ontology_version, source_run_id, status, metrics_json, published_at` | unique `(course_id,id)`；每课程至多一个 active | course/status | 不可变；retired 后按策略归档 |
| `graph_node` | `id, snapshot_id, type, canonical_key, name, aliases_json, properties_json, status, confidence` | unique `(snapshot_id,type,canonical_key)` | snapshot/type/key/name | snapshot 级不可变 |
| `graph_edge` | `id, snapshot_id, source_id, target_id, type, directed, status, confidence` | unique `(snapshot_id,source_id,type,target_id)` | source/type, target/type, snapshot/status | snapshot 级不可变 |
| `graph_mention` | `id, snapshot_id, node_id, block_id, char_start/end, surface, confidence` | unique `(node_id,block_id,char_start,char_end)` | node, block | 随 snapshot |
| `graph_evidence` | `id, snapshot_id, subject_kind, subject_id, artifact_id, block_id, page, bbox/span, quote_hash, run_id, parser_run_id` | evidence target 与 block/run FK | subject, block, artifact/page | 已发布证据不可单删 |
| `graph_review` | `id, snapshot_id, target_kind/id, decision, reason, reviewer_id, before/after_json` | unique 可按 `(target,review_round)` | status/reviewer/created | 审计保留 |

建议增加 `course_document_pipeline_state(course_id, active_document_run_id, active_graph_snapshot_id, version)`，或在单独 pointer 表实现原子切换；不要给现有 `Course` 直接塞大量 V2 临时字段。

## 3. 版本与幂等

- SourceArtifact identity：`artifact_id` 由 `sha256(bytes)` 与源格式规范化规则确定；同 bytes 和同规则可复用。
- DocumentIR identity：`document_id/unit_id/block_id` 按 DocumentIR 稳定 ID 规则生成；`DocumentUnit.block_ids` 只引用同一 DocumentIR 的 `blocks[].block_id`。
- `run_id` 与 `parser_run_id` 每次执行/调用均重新生成；二者不参与稳定对象 ID。
- `idempotency_key` 由 `artifact_id + pipeline_version + ParserProvider/model/prompt/config hashes` 构成，用于查找可复用结果，而非标识本次执行。
- graph identity：snapshot 内 `type + canonical_key`；不同 snapshot 不复用物理 row，方便准确回滚。
- 重复请求先按 `idempotency_key` 查 succeeded run；`force=true` 创建新的 `run_id`，但不原地覆盖。
- run 状态使用乐观锁/version；只有 owner 可完成状态转换。

## 4. 课程重解析

1. 创建新的 `run_id`，旧 active pointer 不变。
2. 生成独立 SourceArtifact/DocumentIR/DocumentUnit/candidate graph。
3. 与当前 snapshot 计算 diff：新增、删除、合并、证据漂移、先修环。
4. 评测与审核通过后创建 immutable snapshot。
5. 单事务切换 active pointers；兼容投影另事务执行并可重放。
6. 失败只标记新 run，不修改旧课程可见结果。

## 5. 图版本与回滚

- `draft -> validated -> active -> retired`；snapshot 内容在 validated 后不可修改。
- 回滚只切 active pointer 到前一 snapshot，不反向执行大量 delete/insert。
- 兼容投影写入前记录 projection manifest（目标行 ID、旧值 hash、新值 hash）；回滚时仅在当前值仍匹配新值 hash 时恢复，避免覆盖用户后续编辑。
- V2 shadow 数据按 `run_id/mode` 清理；任何被 active snapshot、review 或 benchmark 引用的 artifact 受保护。

## 6. GraphStore 接口

```python
class GraphStore(Protocol):
    def stage(self, run_id, nodes, edges, mentions, evidence) -> StageResult: ...
    def validate_snapshot(self, snapshot_id) -> ValidationResult: ...
    def activate(self, course_id, snapshot_id, expected_version) -> None: ...
    def get_active(self, course_id) -> GraphSnapshotRef | None: ...
    def query_nodes(self, scope, filters, limit): ...
    def expand(self, scope, seed_ids, relation_types, max_hops, fanout): ...
    def evidence_for(self, subject_ids): ...
    def delete_shadow_run(self, run_id) -> DeleteReport: ...
```

关系库 provider 用 joins/recursive CTE（若 SQLite 能力受限，应用层做有界 BFS）；Neo4j/OpenSPG provider 必须通过相同 contract tests。向量存储独立 `VectorStore` 接口，不把 embedding 二进制强塞图节点语义。

## 7. Migration 分批

| 批次 | 内容 | 可逆性/门禁 |
|---|---|---|
| D1 | artifact/run/artifact-output 表 | 只新增表；down 前确认无引用 |
| D2 | document block/unit 表 | shadow-only；不改 V1 |
| D3 | graph snapshot/node/edge/mention/evidence/review | provider contract tests |
| D4 | active pointer 与投影 manifest | 原子切换/回滚测试 |
| D5 | 可选索引/向量/外部图 provider | 独立部署与回滚，不是主链前置 |

每批 migration 前备份生产 SQLite、验证空库升级和生产副本升级、记录耗时与磁盘增量。R2D1 只允许 JSON artifact persistence 的最小实现设计，是否建 D1 表由后续人工批准。

## 8. 风险

- SQLite 并发写：长解析不持有事务；阶段产物短事务写入。
- JSON 演进：读取器按 schema version，未知 major 拒绝。
- 级联误删：published snapshot 使用 RESTRICT；shadow run 才允许受控 cascade。
- 双写污染：shadow 无 projection 权限；preferred 模式也先创建 snapshot，再显式投影。
