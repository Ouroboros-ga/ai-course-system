# Agent B / B-R0 研究结论

> 日期：2026-07-16  
> 任务卡基线：`d4894da`  
> 审计 HEAD：`4b2bafd`  
> 阶段：研究与规划完成，算法尚未实现

## 1. 决策结论

Agent B 可以进入 B-R1/B-R2，但应先完成冻结 fixture 和 gold 标注，不能立即复用当前生产 Provider 协议写“证据完整 BM25”。

推荐路线：

```text
冻结 DocumentIR/Evidence fixture
  -> 每课程独立 corpus/index
  -> BM25 + Evidence sidecar + abstain
  -> 标题 + BM25 + 章节位置的 PPT 映射
  -> Dense exact baseline
  -> RRF Hybrid
  -> accepted/active/same-course 一跳图扩展
  -> P1-10 独立验证
```

本路线不包含生产 GraphRAG、LLM 抽图、外部向量服务或生产接线。

## 2. 为什么不直接实现

当前缺少真实冻结研究输入和 gold。先写算法会迫使实现者自行假设 course scope、Evidence ID、page 语义、chunk identity 和 abstain 格式，最后得到无法科学比较的基线。

契约审计还发现四个直接前置：

1. 登记表有 `GraphEvidence`，但指定 Education Graph 代码表面没有同名模型，实际只保存 `evidence_ids`。
2. `EvidenceSpan` 没有单条 `evidence_id`，无法直接按任务卡口径统计。
3. `BM25Provider.index(scope, List[str])` 只接收裸文本，不能保留页、块和 Evidence 身份。
4. `GraphSnapshot(frozen=True)` 是浅冻结，且没有显式 `course_id`。

这些问题不要求 Agent B 修改生产契约。B-R1/B-R2 先使用研究 sidecar 严格适配；未来若晋级生产，由 P1-00/P1-03/P1-05 走 ADR。

## 3. 已核验的现有基础

- `DocumentIR`、Geometry、Evidence、Citation、RetrievedChunk、EducationalUnit/GraphSnapshot 均在登记表中冻结。
- DocumentIR 能保留 source、unit、block、reading order、页/幻灯片、文本、bbox 和 provenance。
- EvidenceSpan 能保留 artifact/document/unit/block、字符区间、页码和 active/stale/suspended 状态。
- RetrievalScope 显式支持 `course`；Gateway 对缺失 scope 不回退其他范围。
- RetrievedChunk 已预留 artifact/document/unit/block/evidence_spans 字段，但仍是 optional 过渡契约。
- 教育图谱已有结构/语义节点、`SUPPORTED_BY`、`APPEARS_ON`、type matrix 和 prerequisite cycle 校验。

这些基础足以建立离线研究，不足以声称生产可信检索已经实现。

## 4. 论文与开源项目研究结论

- BM25 是精确术语、标题、定义、公式/API 的透明下界；中文分词和 chunk 粒度必须本地验证。
- Dense 在开放域论文中能改善语义召回，但不能把英文开放域结果外推到中文课程、公式和代码。
- BEIR 等异构评测工作说明不同数据/查询类型表现差异显著，因此本项目必须分层报告。
- RRF 适合作为首个 rank-based Hybrid，但后续研究指出参数敏感；`k=60` 只进入参数网格。
- 教育图谱/讲义概念图研究支持利用课程结构、幻灯片布局、概念和先修关系；其本体与指标不能直接照搬。
- ALCE 支持把 citation completeness 与 correctness 分开；B-R1 只做结构完整性和 gold relevance，不调用 LLM/NLI。
- Microsoft GraphRAG 面向 LLM 抽图与全局 sensemaking，成本和任务定义都不符合本轮基线，不接入。

完整来源见 [literature_review.md](../../../research/product1_graph_retrieval/literature_review.md)。

## 5. 冻结研究设计

### B-R1

- 每个 course 独立索引，先选 scope 再评分。
- 无新增依赖的可解释 BM25。
- mixed-script tokenizer：拉丁 token + CJK unigram/bigram，规则与版本固定。
- 每个 hit 强制恢复 active Evidence、页码、block 和可重算 citation key。
- 无 Evidence、无 scope、无 match 时显式 abstain。
- 输出 Recall@5/10、MRR、nDCG、污染率、Evidence/Citation 完整率、拒答与失败样例。

### B-R2

- 候选页先按课程过滤。
- 初始可解释公式：`0.45 title + 0.40 normalized BM25 + 0.15 chapter proximity`。
- 比较单特征、等权和起始权重；只在 validation 调权。
- 无 active Evidence、全零信号或校准后歧义时 abstain。
- 输出 Top-1/Top-3、MRR、Evidence binding 和 feature breakdown。

### B-R3

- Dense 使用固定模型 revision 和离线权重，先做 exact search。
- RRF 比较 `k=20/60/100` 与预注册权重。
- Graph 只做同课程、accepted、active-evidence 一跳扩展。
- R0/R1/R2/R3 使用同一 gold、query、scope、candidate budget、TopK 和评测脚本。
- 没有 paired 增量证据就不晋级 Graph。

## 6. 硬门禁

| 门禁 | 要求 |
| --- | --- |
| 跨课程污染 | 精确 0；一个错误课程 hit 即失败 |
| Evidence 完整率 | 1.0 |
| citation key 可重算率 | 1.0 |
| 无证据行为 | abstain，hits 空，不创建 Citation |
| 可复现 | 相同 manifest/config/commit/seed 两次 run 字节相同 |
| 结果报告 | 真实 Recall/MRR/映射指标/成本/失败样例，不填造提升 |

不预设 Recall、MRR 或 Top-1 的“必须提升百分比”，避免在没有 gold 前伪造目标。只有安全指标使用硬阈值。

## 7. 启动清单

B-R1 编码前需完成：

- [ ] 至少两课程 frozen DocumentIR/Evidence fixture；
- [ ] 同词异课、no-evidence、stale-only、公式/代码、同义改写负例；
- [ ] 双人标注并仲裁的 retrieval qrels；
- [ ] 双人标注并仲裁的知识点—PPT mapping qrels；
- [ ] manifest、file SHA-256、split；
- [ ] P1-00 确认研究 `evidence_id` sidecar 口径；
- [ ] P1-10 接受评测协议版本。

## 8. 本轮变更与验证口径

本轮只新增 `research/product1_graph_retrieval/**` 和 `docs/research/graph_retrieval/**` 下的研究文档，没有实现算法或运行算法指标，也没有启动后端或调用外部服务。

因此本报告不继承历史测试通过数作为本轮验证。交付前只做文档路径、UTF-8、范围和 `git diff --check` 验证。
