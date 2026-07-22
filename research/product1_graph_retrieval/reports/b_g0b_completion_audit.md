# B-G0b 完成度与阻塞审计

- 审计日期：2026-07-16
- 总体状态：`SELECTION_REVIEW_PACKET_COMPLETE_REAL_CANDIDATE_BLOCKED`
- 阻塞原因：授权/隐私已由用户声明完成，但尚缺授权有效期字段和最终人工 human selection
- 算法阶段：B-R1/B-R2/B-R3 均未放行

## 结论

B-G0b 的可由 Codex 完成的准备链已经实现并通过离线测试：来源 fail-closed 预检、private selection review schema/生成/工作簿受控导入/验证/finalize、稳定研究 ID、未标注 candidate 构建、文件与内容 hash、记录级 Evidence/Citation/slide 引用闭合、课程隔离、split 隔离、PII 检查、盲标包、双任务仲裁和治理门禁。

4 门真实课件已到位；用户已明确授权仅限“智能课程系统”项目内部离线评测且禁止对外分发。新到 workbook 含 71 个知识点、284 条查询种子和 253 页索引，但全部查询仍标记为待复核并含作者侧 answerability/hint。已生成不含这些提示的 private pending review：96 条查询、71 个知识点、36 个章节、41 个 OCR/原页任务和治理复核；同时生成了经项目导入器往返验证的可填写工作簿。所有真人决定字段为空。用户确认 `AI建议/初审理由` 可作为复核材料，因此它们保留在显式命名的 `AI初审_非Gold` 工作表，但不会进入 importer、selection 或 Gold。真实 `datasets/human_gold_candidate_v0_1/` 未创建，任何 qrels、answerability 或 mapping Gold 均未填写。

## 要求覆盖

| 要求 | 当前证据 | 状态 |
|---|---|---|
| 3–5 门真实课程、PPTX/PDF 配对 | 4 门、8 个文件、253 页；来源/OCR 预检报告 | 输入及用途授权声明已到位；有效期/责任记录待闭合 |
| 原件隔离 | 根 `.gitignore` 忽略 `research/product1_graph_retrieval/human_gold/` | 完成 |
| page count 与逐页配对复核 | schema 要求 `page_count` 和人工 `page_pair_review` | 待真人审签 |
| 未标注 candidate | builder/CLI、selection schema、100–300 chunks、60–100 queries、40–80 KPs、7 个 query strata | 合成契约输入验证通过；真实数据未执行 |
| 稳定 ID/hash/可复现 | research ID、每文件 hash、candidate content hash、byte reproducibility test | 完成 |
| Evidence/Citation 闭合 | artifact/document/unit/block/offset/snippet/page/citation key 记录级校验与篡改测试 | 完成 |
| 课程与 split 隔离 | course scope、query/KP split 不相交、gold-only/public 分区 | 完成 |
| 结构化 OCR sidecar | 41 个低文本图片页已列入 private review；采用 OCR 时保留 order/text/bbox/confidence，无相关文字时显式记录且 blocks 为空 | 工具完成；本轮不再追加 OCR 审核，字段保持 pending |
| 原页 mapping 复核 | `controlled_source_ref`、`requires_visual_review=true`；OCR 分数不进盲标包 | 完成 |
| 人工 Gold | A/B 两名真人独立标注，第三人按 retrieval/mapping 分别仲裁 | 工具已备；人工工作未开始 |
| 无证据 abstain/无伪 Citation | pending candidate 不含 qrels；无闭合 Evidence 不得生成 Citation | 门禁完成 |
| B-R1 放行 | `eligible_for_algorithm_comparison=false`，另需 P1-00/P1-10 与明确授权 | blocked |

## 验证

- pending review 校验为 `valid=true`；禁用字段扫描 0 命中；工作簿往返导入保持 4/96/71/36/41 且为 `pending_human_review`。
- 50 项研究侧离线单元测试通过（2026-07-16 本轮重跑）。
- 9 份 JSON Schema 通过 Draft 2020-12 schema 自检。
- 33 个研究侧 Python 文件通过 AST 解析。
- 未启动应用，未调用真实 LLM、向量服务、生产数据库或托管 OCR API。
- 未修改 `backend/app/**`、`backend/tests/product1/**`、`frontend/**`、ORM、Migration、公开 API、配置或依赖锁。

上述验证只证明准备链、隔离和失败关闭行为，不代表真实 retrieval/mapping 指标，也不构成效果提升声明。

## 解除阻塞顺序

1. 材料责任人将已经完成的授权/隐私结论落入 source manifest，并明确授权有效期或长期有效；Codex 不追加审核或推断这些结论。
2. 预检返回 `authorized_inputs_ready`。
3. 真人可参考 `AI初审_非Gold` 工作表，在 private review 工作簿中完成章节范围、查询和知识点的最终 selection；不得填写答案或 qrels。本轮按用户要求不再追加 OCR、身份或仲裁信息审核，未填字段继续保持 pending。
4. 构建并验证真实未标注 candidate，生成 retrieval/mapping A/B 盲标包。
5. 两名真人独立标注，第三名真人分别仲裁；P1-00/P1-10 再决定 candidate 是否冻结。
6. 即使 candidate 获批，B-R1 仍需单独明确放行。
