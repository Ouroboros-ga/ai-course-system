# B-R0 研究问题与判定规则

## 总研究目标

在不接入生产系统的前提下，判断课程隔离、Evidence 可追溯的检索与知识点—PPT 页映射，能否先由简单可解释基线成立；随后再判断 Dense、RRF 和受限图扩展是否提供可重复的增量收益。

## RQ-01：课程优先过滤能否把污染率稳定为零？

- 对照：全局候选后过滤，仅作为故障注入对照，不作为可晋级实现。
- 实验：每门课程独立索引；查询只访问一个 `course_id` 对应的分区。
- 必备负例：不同课程包含完全相同标题、知识点名和正文片段。
- 通过：每次运行、每个 TopK 的跨课程污染率均精确等于 0。
- 失败：出现一个错误课程 hit 即失败，不用平均值掩盖。

## RQ-02：BM25 能否形成可信检索下界？

- 假设：精确术语、公式符号、标题词和局部定义查询上，BM25 是可解释的强下界。
- 变量：`k1`、`b`、CJK n-gram 策略、chunk 粒度。
- 固定：课程范围、语料、gold、TopK、Evidence 校验和 tie-break。
- 主指标：Recall@5、Recall@10、MRR。
- 安全指标：污染率、Evidence/Citation 结构完整率、正确/错误拒答率。
- 通过：安全门禁全过，并输出真实指标与全部失败样例；不设置未经数据验证的质量承诺值。

## RQ-03：标题 + BM25 + 章节位置能否映射知识点到 PPT 页？

- 候选先按课程过滤。
- 特征必须逐项输出，不能只返回总分。
- 建议的首个注册公式是 `0.45 * title_match + 0.40 * normalized_bm25 + 0.15 * chapter_proximity`。
- 上述权重只是待验证的起始配置；还需与单特征、等权和小网格对照。
- 主指标：Top-1、Top-3、MRR、Evidence 绑定完整率。
- 安全门禁：无 active Evidence 或所有信号为零时 abstain。

## RQ-04：Dense 是否补足 BM25，而不是替换 BM25？

- 查询分层：精确术语、同义改写、中英别名、代码/公式、长问题、无答案。
- Dense 模型必须固定名称、revision、文件 SHA-256、池化和归一化方式。
- 首轮使用精确向量搜索，避免把近似索引误差混入模型比较。
- 判定：报告分层 Recall/MRR 及 BM25 胜、Dense 胜、两者都失败的样例，不用总平均掩盖退化。

## RQ-05：RRF 是否提供稳定互补收益？

- 对照：BM25、Dense、RRF Hybrid。
- 候选深度和最终 TopK 一致。
- `k` 至少比较 20、60、100；如使用权重，权重网格预注册。
- tie-break 固定为 `(-rrf_score, stable_chunk_id)`。
- 判定：RRF 只有在质量提升且污染、Evidence 完整性不退化时才可晋级。

## RQ-06：图扩展是否对特定查询有净增益？

- 图不是生产 GraphRAG；只读取冻结 GraphSnapshot sidecar。
- 只扩展同课程、accepted、active-evidence 的允许边。
- 首轮只做一跳，按关系类型设置预算；不自动生成实体、关系或社区摘要。
- 重点查询：先修、例子、公式用途、易错点、同页关联。
- 对照：Hybrid 与 Hybrid + Graph 使用相同首轮候选、最终 TopK 和评测脚本。
- 判定：若图扩展只增加 Recall 却显著降低 MRR、Citation 完整性或延迟，必须报告代价，不能宣称整体更优。

## RQ-07：何时必须 abstain？

至少覆盖以下原因码：

- `empty_query`
- `scope_not_available`
- `no_lexical_match`
- `no_active_evidence`
- `below_registered_threshold`
- `ambiguous_mapping`

无 active Evidence 是硬拒答；分数阈值是需要验证集校准的软拒答。任何 abstain 结果的 `hits` 必须为空，`citation_key` 必须为 `null`，且不得创建 `Citation` 对象。

## RQ-08：结果能否重放？

- 相同 fixture manifest、配置、代码提交、Python 版本和种子必须得到字节级相同的 run JSONL。
- BM25 本身不依赖随机数，但统一记录 `seed=0`，避免后续实验遗漏。
- 所有排序必须有稳定二级键。
- 浮点输出按固定小数位序列化，配置和语料均记录 SHA-256。
