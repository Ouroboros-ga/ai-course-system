# B-G0b 真实输入预检报告

- 检查日期：2026-07-16
- 结果：`BLOCKED_PENDING_AUTHORIZATION_VALIDITY_AND_HUMAN_SELECTION`
- 真实输入：4 门课、8 个 PPTX/PDF 文件、253 页，页数配对闭合
- 候选目录：未创建
- 人工标签：未创建
- B-R1/B-R2/B-R3：未放行

## 检查结果

真实课件已经到位，并已由根 `.gitignore` 排除。PPTX/PDF 页数、SHA-256、原生文本覆盖、隐私风险和 PaddleOCR 3 结构化抽样结果见 [human_gold_source_ocr_preflight.md](human_gold_source_ocr_preflight.md)。

用户已确认授权/隐私审签完成，且材料仅限“智能课程系统”项目内部离线评测、不得对外分发。当前仍缺少授权有效期、责任人/证据引用、逐课文件与原页隐私复核记录，以及完成后的真人 query/KP/章节/OCR selection。工具不能替代这些签署记录，也不能把种子提示或自动正则检查冒充人工 Gold，因此仍不得创建 `human_gold_candidate_v0_1`。

## 已实现的准备能力（真实数据阶段未执行）

- 授权来源 manifest schema 现以每门课 `pptx_source + pdf_reference` 为原始输入，避免先要求转换后文件的循环依赖。
- fail-closed 来源预检、hash、路径闭合和扩展名校验。
- 候选 manifest、human selection、治理记录和人工标注 schema。
- 未标注 candidate 构建/验证 CLI：稳定 ID、byte/content hash、Evidence/Citation/slide 引用闭合、脱敏扫描、split 隔离和固定规模门禁已在合成契约输入上验证；真实目录仍未创建。
- 无 rank/score/gold 的双盲包准备与校验规则。
- A/B 不同 member ID、第三人仲裁、全部标签分歧和不确定标签闭合校验。
- public index input / gold-only 隔离与候选集禁评测闸门。
- P1-00 / P1-10 清单及身份、校准、仲裁、冻结报告模板。

## 解除阻塞

材料责任人按 [human_gold_input_requirements.md](../../../docs/research/graph_retrieval/human_gold_input_requirements.md) 将现有授权/隐私审签落入 `authorized_source_manifest.json`，补齐有效期、责任人/证据引用和逐课复核记录；查询与知识点策划人完成 private selection review。两个 fail-closed 预检均通过后，方可从原件生成脱敏、未标注的候选数据和 A/B 盲标包；Gold 只能由至少两名真人独立标注并由第三名真人仲裁。