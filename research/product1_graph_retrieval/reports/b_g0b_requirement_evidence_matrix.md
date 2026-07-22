# B-G0b 要求—证据矩阵

- 审计日期：2026-07-16
- 审计范围：仅 B-G0b Human Gold Preparation
- 当前结论：`MACHINE_PREPARATION_COMPLETE_EXTERNAL_HUMAN_SELECTION_REQUIRED`
- 真实 candidate：未生成
- 真实人工标签：未生成
- B-R1/B-R2/B-R3：保持 blocked

本矩阵区分“工具和契约已经完成”与“真实团队已经执行”。工具存在或合成契约测试通过，不能证明人工 selection、A/B 标注、第三人仲裁或 P1-00/P1-10 审批已经完成。

## 逐项证据

| 任务卡要求 | 当前权威证据 | 判定 |
|---|---|---|
| 1. 真实输入前置检查 | 4 门真实课程 PPTX/PDF 共 8 个文件已到位；原件目录由根 `.gitignore` 排除；输入预检工具、source manifest schema 和报告均存在 | 输入存在且用途授权已声明；冻结 manifest 的有效期/长期有效和最终签署字段仍 pending |
| 2. 生成 human gold candidate | builder、候选 manifest schema 和可复现/引用闭合测试已存在 | 构建能力完成；人工 selection 未签署，真实 `datasets/human_gold_candidate_v0_1/` 不存在 |
| 2. candidate 初始状态 | builder 固定输出 `dataset_level=human_gold_candidate`、`gold.status=pending_human_annotation`、`eligible_for_algorithm_comparison=false` | 合成契约测试证明；真实 candidate 尚未生成 |
| 2. 不自动生成最终 qrels | pending candidate 禁止 label/qrels 文件；selection 与 blind packet 禁止 Gold/答案/预填标签 | 完成 |
| 3. public 与 gold-only 隔离 | manifest 精确列出 7 个 public 输入和 9 个 gold-only 文件；public access 失败关闭 | 完成并有测试 |
| 3. packet 无 score/rank/推荐/答案/Gold | 递归禁用字段检查；pending review 扫描零命中 | 完成并有测试 |
| 3. 脱敏与稳定研究 ID | direct identifier 扫描、PII 规则、稳定 course/query/KP/slide/Evidence ID 和 hash 校验 | 工具完成；真实 candidate 的最终人工隐私签署未执行 |
| 4. 人工标注协议 | `human_annotation_protocol.md` | 四类 answerability、0/1/2、mapping 三级、多页、最小充分性、跨课、stale、不确定性、独立性和无模型排序均已明确 |
| 5. retrieval/mapping 双盲 packet | `annotation_workflow.py prepare` 与 packet builder | 工具完成；真实 packet 依赖真实 candidate，尚未生成 |
| 5. A/B、compare、第三人 finalize | compare/finalize、候选集合一致性、不同 member ID、完整分歧与不确定升级检查 | 完成并有测试；工具不能证明 member ID 背后是真实人 |
| 6. 六份治理材料 | identity、calibration、adjudication、P1-00、P1-10、freeze report 模板 | 完成 |
| 7. Schema 与门禁 | 9 份 Draft 2020-12 schema；candidate gate 检查不同 A/B、第三人仲裁、校准、P1-00/P1-10 | 完成 |
| 7. pending 禁止算法比较 | evaluation guard、candidate manifest 常量和 B-R1 checker | 完成并有测试 |
| 8. 七类失败关闭测试 | 同 member ID、仲裁员冲突、缺失仲裁、packet 泄漏、gold-only 访问、pending 评测、完整治理才批准 | 全部覆盖 |
| 9. 交付与限制 | delivery、completion audit 和本矩阵 | 完成；没有人工标签或算法实现 |

## 实际机器侧交付

- pending JSON：`reports/human_selection_review_pending_v0_1.json`
- 状态与数量：`pending_human_review`；4 门、96 条查询、71 个知识点、36 个章节、41 个 OCR/原页任务
- JSON SHA-256：`c9409be83211163ee0d266d6ca3cca28685fd9909d0eda0048e29af15634d0cb`
- XLSX：`B-G0b人工Selection复核工作簿_v0_1.xlsx`
- XLSX SHA-256：`5aad0a1cd642c80910defafcff9ff1f932d3d600b721c800ee7d93e38949b452`
- importer 往返后仍为 pending，数量保持 4/96/71/36/41
- `AI建议/初审理由` 仅在 `AI初审_非Gold` 表中作为复核材料；importer 不读取
- 所有人工作业字段为空；禁用字段扫描零命中

## 本轮验证

- pending review：`valid=true`
- 研究侧测试：50/50 通过
- Draft 2020-12 schema：9/9 自检通过
- 研究侧 Python：33/33 AST 解析通过（按仓库现有 UTF-8 BOM 使用 `utf-8-sig`）
- B-R1 checker：`status=blocked`
- 禁止修改路径：工作区无变更
- 真实 candidate：不存在
- `git diff --check`：通过

## 当前不可由 Codex 代替的步骤

1. 真实团队成员在复核工作簿黄色列中做最终 selection，并完成来源有效期/长期有效记录。
2. selection 通过 fail-closed 导入和 finalize 后，才能生成真实、脱敏、未标注 candidate。
3. candidate 生成后才能产生 retrieval/mapping 的 A/B 盲标包。
4. 两名不同自然人独立标注，第三名不同自然人完成全部仲裁。
5. P1-00 与 P1-10 对语义和治理证据作人工决定。

在第 1 步完成前，自动采用 `AI建议/初审理由`、自动补写最终 selection、自动 qrels 或虚构 member ID 都违反任务边界。当前停止在这个门禁，不实现 BM25、PPT Mapping、Dense、RRF 或 Graph Retrieval。
