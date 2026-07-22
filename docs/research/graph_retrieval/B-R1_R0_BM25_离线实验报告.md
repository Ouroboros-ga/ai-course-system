# B-R1 / R0：课程隔离 BM25 离线实验报告

## 结论

R0 已作为一个可运行、可复核的离线研究基线完成。它不接入上传链路、数据库、API 或生产问答，也不包含 Dense、RRF、图扩展、reranker 或 LLM 生成。

实验使用 `reviewed_silver_v0_2`，因此结果的资格是 `reviewed_silver_offline_research_only`：可用于后续同一 Silver fixture 的工程比较，不能报告为人工 Gold 科学结论，更不构成生产接入授权。

## 固定实现

- 唯一分词器：`mixed-script-ngram/1.0`；NFKC + casefold，Latin/code token，CJK unigram + bigram。
- 索引：4 个独立 `course_id -> BM25Index`，先选课程索引，绝不全库检索后过滤。
- BM25：Lucene-positive IDF，`k1=1.2`，`b=0.75`。
- 同分排序：`score DESC, research_chunk_id ASC`。
- 候选资格：同课程、至少一个 active Evidence、Evidence 与 chunk 坐标闭合；不满足或没有正 BM25 分数时显式 `abstain`。
- 每个 hit 保留 `research_chunk_id`、Evidence IDs、页码、block、citation key 和 matched token trace。

固定配置 SHA-256：`47b2b8b1a992489877b151c61a49aadd31af92c6de5633e607a2950603fe05f3`。

Fixture manifest SHA-256：`ea1f660d0c73dff28f1815456a8ab683bde487d85db70f44b6a8c43c41063975`。

## 最终 test（20 queries，仅运行一次）

| 指标 | 数值 |
| --- | ---: |
| Recall@1 / @3 / @5 / @10 | 0.1111 / 0.3111 / 0.4000 / 0.5778 |
| Direct Recall@1 / @3 / @5 / @10 | 0.0667 / 0.4000 / 0.6000 / 0.8000 |
| MRR | 0.5034 |
| nDCG@5 / @10 | 0.3527 / 0.4222 |
| 跨课程污染率 | 0.0000 |
| 有污染 query 数 | 0 |
| Evidence 完整率 | 1.0000 |
| Citation key 有效率 | 1.0000 |
| 正确拒答率（5 个课程内无答案） | 0.0000 |
| 错误作答率（5 个课程内无答案） | 1.0000 |

索引包含 1,083 chunks、28,204 search tokens 和 4 个课程索引。该次运行记录的索引构建时间为 0.0112 秒，单 query P50/P95 为 0.000304/0.000478 秒；这是本机小型 fixture 的实验测量，不外推生产容量。

## 失败样例与解释

test 的后置 qrels 分析输出 9 个失败 query：5 个 `false_answer`、4 个 `miss_at_5`，其中 3 个同时是 `late_relevant_hit`。完整 machine-readable 样例在 `test.failures.jsonl`。

当前 BM25 的关键不足是：课程内“无答案”问题仍会与课程中的通用术语相交，因而出现有来源、可验证但不支持该问题的 hit。它们不是伪造 Citation（所有 Citation 均指向 active Evidence），但仍是错误作答。验证集上的分数和 query-term coverage 也不能把无答案样本与全部可回答样本可靠分开，所以没有使用 qrels 倒推一个看似更好的阈值。

这正是后续 Dense/Hybrid 和受限图增量应当检验的假设之一，而不是 R0 已经解决的能力。

## 可复核产物

- 配置：`research/product1_graph_retrieval/configs/r0_bm25_reviewed_silver_v0_2.json`
- validation run 与评测：`research/product1_graph_retrieval/experiments/runs/r0_bm25_reviewed_silver_v0_2/validation.*`
- 最终 test run、指标与失败样例：`research/product1_graph_retrieval/experiments/runs/r0_bm25_reviewed_silver_v0_2/test.*`
- 可复现性：两次 validation 的 20 条排名记录（排除刻意可变的计时字段）字节一致，SHA-256 为 `4ec34cfb973ad3998de8d8c181e33a5188f83d4f9f64a30306cedb2def6acaed`。

## 下一步

B-R2 可复用本轮唯一 tokenizer 和 BM25 实现，开始“标题 + BM25 + 章节位置”的知识点到 PPT 页面映射；不能另写分词或 BM25。R0 的 no-answer 失败必须作为后续方法的固定对照，而不能通过删除或改写测试样本掩盖。
