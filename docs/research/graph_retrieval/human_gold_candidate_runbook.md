# B-G0b 候选数据与盲标运行手册

本手册只准备未标注 candidate 和人工工作包，不允许填写 Gold、不运行检索算法，也不放行 B-R1/B-R2。

## 1. 输入角色

### 材料责任人

完成 `authorized_source_manifest.json`：

- 3–5 门课程；每门恰好一个 `pptx_source` 和一个 `pdf_reference`；
- 文件 SHA-256、声明页数和 PPTX/PDF 同页数人工复核记录；
- 材料权利、研究用途、有效期、仓库存储许可；
- 原件受控访问、已知直接标识符声明、候选脱敏计划；
- 确认不含学生记录。

### 查询与知识点策划人

在任何 Gold 标注前准备 `human_selection.json`。这不是 retrieval/mapping 标签，禁止包含 answerability、relevance、primary/supporting、score、rank、模型答案或模型推荐。

策划内容：

- 60–100 条真人编写查询，覆盖七个 `query_stratum`；
- 40–80 个真人确认的知识点名称和 alias；
- query 的 train/validation/test 和知识点的 validation/test 分割，在 Gold 前冻结；
- 每页唯一闭合的章节范围；
- 已知姓名等人工 redaction terms 及复核引用；
- 图片主导且原生文本少于 30 字符的页面，提供 `human_reviewed_for_candidate` OCR 记录，或显式复核为没有相关文字。

查询/知识点策划人只确认候选语义，不填写相关性或映射答案。工具不能证明其真人身份，P1-10 仍需人工核验。

## 2. 生成待填写模板

授权清单预检通过后执行：

```powershell
.venv\Scripts\python.exe research/product1_graph_retrieval/tools/build_human_gold_candidate.py template `
  <source-bundle>/authorized_source_manifest.json `
  <source-bundle>/human_selection.json
```

输出故意保持 `PENDING_HUMAN_*`，在人工填写与审签前不满足 selection schema，也不能用于构建 candidate。

## 3. 从 seed workbook 生成人工 selection review

先生成不含 Gold 的 private review JSON；JSON 是权威交换格式，人工工作簿只是便于填写的界面：

```powershell
.venv\Scripts\python.exe research/product1_graph_retrieval/tools/human_selection_review.py prepare `
  <source-bundle> <private-review.json> --query-target 96

.venv\Scripts\python.exe research/product1_graph_retrieval/tools/human_selection_review.py validate `
  <private-review.json>
```

所有工具建议都以 `_not_gold` 显式命名，真人决定字段必须保持空白等待填写。复核包不得包含 `expected_answerability`、`gold_answer_hint`、answerability、qrels、算法 score/rank 或模型答案。当前真实来源会生成 96 条查询候选、71 个知识点、36 个章节候选和 41 个 OCR/原页复核任务。

真人完成工作簿后，先只导入黄色人工作业列，再验证并执行 finalize：

```powershell
.venv\Scripts\python.exe research/product1_graph_retrieval/tools/human_selection_workbook.py `
  <private-review.json> `
  <filled-review.xlsx> `
  <private-review-imported.json>

.venv\Scripts\python.exe research/product1_graph_retrieval/tools/human_selection_review.py validate `
  <private-review-imported.json>

.venv\Scripts\python.exe research/product1_graph_retrieval/tools/human_selection_review.py finalize `
  <private-review-imported.json> `
  <source-bundle> `
  <source-bundle>/authorized_source_manifest.json `
  <private-output>/human_selection.json
```

工作簿导入器要求七个复核工作表、表头、行集合和稳定 ID 完整一致；灰色来源列、蓝色 `_not_gold` 建议列被改动，或任一复核单元格含公式时均 fail closed。治理页还必须由真人填写 `human_finalization.status/finalized_by/finalized_at/attestation`，导入器不会代填。

`finalize` 对任何未复核候选、缺失的七类查询分层、数量越界、章节空洞、OCR 未决、授权有效期或治理声明缺失均 fail closed。输出会删除所有工具建议和种子提示。

## 4. OCR 记录

采用 OCR 文字的课程必须先填写 `ocr_provenance`（`engine`、`engine_version`、OCR 配置文件的 `config_sha256`）。每条 OCR 记录必须绑定 slide number，并由真人完成隐私和内容复核；`order` 是 1-based 阅读顺序且同页不得重复：

```json
{
  "slide_number": 3,
  "review_status": "human_reviewed_for_candidate",
  "blocks": [
    {"order": 1, "text": "复核后的结构化文字", "bbox": [95, 302, 1417, 962], "confidence": 0.97}
  ]
}
```

OCR 是候选解析输入，不是 Gold。bbox 和 confidence 不进入相关性判断；低置信度噪声应在进入 candidate 前由复核人移除或纠正。图片页即使 OCR 有文本，mapping 标注员仍必须查看受控原页。

若真人目视确认该低文本图片页没有与课程内容相关的文字，使用 human_reviewed_no_relevant_text 且 locks=[]。这种记录不要求 OCR provenance，也不得把页面内容来源标成 human_reviewed_ocr。

## 5. 构建与验证 candidate

```powershell
.venv\Scripts\python.exe research/product1_graph_retrieval/tools/build_human_gold_candidate.py build `
  <source-bundle>/authorized_source_manifest.json `
  <source-bundle>/human_selection.json `
  research/product1_graph_retrieval/datasets/human_gold_candidate_v0_1

.venv\Scripts\python.exe research/product1_graph_retrieval/tools/build_human_gold_candidate.py validate `
  research/product1_graph_retrieval/datasets/human_gold_candidate_v0_1
```

生成器必须满足：

- 100–300 个 active chunks；
- 60–100 条查询、40–80 个知识点、七类查询全覆盖；
- stable research ID、Evidence offset/snippet、Citation key 和 slide 引用闭合；
- public/index 只含七个输入文件；不创建任何 qrels、query labels 或 annotation；
- 邮箱、手机号、学号、身份证号及人工 redaction terms 被移除；
- 低文本图片页缺少真人复核 OCR 时 fail closed；
- 同一输入重复构建逐字节一致；
- manifest 固定 `dataset_level=human_gold_candidate`、`gold.status=pending_human_annotation`、`eligible_for_algorithm_comparison=false`。

## 6. 生成四份独立盲标包

```powershell
.venv\Scripts\python.exe research/product1_graph_retrieval/tools/annotation_workflow.py prepare <candidate> --task retrieval --role A --member-id <A> --output annotation/retrieval_A.json
.venv\Scripts\python.exe research/product1_graph_retrieval/tools/annotation_workflow.py prepare <candidate> --task retrieval --role B --member-id <B> --output annotation/retrieval_B.json
.venv\Scripts\python.exe research/product1_graph_retrieval/tools/annotation_workflow.py prepare <candidate> --task mapping --role A --member-id <A> --output annotation/mapping_A.json
.venv\Scripts\python.exe research/product1_graph_retrieval/tools/annotation_workflow.py prepare <candidate> --task mapping --role B --member-id <B> --output annotation/mapping_B.json
```

A/B 不得互看。候选只按 stable research ID 排序。mapping candidate 带 `controlled_source_ref` 和 `requires_visual_review=true`，文字抽取明确标为不能替代原页。

## 7. 分任务比较与仲裁

retrieval 与 mapping 必须分别比较、分别由第三个不同 member ID 仲裁：

```text
annotation/retrieval_adjudication.json
annotation/mapping_adjudication.json
```

工具会把 A/B 标签分歧和任一方 `needs_adjudication=true` 的不确定项全部送入仲裁。缺一项、重复项或仲裁者等于 A/B 均失败。两个 Agent、同一人重复填写或自动标签不得冒充两名独立人工。

## 8. 治理门禁

完成两类标注及仲裁后，仍需：

- 身份记录、独立性 attestation hash、两类 bundle hash；
- calibration 记录；
- 汇总仲裁记录及 hash；
- P1-00 语义口径批准；
- P1-10 真人身份、独立性、完整性复核。

即使成为 `approved_candidate`，算法比较资格仍为 false，B-R1 仍需单独明确授权。