# B-G0b 真实输入要求

状态：`AUTHORIZATION_PRIVACY_ATTESTED_PENDING_VALIDITY_AND_HUMAN_SELECTION`。截至 2026-07-16，已收到 4 门真实课程的 PPTX/PDF 双格式原件，共 253 页；原件目录已被 Git 忽略。用户已确认授权/隐私审签完成，且材料仅限“智能课程系统”项目内部离线评测、不得对外分发。当前仍需把有效期、责任人/证据引用、逐课文件与隐私复核结果写入受控 manifest，并完成人工 selection/OCR 复核；候选构建保持 blocked，不能用自动解析结果替代人工 Gold。

## 放行前置

由材料责任人在受控来源目录提供 `authorized_source_manifest.json`。每门课必须包含：

- 唯一稳定 `course_id`。
- 两个原始文件角色：`pptx_source` 和 `pdf_reference`；显式填写 `page_count`，并提供真人完成的逐页配对复核状态与证据引用，确认二者页数和页面对应关系一致。
- 书面授权责任人、授权证据引用、用途 `human_gold_research_evaluation`、生效时间和失效时间或 `no_expiry=true`。
- 隐私复核责任人及证据；批准受控读取原件，声明已知直接标识符是否存在，提供清洗计划，并确认不含学生记录。
- 每个原始文件的相对路径与 SHA-256；不得引用来源包目录之外的文件。
- 仓库存储明确获准；敏感材料若仅获准在外部受控位置使用，必须另行设计不入库流程。

DocumentIR、Evidence、课程结构、知识点、查询和 slides 是预检通过后生成的候选产物，不再反向作为来源授权的前置文件，避免循环依赖。结构以 [authorized_source_manifest.schema.json](../../../research/product1_graph_retrieval/schemas/authorized_source_manifest.schema.json) 为准。工具只校验格式、hash、路径、已声明授权/隐私状态并做保守 PII 扫描，不能替代法律、隐私或身份人工审查。

## 原件处理规则

- 原件保持只读，不原地清洗或覆盖。
- 派生候选必须剥离 PPTX 作者/最后修改者等文档元数据。
- 可见页、备注、图片 OCR 和嵌入对象均进入隐私复核；已发现至少一个邮箱模式，必须删除或替换。
- PPTX 原生文本为结构主干，PDF 文本层用于交叉补全；仅对低文本、图片主导或文本冲突页运行 PP-StructureV3。
- OCR 输出必须保留坐标、阅读顺序、模型/参数和置信度，并放入显式 research sidecar；低置信度内容不能自动成为 Evidence 或 qrels。

## 冻结契约

来源 manifest 声明派生数据将适配且不修改以下冻结契约：

- `document_ir = document-ir/1.0`
- `evidence = evidence/1.0`
- `citation = citation/1.0`
- `education_graph = edu-graph/1.0`

契约变化必须走独立 ADR；不得在 B-G0b 内修改生产契约。

## 预检命令

```powershell
.venv\Scripts\python.exe research/product1_graph_retrieval/tools/preflight_human_gold_inputs.py <source-bundle>/authorized_source_manifest.json
```

只有返回 `authorized_inputs_ready` 才允许开始候选数据转换。失败必须保持 fail-closed，不得跳过缺失授权、隐私、页数配对复核、角色、扩展名或 hash 项。候选选择、构建、验证和盲标包流程见 [human_gold_candidate_runbook.md](human_gold_candidate_runbook.md)。

## 候选目录的预期文件分区

公开索引输入仅限 `source_blocks.jsonl`、`evidence.jsonl`、`corpus.jsonl`、`queries.jsonl`、`knowledge_points.jsonl`、`slides.jsonl`、`splits.json`。人工标签、qrels、A/B 标注包和仲裁记录属于 gold-only，任何检索/映射 run 在冻结前不得读取。候选 manifest 的 `gold.eligible_for_algorithm_comparison` 必须为 `false`。

## 数据语义补充

- 查询分层固定为 `exact_term`、`definition`、`formula_or_code`、`paraphrase`、`cross_language_alias`、`multi_hop_relation`、`no_answer`；每门课和各 split 分层报告，不以自动生成查询充当真实查询。
- 无答案类型固定为 `unanswerable_in_course`、`scope_not_available`、`evidence_stale_only`；可回答为 `answerable`。
- retrieval qrels 使用 0/1/2：`not_relevant` / `partial_support` / `direct_support`。
- mapping qrels 使用 0/1/2：`irrelevant_hard_negative` / `supporting_slide` / `primary_slide`。一个知识点允许多个 `primary_slide` 或 `supporting_slide`，必须逐页记录 Evidence ID。
- 多页映射不压缩成单页：顺序页、总结页、例题页分别标注；最终 qrels 保留全部被判定页面。
- `chapter_distance` 按冻结优先级计算：同课程且两侧有 `chapter_path` 时，用树边数 `len(a)+len(b)-2*LCP(a,b)`；无章节树、但同一 document 且有 1-based 页码时，用绝对页差；其他情况为 `unknown`、数值特征 0 且 `missing=true`。跨课程直接报错，禁止混合树距离与页差。
- 所有研究侧字段使用 `research_` 前缀或 sidecar 文件显式命名，不回写生产对象。