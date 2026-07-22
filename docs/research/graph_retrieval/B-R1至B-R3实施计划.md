# Agent B：B-R1 至 B-R3 算法实施与消融计划

> 前置：B-R0 已批准；当前只授权 B-G0，不代表 B-R1/B-R2/B-R3 已放行。  
> 生产集成 Owner：P1-09；独立质量门禁：P1-10；契约治理：P1-00。  
> Agent B 只写 `research/product1_graph_retrieval/**` 与 `docs/research/graph_retrieval/**`。

## 1. 总体依赖顺序

```text
B-G0 fixture/gold 冻结
  -> B-R1 BM25 + Evidence + abstain
  -> B-R2 知识点—PPT 映射
  -> B-G1 P1-10 基线复核
  -> B-R3a Dense exact
  -> B-R3b RRF Hybrid
  -> B-R3c 受限图扩展
  -> B-G2 paired ablation
  -> 研究 Provider 候选
  -> P1-10 独立验证
  -> P1-09 才可申请 Shadow
```

不在本计划中实现 GraphRAG、LLM 抽图、社区摘要、生产 API、ORM、Migration 或前端。

## 2. 文件所有权

| 范围 | Owner | Agent B 权限 |
| --- | --- | --- |
| `research/product1_graph_retrieval/**` | Agent B | 唯一写入，可新增研究代码、fixture、tests、run/report |
| `docs/research/graph_retrieval/**` | Agent B | 唯一写入，可更新研究报告与实施记录 |
| `backend/app/**` | 各生产契约 Owner / P1-09 | 只读；禁止修改 |
| `backend/tests/product1/**` | P1-10/既有 Owner | 禁止修改 |
| `frontend/**` | 前端/P1-09 | 禁止修改 |
| `docs/refactor/product1/contracts/registry.md` | P1-00 | 只读；发现缺口只提交建议 |
| 生产配置、依赖、锁、数据库 | P1-09/平台 Owner | 禁止修改或读取生产状态 |

共享契约不由 Agent B “顺手修复”。需要晋级的变更以 ADR 建议交 P1-00，不在研究分支实现。

## 3. 目标研究代码布局

仅在相应里程碑开始时创建非空文件：

```text
research/product1_graph_retrieval/
├── schemas/                    # B-G0 JSON Schema
├── src/
│   ├── canonical.py            # B-G0 canonical JSON/hash
│   ├── identities.py           # B-G0 research IDs/citation key
│   ├── fixture_io.py           # B-G0 strict loader/validator
│   ├── micro_fixture.py        # B-G0 Level-A generator
│   ├── annotation.py           # B-G0 human workflow
│   ├── evaluation.py           # B-G0 offline metrics
│   ├── chapter_distance.py     # B-G0 frozen feature contract
│   ├── release_gate.py         # B-G0 P1-00/P1-10 gate
│   ├── tokenizer.py            # B-R1 才创建
│   ├── bm25.py                 # B-R1 才创建
│   ├── retrieve.py             # B-R1 才创建
│   ├── mapping.py              # B-R2 才创建
│   ├── dense.py                # B-R3 才创建
│   ├── fusion.py               # B-R3 才创建
│   └── graph_expand.py         # B-R3 才创建
├── tools/
├── tests/
├── datasets/micro_contract_v1/
├── experiments/
└── reports/
```

不提前创建空类、空 Provider 或占位目录。

## 4. B-G0：fixture 与 gold 冻结门禁

当前状态：B-G0a 已实现；B-G0b、P1-00、P1-10 均未完成，B-R1 保持 blocked。

### 修改范围

- `research/product1_graph_retrieval/datasets/<fixture>/**`
- `research/product1_graph_retrieval/src/fixture_io.py`
- `research/product1_graph_retrieval/src/identities.py`
- `research/product1_graph_retrieval/src/annotation.py`、`evaluation.py`、`release_gate.py`
- `research/product1_graph_retrieval/schemas/**`、`tools/**`
- `research/product1_graph_retrieval/tests/test_fixture_*.py`
- `research/product1_graph_retrieval/reports/fixture_audit.md`

### 实施内容

1. 按 fixture spec 准备至少两门脱敏课程。
2. 从 frozen DocumentIR/Evidence JSON 生成 corpus/evidence/slides sidecar。
3. 实现 schema、manifest、hash、reference、offset/snippet、course closure 校验。
4. 至少两名真实团队成员独立完成 retrieval/mapping qrels，第三名真实成员仲裁；两个 Agent 不得冒充人工 gold。
5. 冻结 validation/test split。

### 风险

- gold 漏标被误判为检索 false positive；
- 页码基数混淆；
- 同一 block 被错误分配到多个 course；
- 研究 `research_evidence_id` 被误认为生产字段。

### 验证命令

```powershell
.venv\Scripts\python.exe -m unittest discover -s research/product1_graph_retrieval/tests -p "test_*.py" -v
.venv\Scripts\python.exe research/product1_graph_retrieval/tools/validate_fixture.py research/product1_graph_retrieval/datasets/micro_contract_v1
.venv\Scripts\python.exe research/product1_graph_retrieval/tools/check_b_r1_release.py research/product1_graph_retrieval/datasets/micro_contract_v1
```

### 完成标准

- 两次加载并 canonical serialize 字节相同；
- manifest 全文件哈希通过；
- 所有 source/unit/block/evidence/qrels 引用闭合；
- 至少覆盖 cross-course collision、no-evidence、stale-only；
- 标注一致性和仲裁数量真实记录；
- P1-00 确认 sidecar 口径，P1-10 接受 gold protocol。

### 回滚

fixture 是新增、版本化研究数据。发现错误时停止使用旧 fixture，发布新 `fixture_id`；保留旧 manifest 和失效说明，不原地篡改，以便旧 run 可审计。

## 5. B-R1：课程隔离 BM25 baseline

### B-R1.1 确定性 tokenizer

修改：

- `src/tokenizer.py`
- `tests/test_tokenizer.py`
- `experiments/configs/r0_bm25_default.json`

实现：

- NFKC search view，不修改 source text；
- 拉丁/数字/代码 token；
- CJK unigram + bigram；
- 固定 stopword 策略（首版建议无动态 stopword）；
- tokenizer version 与 token trace。

风险：CJK unigram 产生高频噪声、公式符号丢失、不同 Unicode 表示排序漂移。

验证：

```powershell
.venv\Scripts\python.exe -m pytest research/product1_graph_retrieval/tests/test_tokenizer.py -q
```

完成：中英、全半角、公式、代码标识符 golden cases 全过；同输入字节级同 token 输出。

回滚：切回上一 tokenizer version；旧 run 仍绑定旧配置 hash。

### B-R1.2 BM25 core

修改：

- `src/bm25.py`
- `tests/test_bm25.py`

实现：

- 无新增依赖的 inverted index；
- 明确 BM25 公式、`k1/b`；
- 稳定排序 `(-score, chunk_id)`；
- index stats 和可解释 matched terms；
- 每 course 独立 index，不允许全局 candidate 后过滤。

风险：公式/IDF 变体与开源库不一致、浮点 tie、不正确计算重复 query term。

验证：

```powershell
.venv\Scripts\python.exe -m pytest research/product1_graph_retrieval/tests/test_bm25.py -q
.venv\Scripts\python.exe -m pytest research/product1_graph_retrieval/tests/test_course_isolation.py -q
```

完成：手算小语料对齐；相同配置结果稳定；故障注入的错误课程文本永不进入候选。

回滚：研究 index 可删除重建，无数据库或生产回滚。

### B-R1.3 Evidence-preserving result 与 abstain

修改：

- `src/retrieve.py`
- `src/identities.py`
- `tests/test_evidence_preservation.py`
- `tests/test_abstain.py`

实现：

- `ResearchQuery -> RunResult`；
- 每个 hit 恢复 evidence/page/block/version；
- citation key 只在 active、完整 Evidence 上计算；
- `empty_query/scope_not_available/no_lexical_match/no_active_evidence` reason codes；
- abstain hits 为空，不创建 Citation。

风险：把结构完整误当语义正确、score 高但 evidence stale、同文本 side table 错绑。

验证：

```powershell
.venv\Scripts\python.exe -m pytest research/product1_graph_retrieval/tests/test_evidence_preservation.py -q
.venv\Scripts\python.exe -m pytest research/product1_graph_retrieval/tests/test_abstain.py -q
```

完成：污染率 0、Evidence 完整率 1.0、citation key 重算率 1.0；所有无证据路径 abstain。

回滚：关闭/删除研究 runner，不影响生产 Gateway。

### B-R1.4 指标与报告

修改：

- `src/metrics.py`
- `tests/test_metrics.py`
- `experiments/runs/<run_id>/**`
- `reports/b_r1_bm25_report.md`

实现：Recall@1/3/5/10、MRR、nDCG、Success、污染、Evidence/Citation 完整、拒答、P50/P95、RSS、index bytes、failure JSONL。

风险：多相关证据重复计数、unanswerable 混入 Recall 分母、只报平均分。

验证：

```powershell
.venv\Scripts\python.exe -m pytest research/product1_graph_retrieval/tests/test_metrics.py -q
.venv\Scripts\python.exe -m research.product1_graph_retrieval.src.retrieve --config research/product1_graph_retrieval/experiments/configs/r0_bm25_default.json
```

完成：相同 run 两次输出字节一致；真实指标、配置、环境和全部失败样例齐全；不宣称未经验证的提升。

回滚：run 目录按 immutable artifact 管理；错误 run 标记 invalid，不覆盖。

## 6. B-R2：知识点—PPT 页映射 baseline

### B-R2.1 特征实现

修改：

- `src/mapping.py`
- `tests/test_mapping_features.py`
- `experiments/configs/m0_mapping_default.json`

实现：

- course-first slide candidates；
- title exact/alias/overlap；
- slide title+body BM25；
- chapter tree distance；
- 每项 feature trace 和稳定 tie-break。

风险：没有标题时伪造标题、章节路径缺失时给虚假邻近分、alias 泄漏 test gold。

验证：

```powershell
.venv\Scripts\python.exe -m pytest research/product1_graph_retrieval/tests/test_mapping_features.py -q
```

完成：单特征 golden cases 全过；缺失 feature 显式为 0/unknown，不编值。

### B-R2.2 组合、阈值与 abstain

修改：

- `src/mapping.py`
- `tests/test_mapping_abstain.py`
- validation-only 配置与 run

实现：

- 起始权重 0.45/0.40/0.15；
- title-only、BM25-only、chapter-only、等权对照；
- validation 选择 threshold 与 top1-top2 margin；
- active Evidence 硬门禁。

风险：在 test 上调权、对多页知识点强迫单页、低分仍硬映射。

验证：

```powershell
.venv\Scripts\python.exe -m pytest research/product1_graph_retrieval/tests/test_mapping_abstain.py -q
```

完成：test 配置在运行前冻结；无证据/全零/已注册歧义规则正确 abstain。

### B-R2.3 报告

修改：

- `reports/b_r2_mapping_report.md`
- `experiments/runs/<mapping_run_id>/**`

输出：Top-1/Top-3、MRR、useful coverage、Evidence binding、拒答、feature ablation、失败页案例。

完成：不报告虚构教师接受率；如需教师指标，另建盲审任务。

回滚：同 B-R1，研究 artifact 失效标记，不影响 DocumentIR/Graph 生产数据。

## 7. B-G1：P1-10 基线复核

P1-10 使用冻结 manifest 和独立命令复跑：

- fixture integrity；
- B-R1 全指标；
- B-R2 全指标；
- 字节复现；
- 禁止路径 diff；
- 网络/外部服务为零。

只有 G1 通过，才进入 Dense/RRF/Graph 实验。未通过时优先修数据、指标或隔离，不增加复杂模型掩盖问题。

## 8. B-R3a：Dense exact baseline

### 前置审批

- 候选模型必须支持目标语言/领域并允许离线使用；
- 固定 model revision、权重 SHA-256、许可证结论；
- 模型下载/额外环境需单独批准；
- 不修改生产 `pyproject.toml`、`uv.lock` 或 backend 配置。

可选安全路径：由独立获批环境生成 frozen embedding JSON/cache，研究代码用纯 Python exact dot product 读取；生成环境、模型和 hash 全记录。

修改：

- `src/dense.py`
- `tests/test_dense_exact.py`
- `experiments/configs/r1_dense_<model>.json`
- `reports/b_r3a_dense_report.md`

验证：

```powershell
.venv\Scripts\python.exe -m pytest research/product1_graph_retrieval/tests/test_dense_exact.py -q
```

完成：同课程/Evidence 门禁全过；模型 cache 可验证；按 query type 报 BM25/Dense 胜负样例。

回滚：删除可重建 embedding cache 或标记失效；不影响生产依赖。

## 9. B-R3b：RRF Hybrid

修改：

- `src/fusion.py`
- `tests/test_rrf.py`
- `experiments/configs/r2_rrf_*.json`
- `reports/b_r3b_hybrid_report.md`

实现：

- `k=20/60/100`；
- 等权和预注册小权重网格；
- scope/evidence identity 强校验；
- stable chunk ID 去重和 tie-break；
- 输出 sparse/dense ranks、分量和 final score。

风险：不同 provider chunk ID 不一致、输入 source 顺序影响 tie、candidate depth 不公平。

验证：

```powershell
.venv\Scripts\python.exe -m pytest research/product1_graph_retrieval/tests/test_rrf.py -q
```

完成：置换输入 source 顺序结果不变；R0/R1/R2 公平条件一致；Evidence 字段零丢失。

回滚：保留单路 R0/R1 作为可用研究 baseline。

## 10. B-R3c：受限图扩展

修改：

- `src/graph_expand.py`
- `tests/test_graph_envelope.py`
- `tests/test_graph_expansion.py`
- `experiments/configs/r3_graph_*.json`
- `reports/b_r3c_graph_ablation.md`

实现：

- envelope hash/course/evidence/relation 完整性；
- accepted + active evidence + same course；
- 一跳与 relation budget；
- 路径解释；
- 图候选回到 Evidence-backed chunk；
- 无合法图候选时退化为 R2，而不是生成内容。

风险：hub 漂移、错误先修边、GraphSnapshot 浅可变、同名跨课程节点、图候选改变 TopK 公平性。

验证：

```powershell
.venv\Scripts\python.exe -m pytest research/product1_graph_retrieval/tests/test_graph_envelope.py -q
.venv\Scripts\python.exe -m pytest research/product1_graph_retrieval/tests/test_graph_expansion.py -q
```

完成：故障注入的 proposed/stale/cross-course/missing-evidence 边均被拒绝；每个扩展 hit 有完整路径与 Evidence；最终 TopK 与其他 run 一致。

回滚：关闭 research config 的 graph stage 即回到 R2；没有生产 flag 或数据迁移。

## 11. B-G2：消融裁决

统一输出表：

| Run | Recall@5 | Recall@10 | MRR | nDCG@10 | 污染率 | Evidence 完整率 | 正确/错误拒答 | P95 | RSS | index bytes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| R0 BM25 | 待实验 | 待实验 | 待实验 | 待实验 | 待实验 | 待实验 | 待实验 | 待实验 | 待实验 | 待实验 |
| R1 Dense | 待实验 | 待实验 | 待实验 | 待实验 | 待实验 | 待实验 | 待实验 | 待实验 | 待实验 | 待实验 |
| R2 Hybrid | 待实验 | 待实验 | 待实验 | 待实验 | 待实验 | 待实验 | 待实验 | 待实验 | 待实验 | 待实验 |
| R3 + Graph | 待实验 | 待实验 | 待实验 | 待实验 | 待实验 | 待实验 | 待实验 | 待实验 | 待实验 | 待实验 |

裁决规则：

- 安全门禁先于质量指标；任何污染或伪 Citation 直接失败。
- 使用 paired per-query delta 和固定 seed bootstrap CI。
- Graph 只在目标 query 类型有稳定净收益、成本可接受且无安全退化时形成 Provider 候选。
- R3 未优于 R2 时，结论可以是“图增量证据不足”；这也是有效研究结果。
- 不因算法复杂度、论文热度或开源 stars 决定 Preferred。

## 12. 生产晋级边界

Agent B 最多提交：

- 冻结 fixture 与 gold；
- 离线研究实现；
- 可替换 Provider 候选接口说明；
- 配置、run artifact、失败样例、报告；
- 对冻结契约的 ADR 建议。

Agent B 不执行：

- 修改生产 Provider/Gateway；
- 注册路由、feature flag、ORM/Migration；
- 接 QA/上传/前端；
- Shadow/Canary；
- 宣布 Preferred。

后续顺序固定为 P1-10 独立验证 -> P1-00 契约审批 -> P1-09 Shadow -> Canary -> 人工批准。

## 13. 每次提交的范围证明

实施提交前后运行：

```powershell
git status --short
git diff --name-only -- backend/app backend/tests/product1 frontend pyproject.toml uv.lock
git diff --check
```

第二条必须无输出。测试只运行研究目录的离线测试，不启动 `backend/app/main.py`，避免依赖检查、表创建或迁移副作用。
