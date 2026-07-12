# R2D 实施路线图

## 1. 顺序原则

先建立 DocumentIR、ParserProvider contract、持久化身份和评测基线，因为它们使任意 parser/图算法可替换、可比较、可回滚。直接接重型外部解析器、GraphRAG 或 Neo4j 会先引入私有 schema、部署和模型成本，却仍无法证明质量提升。

## 2. 里程碑

### R2D1 基础契约与 Shadow 骨架

- 修改范围：SourceArtifact、DocumentProbe、ParserProvider/ParserRegistry、DocumentIR、FakeParser、JSON artifact persistence、最小 V1 adapter、feature flags、benchmark 目录和测试。
- 相关文件：新增 `backend/app/platform/document_intelligence/`、对应 tests/config docs；生产 endpoint 是否接 shadow 另行批准。
- 风险：误写 V1、ID 不稳定、schema 过早膨胀。
- 验证：contract/schema/idempotency/fake tests + M7/M4/R1/R2 回归。
- 完成标准：同一 fixture 可稳定生成 DocumentIR；五类失败可控；默认 `v1_only` 行为零变化。
- 回滚：关闭 flag，删除新增模块/独立 shadow artifact；不涉及生产表。

### R2D2 Parser Provider 与质量路由

- 修改范围：Docling DocumentIR adapter、native PPTX ParserProvider、DocumentProbe/ParsePlan、quality scorer、reconciliation。
- 相关文件：document intelligence providers/planner/reconciliation；冻结 fixtures。
- 风险：bbox/坐标不一致、普通 PPTX 回退、依赖版本漂移。
- 验证：普通/图片 PPTX、文本 PDF、DOCX 基准；provider contract；无网回归。
- 完成标准：解析硬门槛满足；shadow 不写 V1；raw provenance 完整。
- 回滚：planner provider allowlist 回到 V1/Docling 单 provider。

### R2D3 OCR/表格/公式/视觉增强

- 修改范围：PP-StructureV3 trial provider、page render、预算、缓存和 enrichment。
- 相关文件：独立 provider/adapter、部署说明、fakes、benchmark。
- 风险：GPU/模型体积、3.x API 变化、成本、隐私、Windows 差异。
- 验证：扫描/表格/公式/流程图集，CPU/GPU P95，模型 hash，business failure。
- 完成标准：仅低质量页触发；覆盖指标达门槛；预算超限可解释。
- 回滚：禁用 enrichment provider，保留基础 DocumentIR 和 needs_review。

### R2D4 Educational Unit 与图候选

- 修改范围：semantic chunk、ontology、schema-guided entity/relation candidates、evidence。
- 相关文件：education/graph domain、新 schema 与 fake extractor。
- 风险：prompt 漂移、长文漏抽、无证据幻觉。
- 验证：实体/关系/证据金标；malformed/business failure；不调用真实付费服务。
- 完成标准：无 accepted 无证据边；候选状态完整；抽取可分段重放。
- 回滚：停 extractor，DocumentIR 仍可独立使用。

### R2D5 归一化、校验、审核与关系库存储

- 修改范围：canonicalization、类型矩阵、先修环、review、graph tables/snapshot/GraphStore SQL provider。
- 相关文件：models/migrations/store/review tests；实施前单独审批 migration。
- 风险：误合并、环、迁移耗时、删除语义。
- 验证：空库/生产副本 migration；idempotency；snapshot switch/rollback；graph metrics。
- 完成标准：图谱硬门槛满足；快照不可变；5 分钟内回滚。
- 回滚：pointer 回旧 snapshot，down migration 仅在无引用环境执行。

### R2D6 混合检索与引用

- 修改范围：course-scoped BM25/向量/entity/graph/evidence/rerank 和 cited context。
- 相关文件：retrieval interfaces/providers/QA shadow adapter。
- 风险：跨课程污染、图扩展爆炸、引用不支持答案。
- 验证：scope isolation、Recall@K/MRR/nDCG、QA/citation/no-answer。
- 完成标准：引用正确率和 QA 增益达门槛；扩展有 hop/fanout/type 限制。
- 回滚：QA feature flag 回 V1 tree/knowledge search。

### R2D7 Preferred Canary 与历史迁移

- 修改范围：projection、canary、历史课程批处理、运维手册。
- 相关文件：orchestration/admin scripts/metrics；不改公开 API。
- 风险：用户行为变化、资源峰值、双写污染。
- 验证：7 天/100 run shadow，1%-100% 分级；M7 冒烟；灾备演练。
- 完成标准：所有切换门槛通过，人工批准 preferred。
- 回滚：`v1_only` + active pointer/projection manifest 回滚。

### R2D8 可选图引擎/高级算法试验

- 修改范围：Neo4j/OpenSPG provider 或 GraphRAG/LightRAG 对照实验。
- 风险：运维、许可、索引成本、框架绑定。
- 验证：相同 `GraphStore/Retriever` contract 和 benchmark，证明收益大于复杂度。
- 完成标准：关系库达到明确瓶颈且试验指标显著改善；否则 Reject for now。
- 回滚：删除可选 provider 配置，不改变业务 schema。

## 3. 依赖关系

```text
R2D1 -> R2D2 -> R2D3
  |        |
  +------> R2D4 -> R2D5 -> R2D6 -> R2D7
                                  |
                                  +-> R2D8（可选）
```

R2D3 可与 R2D4 部分并行，但图谱验收必须使用质量合格 DocumentIR。R2D8 永远不是 R2D5/R2D6 的前置。

## 4. 每阶段共同提交记录

每个提交记录修改范围、证据路径、验证命令与真实结果、未运行项、限制、配置默认值、migration/数据影响和逐步回滚。不得以 skip、弱化断言或真实付费请求换取绿灯。
