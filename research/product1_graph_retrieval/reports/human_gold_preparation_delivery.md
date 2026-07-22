# B-G0b Human Gold Preparation 交付记录

- 状态：`SELECTION_REVIEW_MATERIAL_READY_HUMAN_FINALIZATION_PENDING`
- 真实输入：4 门课 PPTX/PDF 双格式已到位并已忽略
- 当前阻塞：96 条 query、71 个知识点、36 个章节的最终人工 selection 尚未填写；授权有效期/长期有效字段仍为空
- 候选数据：未创建
- 人工标签：未创建
- B-R1/B-R2/B-R3：保持 blocked

## 已交付

- 原始输入隔离、页数/格式/hash 审计和 PaddleOCR 3 结构化抽样报告。
- `.xlsx` 与四个 CSV 的结构、编码、逐值导出一致性和人工复核状态审计；新增 seed export fail-closed 审计器。
- 已生成确定性的 private pending review JSON：`reports/human_selection_review_pending_v0_1.json`，包含 4 门课、96 条查询、71 个知识点、36 个章节和 41 个原页/OCR 复核任务；SHA-256 为 `c9409be83211163ee0d266d6ca3cca28685fd9909d0eda0048e29af15634d0cb`。
- 已生成可填写的 `B-G0b人工Selection复核工作簿_v0_1.xlsx`；SHA-256 为 `5aad0a1cd642c80910defafcff9ff1f932d3d600b721c800ee7d93e38949b452`，项目导入器往返验证通过。`AI建议/初审理由` 按用户确认可作为复核材料保留在三张显式命名的 `AI初审_非Gold` 工作表中，不会被导入为最终 selection 或 Gold。
- private review 工作簿已补齐最终签署字段；新增确定性 XLSX 导入器，只导入人工作业列并拒绝来源/建议列篡改、公式、缺行、增行或重复稳定 ID。
- 原始来源 manifest schema：每门课 `pptx_source + pdf_reference`，授权、用途、有效期、隐私和仓库存储字段 fail-closed。
- `human_gold_candidate` manifest、source contract、selection、annotation、governance schema 与 release checker。
- 未标注 candidate 构建器、稳定 research ID、文件/content hash、记录级引用闭合、PII 扫描、split 隔离和盲标包准备；已在合成契约输入上完成字节级复现与篡改失败测试。
- retrieval/mapping A/B 双盲 packet、完整分歧比较、不确定标签强制仲裁和第三人 finalize。
- direct identifier 扫描、public/gold-only 隔离和 pending 禁止算法评测。
- 人工标注协议、身份/校准/仲裁记录、P1-00/P1-10 清单和冻结报告模板。

## 未执行

- 未从这 4 门真实原件生成 DocumentIR、Evidence、slides 或候选盲标包；当前只生成了 selection 复核材料。原因是最终人工 selection 尚未签署、source manifest 的有效期字段尚未闭合，而不是构建器缺失。
- 未填写 retrieval/mapping 标签或 qrels。
- 未把 `AI建议/初审理由` 自动采纳为人工决定；它们只用于复核参考，人工最终字段保持空白。
- 未调用真实 LLM、向量服务、生产数据库或托管 OCR API。
- 未接入 production OCR，未修改 `backend/app/**`、生产依赖或锁文件。
- 未放行 B-R1，也未实现 BM25、Dense、Hybrid、RRF 或 Graph Retrieval。

## 本轮验证证据

- `.venv\Scripts\python.exe research/product1_graph_retrieval/tools/human_selection_review.py validate research/product1_graph_retrieval/reports/human_selection_review_pending_v0_1.json`：`valid=true`。
- 工作簿经 `human_selection_workbook.py` 往返导入：`status=pending_human_review`、`valid=true`，数量保持 4/96/71/36/41。
- 禁用字段扫描：`score`、`rank`、`qrels`、`answerability`、`gold_answer_hint`、`expected_answerability`、`model_answer` 均为 0 命中。
- `.venv\Scripts\python.exe -m unittest discover -s research/product1_graph_retrieval/tests -v`：50 项离线测试通过。
- B-R1 release checker：`status=blocked`；缺少 human Gold、独立人工标注/仲裁、P1-00/P1-10 批准和单独 B-R1 release。
- Draft 2020-12 schema 自检：9 份通过。
- Python AST 检查：33 个研究侧 Python 文件通过。
- 上述数字仅证明准备链契约与失败关闭行为，不代表真实 retrieval/mapping 准确率或人工 Gold 质量。

## 下一门禁

复核人可直接使用工作簿中的 `AI初审_非Gold` 材料辅助判断，在黄色人工列中确认 96 条查询、71 个知识点和章节范围，并补齐 source manifest 有效期字段。用户已明确本轮不再要求 Codex 追加 OCR 质量、人工身份或仲裁信息审核；这些字段不由 Codex 推断，也不会被自动填充。人工 selection 完成且预检通过后，Codex 才能继续生成脱敏且未标注的 `human_gold_candidate_v0_1`。后续真实 Gold 仍须按已冻结门禁由不同自然人标注/仲裁并由 P1-00/P1-10 确认。
