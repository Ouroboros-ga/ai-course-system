# B-R0 假设、事实与停止条件

## 1. 已核验事实

- 任务卡基础版本是 `d4894da965cc03e04194b71a44977cc957682fe1`。
- 审计时工作区 HEAD 是 `4b2bafd10f9d9d3a68ecd084002c238ba216df76`，工作树干净。
- `d4894da..HEAD` 之间，四个只读代码目录没有变化；契约登记表只新增了公开 V2 Evidence API DTO 的 G4 冻结状态。因此本报告对 DocumentIR、Evidence、Retrieval、Education Graph 的代码结论同时适用于任务卡基线和审计时 HEAD。
- 根 `AGENTS.md` 禁止当前阶段实现 GraphRAG、修改公开行为、调用真实付费服务或生产数据库。
- `pyproject.toml` 的直接依赖只有 FastAPI、Gradio Client、Requests 和 Uvicorn；没有 BM25、分词、向量或图检索依赖。本研究不能通过修改依赖锁来引入它们。

## 2. 研究假设

以下内容是待实验验证的假设，不是已实现能力：

1. 课程分区后建索引比全局召回后过滤更容易把跨课程污染率稳定为零。
2. 混合中英文教学材料可用确定性 Unicode 规范化、拉丁词项和 CJK 字符 n-gram 建立一个无外部依赖的 BM25 下界。
3. 标题匹配、页内 BM25 与章节距离能够形成可解释的知识点—PPT 页映射下界。
4. Dense 可能改善同义改写和跨语言别名召回，但可能降低精确词、公式、代码符号的可控性。
5. RRF 可能利用 sparse/dense 互补性，但其常数和权重必须调参，不能把 `k=60` 当作本项目定律。
6. 只在 accepted、active-evidence、同课程边上做一跳图扩展，可能改善先修或关联查询；也可能引入主题漂移。
7. 图扩展的复杂度本身不构成收益证据；R3 未显著优于 R2 时应停止晋级。

## 3. 严格输入假设

- fixture 是冻结、脱敏、非生产导出的 JSON/JSONL。
- 每个可检索块都能追溯到唯一 `course_id + artifact_id + document_id + unit_id + block_id`。
- 研究 sidecar 为每个 EvidenceSpan 计算 `evidence_id`，但不宣称该字段已经属于 `evidence/1.0`。
- `page_or_slide` 在 PPT fixture 中统一为 1-based；原始 `DocumentUnit.index` 同步保留，防止静默重编号。
- 只索引 `status=active` 的 Evidence；stale/suspended 仅用于负例和完整性测试。
- 查询的课程范围由 fixture 显式给出，研究代码不负责身份认证或权限授权。

## 4. 不作出的假设

- 不假设当前 `RetrievedChunk.chunk_id` 是 DocumentIR block ID 或 Evidence ID。
- 不假设 `GraphSnapshot(frozen=True)` 已实现深不可变。
- 不假设登记表中的 `GraphEvidence` 在代码里存在同名模型。
- 不假设 `BM25Provider.index(List[str])` 能保留 Evidence 身份。
- 不假设空结果一定是“无证据”；当前 Gateway 还可能因空查询、未索引或异常返回空列表。
- 不假设论文或开源项目在其数据集上的提升能迁移到本课程 fixture。
- 不假设真实教师接受率、延迟或准确率；这些只能来自未来真实评测。

## 5. 停止条件

出现任一情况时，本研究应停止当前阶段并报告，而不是扩大范围：

- 需要修改冻结生产契约才能让研究代码运行；
- 需要读取生产数据库、生产密钥或真实学生数据；
- 需要安装模型、下载权重或调用外部付费服务但尚未单独获批；
- fixture 只有一个课程，无法验证跨课程污染；
- gold relevance 或映射标注没有双人复核，无法区分检索失败与标注缺口；
- 结果无法由 manifest、配置哈希和固定 tie-break 复现；
- 无 Evidence 的结果仍产生 citation key 或 `Citation`；
- R3 的任何收益来自更大的候选数、不同 TopK 或不同查询集。
