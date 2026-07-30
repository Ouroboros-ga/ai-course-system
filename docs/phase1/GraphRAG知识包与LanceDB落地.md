# GraphRAG 知识包与 LanceDB 落地

## 决策

课程知识能力使用四个明确边界：

1. GraphRAG 只消费 Canonical DocumentIR，不重新解析 PDF/PPT。
2. GraphRAG 运行 ID 只用于抽取审计；产品身份始终是
   `CourseKnowledgeNode.id ↔ node_key(kn_*)`。
3. LanceDB 每个课程、每个 Bundle 使用独立不可变目录。
4. `CourseKnowledgeHead.active_bundle_id` 是学生图谱、推荐、检索和助教只读
   Provider 的唯一正式激活指针。

教师“通过”只批准图谱和证据集合。Evidence/Citation 转正、检索快照冻结和
LanceDB 构建在 staging 状态完成；manifest、行数、维度、Citation 闭合及课程
隔离校验成功后，才通过数据库 CAS 切换 Head。

## 模块边界

- `app/platform/knowledge/`
  - DocumentIR 导出、GraphRAG 运行适配、教育关系分类、Embedding、LanceDB。
- `app/services/knowledge_bundle_service.py`
  - 整图审批、Evidence 转正、Bundle 构建、校验、激活和回滚。
- `app/domain/knowledge_bundle/ports.py`
  - 与 Agent 框架无关的只读领域协议。
- `app/platform/knowledge/sql_lance_provider.py`
  - SQL 图谱/Evidence 与 LanceDB 检索的生产组合实现。
- `app/platform/agents/providers/retrieval/active_bundle.py`
  - TeachingAgent 的只读适配器；不包含发布、编辑或 Evidence 转正能力。

Agent workflow、state 和 tool-governance 不属于本次改造范围。

## 存储布局

```text
media/knowledge_indexes/
└── courses/{course_id}/
    ├── runs/{grr_id}/
    │   ├── input/
    │   ├── output/
    │   ├── reports/
    │   └── output_manifest.json
    └── bundles/{ckb_id}/
        ├── lancedb/
        ├── manifest.json
        └── COMPLETE
```

只有包含有效 `manifest.json` 和 `COMPLETE` 的 READY Bundle 才允许激活。
回滚只新增 Activation 审计并切换 Head，不删除任何历史目录。

## 运行与恢复

任务类型：

- `knowledge.graphrag_build`
- `knowledge.vector_index`

同一课程的 GraphRAG 和向量任务分别使用持久 lease 串行化。服务重启后，
过期 lease 被移除，running 任务恢复为 pending；Active Bundle 不参与恢复写入。

如果主环境与 GraphRAG 依赖冲突，可设置 `GRAPHRAG_WORKER_PYTHON`。主任务通过
不含密钥的 input manifest 与隔离 Python 进程交换产物；密钥仅由子进程环境读取。

## Course Access

- 草稿及原文预览：`knowledge.review` + `evidence.review`
- 重新生成：`knowledge.review`
- 整图通过：`knowledge.edit` + `evidence.confirm`
- 版本与差异：`knowledge.version.view`
- 回滚：`knowledge.edit`
- 学生图谱：`knowledge.view`
- 节点 Citation 与检索：`knowledge.view` + `course.citation.read`

助教非 HTTP 调用同样通过 Course Access v1 校验课程成员和能力，不依赖
`User.role`、`Course.teacher_id` 或旧 Enrollment 回退。

## 课程 87 的执行状态（2026-07-30）

课程 87 已完成真实运行，不再是未配置状态：

- Canonical DocumentIR 输入：318 RetrievalChunk；
- 原始 GraphRAG：813 entities、1141 relationships；
- 严格零模型精炼：过滤 5 个占位实体，产出 808 个稳定节点、1137 条关系；
- Active Bundle：v4 `ckb_6dbf7fa483b145888f57e094063a27c9`；
- LanceDB：READY，512 维，218 text units、808 entities、218 evidence；
- 新进程检索可读取，结果 Citation 闭合，历史 v1-v3 索引保留。

旧 `semantic_anchor` 身份合并会把同一文本块中的不同概念错误合并，已由
`strict-title-anchor/1.0` 替代。完整当前设计、接口、错误码和前端已知限制见
[课程知识图谱 GraphRAG / Bundle 设计与接口说明](课程知识图谱GraphRAG_Bundle设计与接口说明.md)。

自动化测试仍禁止访问付费接口；已有 Parquet 的精炼接口固定为零模型调用。
