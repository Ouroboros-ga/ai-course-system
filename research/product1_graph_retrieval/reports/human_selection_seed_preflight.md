# B-G0b 知识点与查询种子预检

- 检查日期：2026-07-16
- 结果：`BLOCKED_PENDING_HUMAN_SELECTION_REVIEW`
- 授权声明：用户已声明完成授权/隐私审签；仅限“智能课程系统”项目内部离线评测，禁止对外分发
- 真实 candidate：未创建
- 人工 Gold：未创建
- B-R1/B-R2/B-R3：未放行

## Workbook 与导出文件

权威 workbook 为 `四门课程_知识点范围与查询分类种子.xlsx`。使用 artifact-tool 只读导入并逐工作表渲染核验：

- `使用说明`：22 行；
- `查询种子`：284 条数据行、14 列；
- `知识点范围`：71 条数据行、11 列；
- `分类统计`：13 行；
- `PPT页索引`：253 条数据行、7 列。

三个导出文件与对应工作表逐值一致：

| 文件 | 编码 | 对应工作表 | 数据行 |
|---|---|---|---:|
| `四门课程_知识点范围与查询分类种子.csv` | GB18030 | 查询种子 | 284 |
| `知识点范围子.csv` | UTF-8 BOM | 知识点范围 | 71 |
| `知识点ppt索引.csv` | UTF-8 BOM | PPT页索引 | 253 |

`四份PPT知识点范围与Human_Gold查询分类种子.csv` 为 GB18030、52 条数据行、6 列，不对应当前 workbook 的任何工作表；将其视为旧式/附加种子，不作为 selection 权威输入。

## 数据闭合

| course_id | PPT 页数 | 知识点 | 查询种子 |
|---|---:|---:|---:|
| VEH101 | 42 | 15 | 60 |
| EE207 | 62 | 20 | 80 |
| CTRL202 | 97 | 20 | 80 |
| EE101 | 52 | 16 | 64 |
| 合计 | 253 | 71 | 284 |

- 71 个知识点在 40–80 的目标区间内，课程内 ID 无重复。
- 所有知识点页码范围均落在对应课程的 1-based PPT 页范围内。
- 查询文本无重复。
- workbook/CSV 字段的保守邮箱、手机号、学号和身份证模式扫描无命中；这不替代原始图片/OCR 的人工隐私复核。
- workbook 中的 `source_file` 带历史副本后缀，例如 `(1)`、`(3)`，与实际 PPTX 文件名不同；后续只能按明确 course_id、页数和人工确认映射，不能直接按字符串文件名绑定。

## 为什么尚不能生成 candidate

1. 284 条查询的 `review_status` 全部为 `待复核`，不能签署 `human_selected_without_gold_labels_or_model_rankings`。
2. 最终 candidate 只允许 60–100 条查询，当前种子池为 284 条。
3. 当前只有 `direct_definition`、`mechanism_application`、`hard_negative`、`cross_course_isolation` 四种 seed variant；最终需要真人确认全部七个 `query_stratum`：`exact_term`、`definition`、`formula_or_code`、`paraphrase`、`cross_language_alias`、`multi_hop_relation`、`no_answer`。
4. `expected_answerability` 与 `gold_answer_hint` 只能作为隔离的种子作者侧提示，必须从最终 selection 和 A/B 盲标包删除；它们不得成为人工 Gold 或预填答案。
5. 授权声明未给出 `expires_at` 或 `no_expiry=true`，尚不能通过冻结 source manifest 的有效期门禁。

## 真人需要完成的最小动作

1. 从 284 条种子中选定 60–100 条；每条填写最终 `query_type`、七类之一的 `query_stratum`、`train|validation|test` split、reviewer ID，并标记 `已复核`。
2. 确认 40–80 个知识点；当前 71 个可以全部保留，但需填写 validation/test split、alias、章节 ID/path 和 reviewer ID。
3. 确认 workbook 历史文件名到四个实际 PPTX 的 course_id 映射。
4. 明确授权到期时间，或明确声明长期有效；该字段不能由 Codex 推断。
5. 最终 selection 不得包含 `expected_answerability`、`gold_answer_hint`、页级映射答案、算法 score/rank 或模型推荐。

完成后运行：

```powershell
.venv\Scripts\python.exe research/product1_graph_retrieval/tools/human_selection_seed_audit.py research/product1_graph_retrieval/human_gold/human_gold_source_v0_1
```

只有返回 `ready_for_selection_import=true` 才继续创建真实未标注 candidate。

## 已准备的 private 人工复核包

已从权威 workbook 生成确定性的 private pending review：96 条查询候选、71 个知识点、36 个章节候选、41 个低文本图片页 OCR/原页复核任务，以及 1 组治理与使用范围确认。配套人工工作簿将来源字段显示为只读灰色、工具建议显示为非 Gold 的浅蓝色、真人必填字段显示为黄色。

- 所有真人决定字段保持空白，不预填批准、最终分层、split、章节、OCR 采用或授权有效期。
- 用户已确认 `AI建议/初审理由` 可以作为复核材料。工作簿将其保留在显式命名的 `AI初审_非Gold` 工作表；工具建议字段均带 `_not_gold` 语义，只用于辅助复核，不能自动成为最终决定或 Gold。
- `expected_answerability`、`gold_answer_hint`、算法 score/rank 和任何 qrels 均未进入复核包。
- 41 个 OCR 任务必须逐页选择“采用真人复核 OCR”或“已目视确认无相关文字”；后者必须保持 blocks 为空，不能伪造 OCR 来源。
- 工作簿已包含 `human_finalization` 四项最终签署字段；导入器只接收黄色人工作业列，并拒绝来源/建议列篡改、行集合变化和复核单元格公式。`finalize` 对未完成的人工作业 fail closed；只有查询、知识点、章节、OCR、文件映射、有效期和治理声明全部闭合后，才会输出 authorized source manifest 与 `human_selection.json`。
