# Product 1 图谱与可信检索研究

> Agent B 研究工作区。审计基线：`d4894da`；审计日期：2026-07-16。

## 当前结论

B-R0 已批准。算法前置工程 B-P0 已完成：当前 HEAD 的 9 个冻结契约输入已建立 SHA-256 漂移门禁，tokenizer、BM25、course-first、Evidence、稳定排序、abstain 和 B-R2 mapping 规则已固化为机器可检查规格。B-P0 的状态固定为 `prepared_not_released`，不授权 B-R1 实现或效果比较。

当前仍只放行 B-G0：B-G0a micro-contract fixture、schema、hash、稳定 research ID、引用闭合、人工标注工具和离线评测脚本已实现；B-G0b 真实 human gold 尚未完成。

本轮没有实现 tokenizer、BM25、PPT 映射打分、Dense、RRF、图扩展或 GraphRAG，没有调用真实 LLM、向量服务、生产数据库，也没有修改生产代码或依赖锁。micro fixture 明确禁止用于算法效果比较。

B-P0 可重复检查：

```powershell
.venv\Scripts\python.exe research/product1_graph_retrieval/tools/check_b_r1_release.py --preflight-only research/product1_graph_retrieval/datasets/micro_contract_v1
```

输出必须包含 `implementation_authorized=false`、`quality_comparison_authorized=false`；任何冻结契约文件漂移都会 fail closed 并要求重新审计。

首个可执行基线的推荐顺序是：

1. 先由至少两名真实团队成员独立标注 Level B 数据，并由第三人仲裁。
2. P1-00 确认 research sidecar 口径，P1-10 复核人员、gold、split 与泄漏。
3. B-R1 在课程分区后的候选集上运行可解释、确定性的 BM25。
4. B-R2 在同一 fixture 上运行“标题 + BM25 + 章节位置”的知识点—PPT 页映射。
5. 只有 B-R1/B-R2 通过证据完整性、跨课程污染和可复现门禁后，才进入 Dense、RRF 和受限图扩展消融。
6. 不实现或接入生产 GraphRAG；图增量是否有价值只由同金标消融结果决定。

## 强制边界

- 唯一研究写入范围：`research/product1_graph_retrieval/**`。
- 对外研究文档写入范围：`docs/research/graph_retrieval/**`。
- 只消费冻结 JSON/JSONL fixture，不调用上传、ORM、生产 QA、前端或生产数据库。
- 不修改 `backend/app/**`、`backend/tests/product1/**`、`frontend/**`、公开 API、ORM、Migration、配置、依赖或锁文件。
- 无活动 Evidence 时必须 `abstain`；不得生成 `Citation` 对象或伪 citation key。
- 所有比较必须使用同一 fixture、查询集、课程范围、TopK、指标脚本和随机种子。

## 文件导航

- [assumptions.md](assumptions.md)：事实、假设、边界和停止条件。
- [contract_adaptation_audit.md](contract_adaptation_audit.md)：DocumentIR、Evidence、Graph、Retrieval 契约适配审计。
- [research_questions.md](research_questions.md)：研究问题、假设和判定规则。
- [literature_review.md](literature_review.md)：论文与开源项目调研，区分论文结论和项目推断。
- [datasets/fixture_spec.md](datasets/fixture_spec.md)：冻结数据格式、标注与完整性规则。
- [experiments/evaluation_protocol.md](experiments/evaluation_protocol.md)：指标、消融、公平性和复现协议。
- [reports/fixture_audit.md](reports/fixture_audit.md)：B-G0a micro fixture 的复现标识与测试结果。
- [B-R0 研究结论](../../docs/research/graph_retrieval/B-R0研究结论.md)：面向治理与决策的摘要。
- [B-R1 至 B-R3 实施计划](../../docs/research/graph_retrieval/B-R1至B-R3实施计划.md)：分阶段实现、验证与回滚计划。
- [B-G0 实现与人工 Gold 门禁](../../docs/research/graph_retrieval/B-G0实现与人工Gold门禁.md)：当前状态、人工边界和 release gate。

## 尚未满足的启动条件

B-R1 暂不应开始编码，直到以下输入均已就绪：

- Level B 的 3～5 门真实、脱敏课程冻结输入；
- 包含同词异课、无答案、缺 Evidence、失效 Evidence 的负例；
- 至少两名真实团队成员独立完成 retrieval/mapping 标注，并由第三人仲裁；
- P1-00 书面确认 `research_evidence_id` 等 sidecar 口径；
- P1-10 复核人员、gold、分层、split、hash 和 test qrels 隔离；
- B-R1 release checker 返回 approved。

这些条件不是生产契约变更请求。研究侧将先使用严格、可逆的 sidecar 适配层；若未来需要晋级生产，再由契约 Owner 按 ADR 流程处理。
