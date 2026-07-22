# B-R2 / M0：知识点—PPT 映射实验报告

## 结论

M0 已完成为一个独立于生产系统的离线页面映射基线。它直接复用 R0 的 `mixed-script-ngram/1.0` tokenizer 和 `course-bm25/1.0`，没有新增分词、向量模型或 LLM。

结果仅具 `reviewed_silver_offline_research_only` 资格，不是人工 Gold 结论，也不授权生产图谱或 RAG 接入。

## 固定规则

在 `course_id` 内对所有带 active Evidence 的 slides 评分：

```text
0.45 * title_match
+ 0.40 * normalized_bm25(body_text)
+ 0.15 * chapter_proximity
```

- 标题只取 fixture 的 `slide.title`；空标题为 0，不从正文猜标题。
- 正文 BM25 为 R0 BM25 的 slide-document 适配，tokenizer、IDF、`k1=1.2`、`b=0.75` 均未改变。
- 章节距离复用冻结的 `chapter_distance()`：优先 chapter tree distance，缺失时才使用同文档页码差。
- 全部三项都为 0 时 `abstain`；无 active Evidence 的 slide 不进入候选。
- 每个命中输出三个特征、原始 BM25、章节距离依据、Evidence IDs 与 citation keys。

配置 SHA-256：`3ff3845bbe2630514d75a07dcaccc9325758b37e5266698a2904550efd9a7a38`。

## 最终 test（35 knowledge points，仅运行一次）

| 指标 | 数值 |
| --- | ---: |
| Top-1 primary page 命中 | 0.5429 |
| Top-3 primary page 命中 | 0.8857 |
| Top-3 supporting/useful page 覆盖 | 0.7857 |
| Mapping MRR | 0.8376 |
| 已返回相关页的 Evidence binding accuracy | 1.0000 |

其中 Evidence binding accuracy 只在返回的 gold-relevant 页面上计算：返回的 Evidence 必须同时属于该页面并和该知识点的 qrel Evidence 相交。它不把 Top-K 中的负例误计为“没有可绑定 evidence”。

## 失败样例

后置 qrels 分析输出 16 个失败知识点：16 个 `mapping_wrong_page`、4 个 `primary_miss_at_3`、3 个 `useful_miss_at_3`。常见原因是课件 slide 标题稀缺（253 页中只有 22 页具有非空 fixture title），且同章节的 position feature 不能进一步区分页面；这不是靠伪造标题或 qrels 反向调权可以解决的问题。

完整结果和特征 trace 在：

- `research/product1_graph_retrieval/experiments/runs/m0_mapping_reviewed_silver_v0_2/test.run.jsonl`
- `research/product1_graph_retrieval/experiments/runs/m0_mapping_reviewed_silver_v0_2/test.evaluation.json`
- `research/product1_graph_retrieval/experiments/runs/m0_mapping_reviewed_silver_v0_2/test.failures.jsonl`

两次 validation 的 36 条排名记录字节一致（排除可变 runtime 字段），SHA-256 为 `5be7140c759aa8b4302a3cab2207a6ebf1b62709961d128bdb30bac106ad1781`。

## 下一步

可据此构建课程图谱的确定性骨架：仅从课程、章节、知识点、映射 slide 和 active Evidence 产生可追溯关系；不把相似度推断的 prerequisite/related 等候选关系发布为 accepted edge，更不做 GraphRAG。
