# B-G0b 人工双盲标注与仲裁协议

版本：`product1-graph-retrieval-human-annotation/1.0`。本协议只准备人工 gold；不实现 BM25、Dense、Hybrid、GraphRAG，也不授权 B-R1。

## 角色与独立性

- 标注员 A 与 B 必须是两名不同团队成员，分别独立完成 retrieval 和 mapping 包。
- 仲裁员必须是第三名团队成员，不得等于 A 或 B。
- Agent、脚本或两个 Agent 输出不能冒充两名人工标注员。工具仅记录 `member_id`，真实性由 P1-10 查看外部证据核验。
- A/B 在提交前不得互看标签，也不得看到算法 score、rank、推荐答案或 gold。候选顺序只按稳定 research ID 升序。

## 校准

正式标注前，由三人使用不进入正式 test gold 的校准样例共同讨论边界；记录争议类型、最终解释和协议是否修订。不得把校准共识预填进正式包。校准记录使用 `calibration_record_template.md`。

## Retrieval 标注

先判定 query 的 answerability，再逐证据块标 0/1/2。`direct_support` 必须足以直接支持答案主张；`partial_support` 只支持部分条件或背景；其余为 0。无答案查询的全部候选通常为 0，但若类型是 `evidence_stale_only`，必须在备注中解释过期证据为何不能作为当前答案。

每条非零 qrel 必须闭合到冻结 Evidence ID、来源页/slide、unit/block ID 和引用文本片段。无证据不得创建 Citation。

## Mapping 标注

以“知识点是否由该页承担主要教学职责”为 2，以补充、例题、总结或必要铺垫为 1，以同词但不同语义等硬负例为 0。允许多页 2、多页 1；不得强制单页。每个非零页面必须保留 `research_evidence_ids`。每个 mapping candidate 必须带受控 `controlled_source_ref`，标注员必须查看原始页面视觉内容；PPTX 文本层、PDF 文本层和 OCR sidecar 都不能替代原页。OCR 的 bbox、置信度和引擎分数不得进入 A/B 盲标包，避免锚定判断。`chapter_distance` 优先按同课程章节树边数计算；无章节树但同一 document 有页码时才使用绝对页差；其余标记 unknown/missing，跨课程报错，禁止把两种距离混合。

## Evidence 最小充分性

- Evidence 单元必须闭合到 `research_evidence_id`、artifact/document/unit/block、字符区间和来源页；文本片段与来源区间不一致时停止标注并报数据错误。
- 标为 2 的单条 Evidence 必须直接建立问题所问事实，或建立多跳问题中不可缺少的一个核心命题；不能依赖未写出的常识或猜测补全。
- 最终支持集合采用“删除任一条就不再足以支持答案”的最小集合。仅重复、过宽或只有主题相关性的块不得因关键词重合标为 2。
- 没有闭合且最小充分的 active Evidence 时不得生成 Citation，也不得把 annotation note 当成证据。

## 跨课程与 stale Evidence

- A/B packet 只能包含查询/知识点所属 `course_id` 的候选。发现跨课程候选属于 packet 构建失败，必须停止并重生成；不得把它标 0 来掩盖污染。
- `scope_not_available` 表示所请求课程或课程范围未提供，不能借用另一门课的相似内容回答。
- `status=stale` 的 Evidence 对当前答案 relevance 固定为 0，不进入 Citation。只有 stale 材料能匹配且没有 active Evidence 时，answerability 标为 `evidence_stale_only` 并说明原因。
- 同一问题存在有效 active Evidence 时按 `answerable` 正常标注；stale 副本仍保持 0，不能与 active 版本合并。

## 不确定标签

- 每个 answerability 和 relevance 判断都必须填写 `needs_adjudication=true|false`。盲标包初始为 `null`，完成包仍为 `null` 时校验失败。
- 标注员不确定时仍选择一个最接近的合法临时标签，在 `annotation_note` 说明歧义，并设置 `needs_adjudication=true`；不得自造第四级 relevance 或 `unknown` 最终标签。
- 只要 A 或 B 标记不确定，该键必须进入仲裁，即使两人的临时标签完全相同。仲裁员给出唯一合法 `final_value` 和理由。
- P1-00 发现系统性歧义时应先修订协议并重新校准；不能让仲裁员临时改变全局口径。
## 提交与仲裁

1. A/B 分别填写所有空标签，设置 attestation 为 `completed_independently_without_algorithm_rankings`。
2. 工具验证角色 A/B、不同 member ID、来源 manifest hash、冻结契约和候选集合完全一致。
3. retrieval 与 mapping 分别 compare；输出标签分歧及任一方标记不确定的全部键，不自动决定最终标签。仲裁员逐项填写 `final_value`，分别保存为 `annotation/retrieval_adjudication.json` 和 `annotation/mapping_adjudication.json`。
4. finalize 要求所有分歧恰好解决一次，且仲裁员与 A/B 不同。缺一项、多一项或身份冲突即失败。
5. 产物 hash、原始 A/B 包、仲裁包和协议版本进入冻结报告；P1-00 复核语义口径，P1-10 复核真人身份、独立性、完整性和访问隔离。

## 门禁状态

`approved_candidate` 只表示 B-G0b 候选完整。其 `eligible_for_algorithm_comparison` 仍为 false，`b_r1_release` 仍为 `blocked_requires_separate_explicit_authorization`。B-R1 需后续单独明确放行；B-R2 必须复用届时 B-R1 的唯一 BM25/tokenizer 实现。



