# Agent B：B-G0 实现与人工 Gold 门禁

> 状态日期：2026-07-16  
> B-R0：APPROVED  
> B-G0a micro-contract fixture：IMPLEMENTED，等待 P1-00/P1-10 复核  
> B-G0b human gold：BLOCKED，4 门真实课件及授权/隐私用途声明已到位；尚需冻结授权有效期与责任/证据记录，并完成人工 selection、OCR/原页复核、脱敏候选、真人双标与第三人仲裁  
> B-R1/B-R2/B-R3：未放行

## 1. 本轮实际边界

本轮只实现数据与评测基础设施，没有实现 tokenizer、BM25、知识点映射打分、Dense、RRF、图扩展或 GraphRAG。没有修改任何生产契约、生产代码、API、数据库、配置或依赖锁。

B-G0 被拆成两个不同证明层级：

| 层级 | 可以证明 | 不能证明 | 当前状态 |
| --- | --- | --- | --- |
| B-G0a micro contract | schema、hash、稳定 ID、引用闭合、课程闭包、offset/snippet、分级 qrels、指标代码和字节复现 | 任何算法效果 | 已实现 |
| B-G0b human gold | 在真实课程材料上比较 BM25/Dense/Hybrid/Graph | 自动生成标签不能替代人工判断 | 尚未完成 |

micro fixture 的 manifest 强制写入：

```json
{
  "dataset_level": "micro_contract",
  "gold": {
    "status": "synthetic_contract_oracle",
    "eligible_for_algorithm_comparison": false
  }
}
```

评测 CLI 对该 fixture 默认拒绝执行；只有显式传入 `--contract-test-only` 才运行，并在报告中写入 `contract_only_not_algorithm_comparison`。

## 2. B-G0a 已实现内容

- `product1-graph-retrieval-fixture/1.1` manifest 与 records/annotation/run JSON Schema；
- canonical JSON/JSONL、文件 SHA-256、fixture content hash；
- `research_evidence_id`、`research_chunk_id`、`research_query_id`、`research_slide_id`、`research_knowledge_point_id`；
- 与冻结 `citation/1.0` 兼容的 citation key 重算；
- source block、Evidence、chunk、slide、knowledge point、qrels 的引用闭合；
- active/stale、offset/snippet、课程范围、重复 ID、split 隔离检查；
- 公开索引输入与 gold-only 文件隔离；
- 授权来源预检、human selection schema、未标注 candidate 构建/验证和字节复现检查；
- 独立 retrieval/mapping 人工标注 packet、两人差异比较、分任务第三人仲裁检查；
- retrieval/mapping 离线评测脚本；
- P1-00/P1-10/B-R1 release gate。

micro fixture 当前规模：2 门脱敏合成课程、22 个 source block、22 条 Evidence、20 个 active chunk、18 个查询、10 个知识点、20 个 PPT 页。

这些数量只描述契约测试数据，不是生产数据或效果样本量。

## 3. Gold 隔离

索引与运行阶段只允许读取：

```text
source_blocks.jsonl
evidence.jsonl
corpus.jsonl
queries.jsonl
knowledge_points.jsonl
slides.jsonl
splits.json
```

以下文件只能在 run 文件已经冻结后由评测器读取：

```text
retrieval_query_labels.jsonl
retrieval_qrels.jsonl
mapping_qrels.jsonl
```

`queries.jsonl` 不包含 `answerable`、`answerability` 或 `expected_behavior`。运行 header 必须声明：

```json
{
  "gold_access_attestation": {
    "qrels_accessed_during_run": false,
    "query_labels_accessed_during_run": false
  }
}
```

若声明为 true、缺失或与 fixture manifest hash 不一致，评测器 fail-closed。Level A alias 必须标记 `synthetic_contract_fixture`；只有真实 Level B gold 才能标记 `human_confirmed_pre_split`。两者都要求 `frozen_before_split=true`，不得从 test qrels 反向生成。

## 4. 冻结标注口径

### 4.1 Retrieval qrels

- `2`：直接回答问题的核心证据；
- `1`：有用的部分支撑或上下文；
- `0`：不相关或显式 hard negative。

每个 `answerable` 查询至少有一个 relevance=2。Recall/MRR 使用 relevance>=1，并单报 direct-support Recall。

### 4.2 无答案类型

- `answerable`；
- `unanswerable_in_course`；
- `scope_not_available`；
- `evidence_stale_only`。

Recall/MRR 只在 `answerable` 上计算。评测同时按四类输出 answer/abstain rate，不能用总体平均掩盖错误作答或错误拒答。

### 4.3 查询分层

- `exact_term`；
- `definition`；
- `formula_or_code`；
- `paraphrase`；
- `cross_language_alias`；
- `multi_hop_relation`；
- `no_answer`。

micro fixture 覆盖全部分层。未来 human gold 也必须按层报告，不能只报总 Recall/MRR。

### 4.4 多页 PPT 映射

一个知识点允许多个 primary/supporting 页：

- relevance=2：primary slide；
- relevance=1：supporting slide；
- relevance=0：irrelevant hard negative。

每个知识点至少一个 primary 页；允许多个 primary 和多个 supporting。Top-1/Top-3 primary 与 Top-3 useful coverage 分开报告。

### 4.5 章节距离

冻结优先级如下，不在看完 validation 后改变：

1. 两侧都有同课程 `chapter_path`：距离为树边数，`len(a)+len(b)-2*LCP(a,b)`；
2. 缺章节树但属于同一 document 且都有 1-based 页码：距离为 `abs(page_a-page_b)`；
3. 其他情况：`unknown`，feature value 为 0，并保留 `missing=true`；
4. 跨课程 chapter path 直接报错，不计算距离；
5. 不把树距离和页差临时混合。

未来 B-R2 只能复用该定义，`chapter_proximity = 1/(1+distance)`。

## 5. Human gold 必须由真实团队完成

工具可以：

- 按 stable research ID 排序生成无算法 rank/score 的标注 packet；
- 校验两份 annotation 的候选集合一致；
- 拒绝相同 `member_id` 充当两名标注者；
- 计算原始一致率并生成分歧清单；
- 要求第三个不同 `member_id` 对 retrieval 与 mapping 分别完整仲裁；
- 在真人标注与仲裁完成后导出 gold candidate records；真实来源当前仅完成准备链，尚未执行该步骤。

工具不能证明 `member_id` 背后确实是人。P1-10 必须在工具之外核验真实团队身份、独立完成过程和仲裁记录。两个 Agent、同一个人两次填写、自动模型标签或 Codex 生成结果均不得计入两名人工标注者。

## 6. Release gate

B-R1 只能在以下条件全部满足后放行：

- dataset_level=`human_gold`；
- 至少两名真实团队成员独立标注；
- 第三人完成全部分歧仲裁；
- gold manifest 和所有文件 hash 冻结；
- P1-00 对 research sidecar、身份和字段语义书面确认；
- P1-10 复核 gold protocol、人员与运行隔离；
- manifest 的 `b_r1_release` 明确为 approved。

当前 micro fixture 执行 release checker 会返回 blocked，这是正确行为。B-R2 后续必须复用 B-R1 唯一 tokenizer/BM25 实现，不允许另写一套。任何生产契约调整仍需独立 ADR。

## 7. 验证命令

```powershell
.venv\Scripts\python.exe research/product1_graph_retrieval/tools/validate_fixture.py research/product1_graph_retrieval/datasets/micro_contract_v1
.venv\Scripts\python.exe -m unittest discover -s research/product1_graph_retrieval/tests -p "test_*.py" -v
.venv\Scripts\python.exe research/product1_graph_retrieval/tools/check_b_r1_release.py research/product1_graph_retrieval/datasets/micro_contract_v1
```

第三条当前预期退出码为 2，状态为 blocked；不得把它改成绿色占位。

