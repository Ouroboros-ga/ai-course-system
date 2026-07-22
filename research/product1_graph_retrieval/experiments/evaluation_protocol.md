# 检索、映射与图增量评测协议

> 协议版本：`graph-retrieval-eval/1.2`。  
> B-G0 已实现指标与隔离脚本，但未实现或运行任何检索/映射算法。micro contract 输出不得用于算法效果比较。

机器可检查的算法前置规格冻结在 `src/release_gate.py` 的
`ALGORITHM_PREPARATION_SPEC`。其 canonical JSON SHA-256 由 B-P0 preflight 输出；
文档与机器规格冲突时必须停止实现并先修正规格，不得由实现者自行选择解释。

## 1. 不可变比较条件

所有 R0-R4 run 必须共享：

- fixture manifest SHA-256；
- query IDs、qrels 与 split；
- course scope；
- chunk 粒度与 active Evidence 过滤；
- 每路候选深度与最终 TopK；
- 指标实现；
- Python 版本、操作系统信息、seed；
- 失败样例输出格式。
- manifest 的 `access_policy.index_inputs` 与 `gold_only` 分区；
- run header 的 configuration hash 与 gold-access attestation；
- test qrels 只在 run 文件冻结后由 evaluator 读取。

任何一项不同都视为新实验组，不得直接把指标差写成算法提升。

## 2. 实验矩阵

| Run | 召回/融合 | 当前状态 | 允许的输入 | 明确禁止 |
| --- | --- | --- | --- | --- |
| R0 | BM25 | B-R1 实现目标 | frozen corpus/evidence/query | LLM、embedding、全局后过滤 |
| M0 | 标题 + BM25 + 章节位置 | B-R2 实现目标 | accepted KP + frozen slides | LLM、embedding、无证据映射 |
| R1 | Dense | 设计完成，未实现 | 同一 corpus/query | 未固定模型 revision、在线 API |
| R2 | BM25 + Dense + RRF | 设计完成，未实现 | R0/R1 同候选预算 | test 集调参、跨 scope 融合 |
| R3 | BM25 + Dense + Graph | 设计完成，未实现 | R2 + frozen course graph | GraphRAG、LLM 抽图、跨课程边 |
| R4 | R3 + Rerank | 可选设计 | 同候选与 Evidence | 真实外部 rerank 服务 |

R3 的“Graph”只是一跳、受 relation budget 限制的 frozen graph expansion，不是 Microsoft GraphRAG 或生产 GraphRAG。

## 3. 运行配置

每个 run 保存 canonical JSON 配置：

```json
{
  "protocol_version": "graph-retrieval-eval/1.2",
  "run_name": "r0_bm25_v1",
  "fixture_manifest_sha256": "<hex>",
  "git_commit": "<sha>",
  "python_version": "3.12.x",
  "seed": 0,
  "candidate_k": 50,
  "report_top_k": [1, 3, 5, 10],
  "tokenizer": {
    "version": "mixed-script-ngram/1.0",
    "unicode": "NFKC",
    "case_normalization": "casefold",
    "latin_pattern": "[a-z0-9]+(?:[._:/#+-][a-z0-9]+)*",
    "cjk_ranges": ["3400-4DBF", "4E00-9FFF", "F900-FAFF"],
    "cjk_ngrams": [1, 2],
    "query_term_frequency": "unique_terms_first_occurrence_order"
  },
  "bm25": {
    "idf": "lucene-positive",
    "k1": 1.2,
    "b": 0.75
  },
  "tie_break": ["score_desc", "research_chunk_id_asc"],
  "float_serialization_digits": 12
}
```

配置文件自身计算 SHA-256，并写入 report。不得在运行结束后改配置而保留原 run ID。

## 4. R0：BM25 预注册实现

### 4.1 课程隔离

索引结构是 `Dict[course_id, BM25Index]`。先用 `query.course_id` 选择唯一 index，再计算 score。不存在 course index 时返回：

```json
{"status":"abstain","abstain_reason":"scope_not_available","hits":[]}
```

禁止先对所有课程评分再过滤。

### 4.2 分词下界

- source text 保持不变；仅搜索视图做 NFKC 与小写规范化。
- 搜索视图依次做 NFKC 和 Unicode `casefold`；拉丁/数字/代码 token 使用
  `[a-z0-9]+(?:[._:/#+-][a-z0-9]+)*`。
- CJK 范围固定为 U+3400–U+4DBF、U+4E00–U+9FFF、U+F900–U+FAFF；连续
  CJK 字符按原顺序产生 unigram + 相邻 bigram。
- 不用动态词典、网络分词器或按 test query 加词。
- token trace 只保存 token 与 source chunk ID，不保存敏感数据。
- query 重复 token 只保留首次出现的一项；document TF 统计全部出现次数。

### 4.3 BM25 公式

首个实现采用正 IDF 变体：

```text
idf(t) = log(1 + (N - df(t) + 0.5) / (df(t) + 0.5))

score(q, d) = Σ_t∈q idf(t) *
  tf(t,d) * (k1 + 1) /
  (tf(t,d) + k1 * (1 - b + b * dl(d) / avgdl))
```

重复 query token 不重复累加 BM25 项；起始配置 `k1=1.2, b=0.75`，validation 可运行预注册小网格：

- `k1 ∈ {0.9, 1.2, 1.5, 1.8}`
- `b ∈ {0.5, 0.75, 0.9}`

test 只运行 validation 已选配置和起始配置。

### 4.4 hit 资格

候选必须同时满足：

- chunk course 等于 query course；
- 至少一个 active EvidenceRecord；
- artifact/document/unit/block/page 引用完整；
- score 大于 0，或满足未来注册的 threshold。

没有合格候选时 abstain。无 Evidence 的高分文本也不得返回。

## 5. M0：知识点—PPT 页映射

候选 slide 先按 course 过滤。每个 pair 输出：

```text
title_match        ∈ [0, 1]
normalized_bm25    ∈ [0, 1]
chapter_proximity  ∈ [0, 1]
```

起始公式：

```text
mapping_score =
    0.45 * title_match
  + 0.40 * normalized_bm25
  + 0.15 * chapter_proximity
```

定义：

- `title_match`：canonical label 和人工确认、split 前冻结的 alias 使用 B-R1 tokenizer。
  任一规范化标签与标题完全相等时为 1；否则取各标签 token 集与标题 token 集的
  Sorensen-Dice 最大值 `2*|A∩B|/(|A|+|B|)`；任一必要 token 集为空时该项为 0。
- `normalized_bm25`：对同一知识点、同课程候选页的 raw BM25 分数做确定性归一化；全零时为 0。
- 两侧有同课程 chapter path：`tree_distance=len(a)+len(b)-2*LCP(a,b)`；
- 缺 chapter path、同 document 且页码均为 1-based：使用 `abs(page_a-page_b)`；
- 其他情况为 unknown，feature=0、missing=true；跨课程 path fail-closed；
- `chapter_proximity = 1 / (1 + distance)`；树距离和页差不混合。
- mapping 总分相同时按 `research_slide_id` 升序稳定排序。

必须比较：title only、BM25 only、chapter only、等权、起始权重。权重与 abstain margin 只在 validation 选择。

硬 abstain：

- knowledge point 没有 active Evidence；
- 先剔除没有 active Evidence 的 candidate slide；若没有合格 candidate slide 剩余则 abstain；
- 所有候选三项信号都为 0。

软 abstain：最高分低于 validation threshold，或 top-1/top-2 margin 小于预注册阈值。

## 6. R1：Dense 设计

- 模型名称、revision、权重文件 SHA-256、tokenizer、pooling、最大长度、归一化方式全部写入配置。
- 禁止在线 embedding API。
- corpus embedding 离线缓存，缓存以 fixture + model + preprocessing hash 命名。
- 首轮使用 exact cosine/dot-product search；ANN 单独做性能实验。
- 字符串 ID 与向量 ordinal 使用只读映射表，返回时恢复完整 EvidenceRecord。
- 同一模型至少两次运行验证字节级排序一致；硬件导致非确定时明确记录容差与限制。

## 7. R2：RRF Hybrid 设计

每路都在同一 course scope 内取相同 candidate_k，再融合：

```text
rrf_score(d) = Σ_s weight_s / (k + rank_s(d))
```

预注册：

- `k ∈ {20, 60, 100}`；
- 等权；可选 sparse:dense `2:1, 1:1, 1:2`；
- 稳定去重键为 research chunk ID；
- scope 或 Evidence identity 不一致立即 fail-closed；
- tie-break 为 `(-rrf_score, research_chunk_id)`。

每个 hit 输出各来源 rank、分量、最终 score，不能丢 Evidence IDs。

## 8. R3：受限图扩展设计

入口只来自 R2 已命中的知识点/SourceBlock。扩展规则：

- 同一个 `CourseGraphSnapshotEnvelope`；
- accepted node/relation；
- relation 的全部 evidence_ids active；
- 一跳；
- 每种 relation 有独立预算；
- 只允许预注册关系，例如 `PREREQUISITE_OF/HAS_EXAMPLE/USES_FORMULA/SUPPORTED_BY/APPEARS_ON`；
- `RELATED_TO` 默认低权或关闭，避免 hub 漂移。

图候选带完整路径解释：

```text
seed_chunk -> seed_node -> relation -> neighbor_node -> evidence -> chunk
```

图路径没有 active Evidence 时不产生候选。最终仍限制同一 report TopK。

## 9. 检索指标定义

设查询 `q` 的 gold Evidence 集为 `G_q`，TopK 返回 Evidence 集为 `R_q^K`。

### Recall@K

```text
Recall@K(q) = |G_q ∩ R_q^K| / |G_q|
Macro Recall@K = mean over answerable queries
```

去重按 research_evidence_id，不按 hit 数。分别报告 relevance>=1 和 direct-support relevance=2。

### MRR

```text
RR(q) = 1 / rank_of_first_relevant_hit
MRR = mean RR over answerable queries
```

TopK 内无 relevant 则 RR=0。

### nDCG@K

使用 qrels 的 graded relevance 0/1/2。gain 和 discount 公式在指标代码中冻结；建议 `gain=2^rel-1`、`discount=log2(rank+1)`。

### Success@K

`TopK` 至少一个 relevant evidence 的查询比例。作为直观补充，不替代 Recall。

## 10. 安全与可信指标

### 跨课程污染率

```text
wrong_course_hits / all_returned_hits
```

门禁必须精确为 0；同时报告 `queries_with_any_contamination`，也必须为 0。

### Evidence 完整率

完整 hit 必须通过 research_evidence_id、artifact/document/unit/block/version/page/status、reference 和 snippet 校验：

```text
complete_evidence_hits / all_returned_hits
```

门禁为 1.0。

### Citation key 有效率

非 abstain hit 的 key 必须可由同一 active evidence 重算且非空：

```text
valid_recomputable_keys / all_returned_hits
```

门禁为 1.0。这里不创建带 statement 的 Citation，也不把 key 有效写成语义支撑正确。

### 无答案分型

评测按 `answerable | unanswerable_in_course | scope_not_available | evidence_stale_only` 分层输出 answer/abstain rate。Recall/MRR 只在 answerable 查询上计算；不得用合并后的正确拒答率掩盖某一种无答案类型的错误作答。

### 正确拒答率

```text
correct_abstains / all_unanswerable_queries
```

### 错误拒答率

```text
answerable_queries_abstained / all_answerable_queries
```

同时输出原因码分布。不得通过一律 abstain 换取零污染/零伪 Citation。

## 11. 映射指标

- Top-1 primary accuracy：首位是否命中 relevance=2 slide。
- Top-3 primary accuracy：前三是否含 relevance=2 slide。
- Top-3 useful coverage：前三覆盖 relevance>=1 gold slides 的比例。
- Mapping MRR：第一个 relevant slide 的 reciprocal rank。
- Evidence binding accuracy：返回 mapping 的 evidence_ids 是否属于 gold slide/knowledge point 交集。
- Ambiguous abstain precision/recall：对标注为 ambiguous/no-map 的样例评估。

教师接受率、平均修改次数不在冻结 fixture 自动产生；只有未来真实教师盲审后才能报告。

## 12. 运行成本指标

- index build wall time；
- query latency P50/P95；
- peak RSS；
- serialized index bytes；
- corpus/query token count；
- Dense 额外记录 embedding cache bytes 与硬件。

计时规则：固定 warm-up 次数，单线程基线，至少重复 5 次，报告环境。小 fixture 的延迟只叫实验延迟，不外推生产容量。

## 13. 统计与报告

- 保存每查询指标，不只保存聚合值。
- R1/R2/R3 相对 R0/R2 使用 paired per-query delta。
- 可用固定 seed 的 paired bootstrap 给 95% CI；样本太小时只报告区间与方向，不宣称显著。
- 所有 metric 以原始分数和绝对差报告；相对提升仅作补充。
- 若 CI 包含 0、不同 query 类型方向相反或安全指标退化，结论写“证据不足/存在权衡”。

## 14. 失败样例格式

每个失败写 JSONL：

```json
{
  "run_id": "r0_bm25_v1",
  "research_query_id": "rq_<24 hex>",
  "failure_types": ["miss_at_5"],
  "expected_research_evidence_ids": ["rev_<24 hex>"],
  "returned": [
    {
      "rank": 1,
      "research_chunk_id": "rch_<24 hex>",
      "course_id": "course_alpha",
      "research_evidence_ids": ["rev_<24 hex>"],
      "score": 1.234,
      "feature_trace": {"matched_terms": ["查找"]}
    }
  ],
  "diagnosis": "generic_term_dominated",
  "gold_issue_suspected": false
}
```

标准 failure types：

- `cross_course_contamination`
- `missing_evidence`
- `invalid_citation_key`
- `miss_at_5`
- `late_relevant_hit`
- `false_abstain`
- `false_answer`
- `mapping_wrong_page`
- `graph_topic_drift`
- `gold_ambiguity`

## 15. 晋级门禁

### B-R1 完成

- 污染率 0；
- Evidence 完整率 1.0；
- Citation key 有效率 1.0；
- 无证据 query 不产生 Citation；
- 两次运行结果字节相同；
- Recall@K、MRR、拒答、成本和失败样例真实输出。

### B-R2 完成

- 同样安全门禁全过；
- 输出 Top-1/Top-3/MRR 与 feature breakdown；
- 权重/阈值只用 validation；
- 不使用 LLM/embedding。

### B-R3 实验可提交 P1-10

- R0/R1/R2/R3 公平条件一致；
- 图扩展不改变 gold、TopK 或 course scope；
- paired 结果、CI、成本和失败样例齐全；
- 不宣称 Graph 必然优于其他方法；
- 研究代码仍未接生产。
