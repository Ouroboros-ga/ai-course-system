# DocumentIR、Evidence、Graph、Retrieval 契约适配审计

> 审计基线：`d4894da`；最近复核 HEAD：`3743fc2`；日期：2026-07-19。  
> 结论仅来自任务卡指定的只读输入和契约登记表，不把 README、规划稿或历史测试数字当作实现证据。

## 1. 基线一致性

`git diff --name-status 4b2bafd..3743fc2 -- <冻结输入>` 无输出，说明最近一次审计后，DocumentIR、Evidence、Retrieval、Education Graph 和契约登记表均未变化。B-P0 进一步冻结这 9 个输入文件的 SHA-256；任何文件漂移都会使算法前置检查 fail closed，要求先重新审计，不能直接沿用本报告。

复核没有改变 B-R0 结论：生产 BM25 Provider 仍只接受 `List[str]`，Gateway 仍以空列表合并多种拒答原因，RRF 仍缺少研究要求的 scope/参数/稳定 tie-break 门禁。因此 B-R1/B-R2 继续采用研究 sidecar，且正式实现仍等待 Human Gold 与显式放行。

## 2. 总体结论

现有契约足以支撑 B-R0 的 fixture 设计，也能支撑 B-R1/B-R2 的研究侧适配，但不能直接把当前 Provider 协议当成“证据完整的 BM25 实现接口”。

可直接消费的部分：

- DocumentIR 的 source、unit、block、页/幻灯片、文本、reading order 和 provenance；
- EvidenceSpan 的 artifact/document/unit/block、字符区间、页码和生命周期状态；
- RetrievalScope 的显式课程范围；
- RetrievedChunk 的 optional Evidence 字段；
- 教育图谱的受控节点/关系枚举、`SUPPORTED_BY`、`APPEARS_ON` 和关系校验。

必须由研究 sidecar 补齐、但不能冒充冻结生产字段的部分：

- `course_id` 研究 envelope；
- 每条 EvidenceSpan 的 `evidence_id`；
- 显式 `RetrievalQuery`、run result、abstain reason；
- 图快照的课程范围、深不可变校验和 canonical hash；
- BM25 语料记录与文本之间的稳定身份映射。

## 3. 契约逐项审计

### 3.1 DocumentIR / Geometry

已核验能力：

- 登记表将 `document-ir/1.0` 标为 `frozen-major`，并要求 stable ID 不受运行元数据影响（`docs/refactor/product1/contracts/registry.md:11`）。
- `deserialize_document_ir()` 解析 schema version，并对未知更高 major fail-closed（`backend/app/platform/document_intelligence/document_ir/serialization.py:31-46`）。
- `DocumentIR` 显式包含 `source_artifact`、`units`、`blocks` 和 `assets`（`document_ir/models.py:687-705`）。
- `DocumentUnit` 提供 unit 类型、index、block IDs 和 reading order（`document_ir/models.py:615-630`）。
- block 提供 `page_or_slide`、`block_type`、文本、bbox 和 provenance，可构造 PPT 页文本和来源定位。
- `compute_document_id()` 与 `compute_unit_id()` 是确定性 UUIDv5 帮助函数（`document_ir/models.py:978-997`）。
- reference-integrity 和 duplicate-ID 检查函数已经存在（`document_ir/models.py:781-859`）。

适配限制：

- 契约没有通用 `compute_block_id()`；当前 provider 自行生成 `blk_pptx_s...`、`blk_docling_p...` 等 block ID。研究 fixture 必须冻结已有 block ID，不能在 baseline 里重新发明生产 block ID 算法。
- `DocumentUnit.index` 的基类语义没有明确 0-based/1-based。native PPTX 实际以 `i + 1` 写入；研究 fixture 必须同时保存原 index，并把 PPT 的 `page_or_slide` 明确为 1-based。
- `DocumentIR.from_dict()` 本身不做 major 版本检查；研究数据必须走 `deserialize_document_ir()`，不能直接调用 `from_dict()` 绕过 fail-closed。
- frozen dataclass 只限制属性重新赋值；内部 list/dict 成员不都深不可变。fixture 以 canonical JSON 和 SHA-256 保证冻结，不依赖 Python 对象冻结语义。

研究决策：B-R1/B-R2 只读取序列化 DocumentIR，先运行 schema、reference 和 duplicate-ID 校验，再生成只读 corpus sidecar。

### 3.2 Evidence / Citation

已核验能力：

- `EvidenceSpan` 强制包含 artifact、document、unit 和 block ID（`evidence/contracts.py:63-66`）。
- 它还能携带 version、页/幻灯片、字符区间、snippet、score 和 active/stale/suspended 状态（`evidence/contracts.py:68-76`）。
- `EvidenceBundle` 有 `bundle_id`，并可区分 active/stale items（`evidence/contracts.py:88-115`）。
- `citation_key()` 在 block ID 缺失时返回 `None`，符合“无证据不伪造 key”（`evidence/citation.py:94-114`）。
- `CitationValidationResult` 有 `abstain` 与 `abstain_reason`，但它属于 citation validation，而非 retrieval run 顶层结果。

适配限制：

- `EvidenceSpan` 没有自身 `evidence_id`；只有 bundle 有 ID。任务卡又要求每个结果保留 Evidence ID。
- `version_ref` 在代码中是 optional，而登记表写“必须引用存在的 artifact/version/block”。研究 fixture 将采用更严格子集：所有 active Evidence 必须填写 `version_ref`。
- `EvidenceSpan` 没有 `__post_init__` 验证字符区间、ID 前缀、snippet 与 block text 的一致性。研究数据加载器必须 fail-closed 校验。
- `Citation.evidence_ref` 是未类型化字符串，不能单靠该字段证明指向哪个 EvidenceSpan。
- `citation_key()` 允许空 artifact ID，只要 block ID 存在仍会生成 key。研究侧要求 artifact 和 block 均非空，并且 evidence 状态 active，才允许计算 key。

研究决策：定义 `EvidenceRecord` sidecar，`evidence_id` 由 canonical tuple 的 SHA-256 派生；sidecar 内嵌完整 frozen `EvidenceSpan` 字段。它只是实验身份，不宣称是 `evidence/1.0` minor 字段。无 active Evidence 时 run 直接 abstain，不构造 `Citation`。

### 3.3 Retrieval

已核验能力：

- `RetrievalScope` 明确区分 course、knowledge_base、document（`retrieval/schemas.py:33-65`）。
- `RetrievedChunk` 保留 scope、source/chapter/page、score/path/metadata，并有 optional artifact/document/unit/block/evidence_spans（`retrieval/schemas.py:71-107`）。
- 登记表明确 `chunk_id` 仍是过渡树节点 ID，不得冒充 DocumentIR block/evidence ID（`contracts/registry.md:34`）。
- Gateway 对未建立 scope 不回退其他 scope；这为课程隔离提供了正确 seam。
- Provider 契约已经预留 BM25、Vector、RRF 与 Reranker 的概念接口。

适配限制：

- `BM25Provider.index(scope, documents: List[str])` 只接收裸文本（`retrieval/providers/contracts.py:36-59`），不能原生保留 block、page、Evidence ID 或稳定 chunk identity。
- 同一个裸文本可来自不同页、不同块或不同课程；仅靠 list ordinal 回填身份会在重排、去重或持久化时脆弱。
- 当前 Gateway 明确不负责权限或评测（`retrieval/gateway.py:13`）。研究能验证 scope isolation，但不能把它称为用户授权验证。
- 新 retrieval 模块没有冻结的 `RetrievalQuery` 或带 reason code 的顶层 `RetrievalResult`。Gateway 的 `[]` 同时可能表示空查询、未索引、无命中或异常。
- `RetrievalScope.scope_type` 使用 typing `Literal`，运行时没有 fail-closed 校验；空 `scope_id` 也会被接受。
- `rrf_fuse()` 没有检查各来源 scope 一致、权重和为 1、`k > 0` 或稳定二级排序；相同分数时结果依赖输入顺序。
- RRF 使用 `chunk_id` 去重；过渡 chunk ID 或不同 provider 的不一致 ID 会导致错误合并或无法合并。
- 当前 `rrf_fuse()` 没有把最终 RRF score 写回结果，`retrieval_source` 也仍来自最后一次覆盖的原 chunk，不足以做解释性报告。

研究决策：B-R1 不实现生产 `BM25Provider`。先在研究目录定义 `CorpusRecord -> BM25Index -> ResearchHit` 的透明链路，最后适配为 RetrievedChunk-compatible JSON。每个 course 独立建索引；排序使用稳定 evidence/chunk ID。未来若晋级生产，再由 P1-03 Owner 决定是 minor 增加结构化 index record，还是维护 provider 内部 side table。

### 3.4 Education Graph

已核验能力：

- `edu-graph/1.0` 提供结构层 `COURSE/CHAPTER/SECTION/PAGE/SOURCE_BLOCK` 和语义层 KnowledgePoint、Concept、Definition、Formula、Method、Example、Exercise、Misconception 等类型（`education_graph/enums.py:24-69`）。
- 关系包含 `SUPPORTED_BY` 与 `APPEARS_ON`，可以表达语义节点到 source block 与 PPT 页的可解释链接（`education_graph/enums.py:75-101`）。
- GraphNode 与 GraphRelation 都有 `evidence_ids`（`education_graph/models.py:101,145`）。
- validation 模块实现 type matrix、自环、重复边和 prerequisite cycle 检查。

适配限制：

- 登记表冻结了 `GraphEvidence / GraphSnapshot`，但在任务卡指定的 Education Graph 只读代码中没有同名 `GraphEvidence` dataclass。实际模型只存 `evidence_ids: List[str]`。
- 因 EvidenceSpan 没有 `evidence_id`，`evidence_ids` 的指向规则在这几个冻结文件之间不闭合。
- `GraphSnapshot` 标注 `frozen=True`，但其 `nodes`、`relations`、metadata 是可变 dict，节点和关系本身也是可变 dataclass；因此是浅冻结，不是内容深不可变（`education_graph/models.py:167-186`）。
- `GraphSnapshot` 没有显式 `course_id`、parent snapshot、content hash 或 active pointer。跨课程图扩展不能只靠 snapshot 对象证明隔离。
- node/relation/snapshot ID 只以字符串类型别名和注释约定；代码注释明确生产将来使用 UUIDv5，但当前没有冻结的计算函数。
- GraphSnapshot 构造器本身不强制只包含 accepted 节点/边，也不验证 Evidence 引用存在。调用链可能在其他模块保证，但不在本次指定只读契约表面内。
- `GraphNode.__post_init__()` 的默认 canonical key 只是 lower/strip/空格替换，不足以解决中文同义词、缩写、歧义或跨课程概念边界。

研究决策：图 fixture 使用 `CourseGraphSnapshotEnvelope` sidecar，外层强制 `course_id`、snapshot source ID、canonical content hash；只接受状态为 accepted 且可解析到 active EvidenceRecord 的节点和边。图扩展只读取 sidecar，不修改 GraphSnapshot，不把研究 sidecar 宣称为生产契约。

## 4. 关键缺口清单

| ID | 严重度 | 缺口 | 对 B 轨道影响 | 本轮处理 | 生产 Owner 后续决策 |
| --- | --- | --- | --- | --- | --- |
| B-CON-001 | P0 | `GraphEvidence` 登记名与指定代码表面不闭合 | 无法证明 graph `evidence_ids` 指向规则 | 研究 sidecar + referential-integrity 校验 | P1-00/P1-03/P1-05 澄清或 ADR |
| B-CON-002 | P0 | BM25 `index(List[str])` 丢身份 | 不能直接满足 Evidence/page/block 保留 | 研究结构化 corpus + side table | P1-03 决定 provider minor 方案 |
| B-CON-003 | P0 | EvidenceSpan 无单条 `evidence_id` | 任务卡指标无法直接按 Evidence ID 统计 | 确定性 sidecar ID | P1-03 决定是否晋级字段 |
| B-CON-004 | P0 | graph snapshot 无显式课程 scope | 图扩展可能跨课程污染 | 每 course 独立 envelope/index | P1-05/P1-09 定义持久化 scope |
| B-CON-005 | P1 | GraphSnapshot 仅浅冻结 | 同一 fixture 可能被内存修改 | canonical JSON + SHA-256 + reload | P1-05 评估深不可变 minor/实现修复 |
| B-CON-006 | P1 | block/node/relation/snapshot ID 规则不完整 | 跨 provider/运行复现有风险 | 冻结输入 ID，不重算生产 ID | 对应契约 Owner 定义稳定算法 |
| B-CON-007 | P1 | Retrieval 无顶层 abstain reason | 空列表语义模糊 | 研究 `RunResult` 显式 reason | P1-03/P1-09 评估内部 trace |
| B-CON-008 | P1 | RRF 不校验 scope/参数/稳定 tie | 污染与复现风险 | 研究实现强校验和稳定排序 | P1-03 后续实现时补 contract test |
| B-CON-009 | P1 | Evidence 字段缺运行时完整性校验 | 可能输出伪页码/错误 span | fixture loader fail-closed | P1-03 决定 validation 层 |
| B-CON-010 | P2 | PAGE 同时承担 page/slide 语义 | PPT 映射解释可能含混 | sidecar 保留 `unit_type=slide` | P1-05 仅在确有消费者需求时申请 minor |

## 5. B-R1/B-R2 可启动性判断

结论：**有条件可启动，不需要先改生产契约。**

必须先完成：

1. 按 fixture spec 建立至少两课程的 frozen corpus、queries 和 gold。
2. 人工复核 `course_id -> document/unit/block/evidence` 关联。
3. 生成 manifest 和 canonical hashes。
4. P1-00 确认研究 `evidence_id` 只是一层 sidecar，不等价于冻结生产 ID。

满足后，B-R1/B-R2 可以完全在研究目录实现。任何需要修改 `backend/app/**` 的需求都应停止并转为契约变更建议，不在 Agent B 内处理。

## 6. B-R3 可启动性判断

Dense/RRF 的实验设计可以现在冻结，执行必须等 B-R1/B-R2 评测基线成立。图扩展还需要 CourseGraphSnapshotEnvelope 和 gold query 类型；GraphRAG 仍明确禁止。

图增量只有同时满足以下条件才可提交 P1-10：

- 同一 gold、query、scope、TopK、评价脚本；
- 污染率继续为 0；
- Citation 结构完整率不下降；
- Recall/MRR 的改进附带 per-query paired 结果和失败样例；
- 延迟、内存和索引体积真实记录；
- 不把“未显著退化”写成“显著提升”。
