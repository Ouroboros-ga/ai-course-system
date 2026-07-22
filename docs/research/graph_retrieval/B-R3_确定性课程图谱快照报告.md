# B-R3：确定性课程图谱快照报告

## 结论

已从 Reviewed Silver v0.2 的公开 research fixture 构建不可变、可校验的课程图谱快照。它是研究 sidecar，不是生产 Education Graph，不是 GraphRAG，也没有接入检索/问答链路。

快照：[snapshot.json](../../../research/product1_graph_retrieval/graphs/reviewed_silver_v0_2_snapshot_r0_m0/snapshot.json)。

## 图谱内容

| 节点类型 | 数量 |
| --- | ---: |
| Course | 4 |
| Chapter | 36 |
| KnowledgePoint | 71 |
| PPTSlide | 253 |
| ScriptNode（SourceBlock 的 research 表示） | 1,083 |
| Evidence | 1,083 |

| accepted 边 | 数量 | 结构来源 |
| --- | ---: | --- |
| `CONTAINS` | 360 | 课程/章节/课件结构 |
| `GROUNDED_BY` | 205 | KnowledgePoint 的 active Evidence |
| `MAPPED_TO` | 1,288 | slide—block 结构或 KnowledgePoint 与 slide 的共享 active Evidence |
| `NEXT` | 32 | 每门课程中 chapter 的首次 slide 顺序 |

每条边保持同课程范围。带 Evidence 的边只引用 active Evidence；`GROUNDED_BY` 和知识点到 PPT 的映射均可追溯回 `research_evidence_id`。

## 明确没有写入的关系

以下关系即使可能有语义相关性，也没有从相似度或模型输出发布为 accepted edge：

`PREREQUISITE_OF`、`RELATED_TO`、`HAS_MISCONCEPTION`、`USES`、`EXPLAINS`。

它们只能在后续具备单独审核证据时作为候选关系处理。

## 完整性

- 节点数：2,530；边数：1,885。
- fixture manifest：`ea1f660d0c73dff28f1815456a8ab683bde487d85db70f44b6a8c43c41063975`。
- graph content SHA-256：`04f200f5172d7b2cfc9bad18d5c5d513bdba3f46e902dd9eb9c3b08658541f51`。
- 节点 / 边文件 SHA-256 分别记录在 snapshot manifest 中。

构建器拒绝覆盖非空输出目录，避免同名快照被静默改写。后续 R3 图增量实验只能消费 accepted 的同课程、active-Evidence、一跳关系，并且必须与 R2 使用相同最终候选预算。
