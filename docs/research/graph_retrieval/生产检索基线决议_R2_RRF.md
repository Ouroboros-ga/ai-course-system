# 测试环境检索基线决议：R2 RRF Hybrid

日期：2026-07-23。

## 决议

- 测试环境影子检索唯一候选基线为 **R2：课程隔离 BM25 + 本地 BGE Dense + RRF**。
- R3 受限一跳结构图扩展不属于生产候选路径；运行时常量
  `GRAPH_EXPANSION_PRODUCTION_CANDIDATE_ENABLED=false`，R2 sidecar provider
  不导入或调用图扩展。
- 图谱可继续作为可视化、治理和离线研究工件，但不得影响在线检索排序。

## 依据与边界

在 `reviewed_silver_v0_2` 的离线 test 中，R2 为 Recall@5 `0.4889`、MRR
`0.5148`；R3 的同两项指标均未提升。因此不以“已有图谱”为由把图扩展接入
检索链路。该数据集仍是 Reviewed Silver，不能作为泛化或回答质量声明。

本决议不包含回答生成或 abstain 校准；影子 R2 只返回 Evidence/Citation 闭合的
检索结果。发生 sidecar 故障时，可显式回退到隔离 fixture provider，响应会标注
`data_source=research_fixture_rollback`，不得伪装为真实课程数据。
