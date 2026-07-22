# 冻结 fixture 与 human gold 数据规范

> Fixture schema：`product1-graph-retrieval-fixture/1.1`。  
> Research sidecar：`product1-graph-retrieval-research-sidecar/1.0`。  
> 本规范定义研究输入，不修改或冒充任何生产契约。

> v1.1 机器可执行口径以 `../schemas/`、`../src/fixture_io.py` 和
> [B-G0 实现与人工 Gold 门禁](../../../docs/research/graph_retrieval/B-G0实现与人工Gold门禁.md)
> 为准。下文示例中的研究身份均使用显式
> `research_*` 字段替代；`answerability` 已从公开 queries 移入 gold-only 文件。

## 1. 数据包布局

每个冻结数据包使用以下非空文件：

```text
datasets/<fixture_name>/
├── manifest.json
├── source_blocks.jsonl
├── corpus.jsonl
├── evidence.jsonl
├── queries.jsonl
├── retrieval_query_labels.jsonl  # gold-only
├── retrieval_qrels.jsonl         # gold-only
├── knowledge_points.jsonl
├── slides.jsonl
├── mapping_qrels.jsonl           # gold-only
└── splits.json
```

gold 与 corpus 分开存储，避免实现阶段无意读取答案。数据包创建后只读；任何修订生成新版本和新 manifest，不原地覆盖。

## 2. manifest.json

必填字段：

```json
{
  "fixture_schema_version": "product1-graph-retrieval-fixture/1.1",
  "fixture_id": "fixture_demo_v1",
  "created_at": "2026-07-16T00:00:00Z",
  "source_contracts": {
    "document_ir": "document-ir/1.0",
    "evidence": "evidence/1.0",
    "citation": "citation/1.0",
    "education_graph": "edu-graph/1.0"
  },
  "course_ids": ["course_alpha", "course_beta"],
  "files": {
    "corpus.jsonl": "sha256:<hex>",
    "evidence.jsonl": "sha256:<hex>",
    "queries.jsonl": "sha256:<hex>"
  },
  "normalization": {
    "unicode": "NFKC-for-search-only",
    "source_text_mutated": false,
    "ppt_page_base": 1
  },
  "gold": {
    "status": "synthetic_contract_oracle",
    "eligible_for_algorithm_comparison": false
  },
  "governance": {
    "p1_00": {"status": "pending"},
    "p1_10": {"status": "pending"},
    "b_r1_release": "blocked_until_both_approved"
  },
  "contains_production_data": false,
  "contains_personal_data": false
}
```

约束：

- `course_ids` 至少两个。
- `files` 覆盖数据包内除 manifest 外的全部文件，并记录字节 SHA-256。
- `contains_production_data` 和 `contains_personal_data` 必须为 `false`。
- 时间戳不参与任何 stable research ID。

## 3. evidence.jsonl

一行一个研究 `EvidenceRecord`。它嵌入 `evidence/1.0` 字段并增加 sidecar ID：

```json
{
  "research_evidence_id": "rev_8a9d...",
  "course_id": "course_alpha",
  "artifact_id": "art_example",
  "document_id": "doc_example",
  "unit_id": "unit_slide_0003",
  "block_id": "blk_pptx_s3_sh2",
  "version_ref": "fixture-document-v1",
  "page_or_slide": 3,
  "char_start": 0,
  "char_end": 24,
  "text_snippet": "二分查找每次排除一半搜索区间。",
  "status": "active",
  "metadata": {
    "unit_type": "slide",
    "research_sidecar": true
  }
}
```

`research_evidence_id` 研究算法：

```text
payload = join_with_NUL(
  course_id,
  artifact_id,
  document_id,
  unit_id,
  block_id,
  version_ref,
  char_start_or_empty,
  char_end_or_empty
)
research_evidence_id = "rev_" + sha256(utf8(payload))[0:24]
```

它是研究 ID，不是冻结 `EvidenceSpan` 字段。所有字符串先验证非空，但 source ID 不做 NFKC 改写。

fail-closed 规则：

- ID 引用必须能解析到同一个 DocumentIR source/unit/block。
- active Evidence 的 `version_ref` 和 `page_or_slide` 必填。
- `0 <= char_start < char_end <= len(canonical_block_text)`。
- `text_snippet` 必须等于 block text 对应切片；block-level Evidence 可把两个 char 字段均设为 null，但 snippet 仍需与 canonical text 一致。
- stale/suspended 不进入可检索 corpus。

## 4. corpus.jsonl

一行一个可检索 chunk，首版一个 active Evidence span 对应一个 chunk；不在 B-R1 合并多 block：

```json
{
  "research_chunk_id": "rch_4f20...",
  "course_id": "course_alpha",
  "artifact_id": "art_example",
  "document_id": "doc_example",
  "unit_id": "unit_slide_0003",
  "unit_type": "slide",
  "unit_index": 3,
  "block_id": "blk_pptx_s3_sh2",
  "block_type": "paragraph",
  "research_evidence_ids": ["rev_8a9d..."],
  "page_or_slide": 3,
  "chapter_id": "chapter_search",
  "chapter_path": ["course_alpha", "chapter_search", "section_binary_search"],
  "title": "二分查找",
  "text": "二分查找每次排除一半搜索区间。",
  "text_sha256": "<hex>",
  "language": "zh-CN"
}
```

`research_chunk_id` 研究算法：

```text
payload = join_with_NUL(course_id, document_id, unit_id, block_id, sorted(research_evidence_ids), text_sha256)
research_chunk_id = "rch_" + sha256(utf8(payload))[0:24]
```

约束：

- `course_id` 必须属于 manifest。
- `research_evidence_ids` 非空且全部 active、同课程、同 source block。
- `text_sha256` 对未改写 source text 计算。
- 搜索规范化在运行时另存 token trace，不覆盖 `text`。
- 同一个 `research_chunk_id` 不能出现在两个课程。
- B-R1 不把一个 chunk 跨页合并，避免 page/Citation 语义不清。

## 5. queries.jsonl

查询文件不含 gold：

```json
{
  "research_query_id": "rq_<24 hex>",
  "course_id": "course_alpha",
  "text": "二分查找为什么每次能缩小一半范围？",
  "query_type": "explanation",
  "query_stratum": "paraphrase",
  "tags": ["paraphrase", "zh"]
}
```

字段枚举：

- `query_type`：`definition | explanation | formula | example | exercise | prerequisite | misconception | locate | no_evidence`。
- `query_stratum`：`exact_term | definition | formula_or_code | paraphrase | cross_language_alias | multi_hop_relation | no_answer`。

必须包含的负例标签：

- `cross_course_collision`：错误课程有同名/同文内容；
- `no_evidence`：课程内无可支持证据；
- `stale_only`：只有 stale evidence；
- `exact_symbol`：公式/API/代码符号；
- `cross_language_alias`：中英别名；
- `ambiguous`：多个页面都可能相关，需要 TopK 或 abstain。

### Gold-only answerability

`retrieval_query_labels.jsonl` 单独保存：`answerable | unanswerable_in_course | scope_not_available | evidence_stale_only`。Recall/MRR 只在 answerable 上计算，其余类型分别报告拒答和错误作答。公开 `queries.jsonl` 不得出现这些标签。

## 6. retrieval_qrels.jsonl

每行一个 query—Evidence relevance 判断：

```json
{
  "research_query_id": "rq_<24 hex>",
  "research_evidence_id": "rev_8a9d...",
  "relevance": 2,
  "judgment": "direct_support",
  "adjudication_note": "定义与缩小区间原因均在该块中"
}
```

`relevance`：

- `2`：直接支撑；
- `1`：部分支撑/有用上下文；
- `0`：不相关，仅在 hard-negative 审计时显式记录。

Recall/MRR 默认把 `relevance >= 1` 视为 relevant；同时单报 `relevance == 2` 的 direct-support Recall。

## 7. knowledge_points.jsonl

```json
{
  "research_knowledge_point_id": "rkp_<24 hex>",
  "course_id": "course_alpha",
  "canonical_label": "二分查找",
  "aliases": ["折半查找", "Binary Search"],
  "chapter_id": "chapter_search",
  "chapter_path": ["course_alpha", "chapter_search"],
  "research_evidence_ids": ["rev_8a9d..."],
  "review_status": "accepted"
}
```

约束：首版只映射 `review_status=accepted` 且有 active Evidence 的知识点。Level A aliases 必须标记 `synthetic_contract_fixture`；Level B aliases 必须由真实教师/标注者确认并标记 `human_confirmed_pre_split`。两者均需在 split 前冻结，不用 LLM 自动扩展。

## 8. slides.jsonl

一行一个 PPT slide，由 `DocumentUnit(unit_type=slide)` 与其 blocks 确定性投影：

```json
{
  "research_slide_id": "rsl_<24 hex>",
  "course_id": "course_alpha",
  "document_id": "doc_example",
  "unit_id": "unit_slide_0003",
  "slide_number": 3,
  "chapter_id": "chapter_search",
  "chapter_path": ["course_alpha", "chapter_search"],
  "title": "二分查找",
  "body_text": "二分查找每次排除一半搜索区间。",
  "block_ids": ["blk_pptx_s3_sh1", "blk_pptx_s3_sh2"],
  "research_evidence_ids": ["rev_8a9d..."]
}
```

约束：

- `slide_number` 1-based，并等于原 `page_or_slide`。
- 标题优先来自 `block_type=title/heading`；没有可靠标题时为空，不用首段伪造。
- body 按 DocumentUnit reading order 连接，并保留 block 分界映射。
- slide ID 由 `course_id + document_id + unit_id` 的 SHA-256 派生。

## 9. mapping_qrels.jsonl

```json
{
  "research_knowledge_point_id": "rkp_<24 hex>",
  "research_slide_id": "rsl_<24 hex>",
  "relevance": 2,
  "judgment": "primary_teaching_slide",
  "research_evidence_ids": ["rev_8a9d..."]
}
```

一个知识点可以有多个相关页：primary 页 relevance=2，补充例题/复习页 relevance=1。Top-1 以是否命中任一 relevance=2 页为主；Top-3 同时报 relevance>=1 coverage。

## 10. 章节距离冻结定义

1. 两侧有同课程 `chapter_path`：`tree_distance=len(a)+len(b)-2*LCP(a,b)`；
2. 缺章节树但属于同一 document 且页码均为 1-based：`page_gap=abs(page_a-page_b)`；
3. 其他情况返回 `unknown`，proximity=0，missing=true；
4. 跨课程 path fail-closed；
5. 不混合树距离和页差。未来 B-R2 固定使用 `chapter_proximity=1/(1+distance)`。

## 10A. graph_snapshots.jsonl（B-R3 未放行）

B-R3 使用的外层 envelope，不修改 `GraphSnapshot`：

```json
{
  "envelope_schema_version": "course-graph-snapshot-envelope/1.0",
  "course_id": "course_alpha",
  "source_snapshot_id": "snapshot_fixture_001",
  "content_sha256": "<canonical-json-sha256>",
  "nodes": {},
  "relations": {},
  "evidence_index": {
    "rev_8a9d...": {
      "status": "active",
      "block_id": "blk_pptx_s3_sh2"
    }
  }
}
```

加载门禁：

- 所有 node/relation 必须 accepted；
- 所有 `research_evidence_ids` 在 envelope evidence index 中存在且 active；
- 所有 source/target node 存在；
- prerequisite 图无环；
- 不接受指向另一 course envelope 的边；
- canonical JSON 重算哈希必须等于 `content_sha256`。

## 11. splits.json

```json
{
  "split_version": "1.1",
  "train_query_ids": [],
  "validation_query_ids": ["rq_<validation 24 hex>"],
  "test_query_ids": ["rq_<test 24 hex>"],
  "validation_knowledge_point_ids": ["rkp_<validation 24 hex>"],
  "test_knowledge_point_ids": ["rkp_<test 24 hex>"],
  "policy": "thresholds_and_weights_use_validation_only",
  "test_gold_access": "evaluation_only_after_run_freeze"
}
```

- BM25 参数、mapping 权重、RRF 参数和 abstain threshold 只在 validation 调整。
- test 只运行已注册配置，不反复看结果调参。
- 每个 split 都要覆盖多课程与污染负例；如按课程外推评测，另建明确的 held-out-course split。

## 12. 标注流程

1. 标注者先看 query 与课程内候选，不看算法排序。
2. 分别判断 direct/partial/not relevant。
3. 对 mapping 标注 primary/supplementary/not relevant。
4. 至少两名真实团队成员独立完成；两个 Agent、同一人重复填写或模型标签不得冒充人工 gold.
5. 第三名真实团队成员仲裁全部分歧，P1-10 在工具之外核验身份与过程。
6. 保存分歧原因：漏标、页粒度争议、概念边界、证据失效、课程归属错误。
7. gold 修订只发布新 fixture 版本，并说明旧结果不可直接横比。

## 13. 数据质量验收

在任何 baseline 运行前必须全过：

- JSON/JSONL schema 与 UTF-8 校验；
- manifest 哈希校验；
- DocumentIR unknown-major fail-closed；
- source/unit/block reference integrity；
- duplicate ID 检查；
- Evidence offset/snippet/status 校验；
- 每个可检索 chunk 至少一个 active Evidence；
- course scope 闭包校验；
- gold 中的 query/evidence/slide/kp 引用全部存在；
- 至少一个 cross-course collision 和一个 no-evidence query；
- 两次加载、canonical serialize 的字节结果一致。
