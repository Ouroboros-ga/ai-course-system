# KG-MEST 接入完成度审计

审计基准：`多源学习证据识别与知识图谱驱动学习路径推荐架构`。本文件以当前代码和测试为证据，不把规划、README、合成 fixture 或展会演示当成生产完成证据。

状态含义：

- **研究已实现**：研究区有可复现代码和自动化测试。
- **Shadow 已准备**：具备受治理输入后的只读运行能力，但尚未在真实受保护数据上执行。
- **未实现/待外部条件**：没有相应代码，或缺少必须由人/平台提供的输入与批准。

| 原始资料要求 | 当前证据 | 状态 | 不能据此声称的结论 |
| --- | --- | --- | --- |
| 知识点级 `student × concept × state_vector`，8 维状态 | `research/product1_cognition/cognition/kg_mest.py` 的 `Dimension`、`BetaCell`、`ConceptState`；研究测试覆盖。 | 研究已实现 | 不代表对真实学生的八维识别准确。 |
| Beta 增量更新和按维度时间衰减 | `BetaCell.update` 与 `HALF_LIFE_DAYS`。 | 研究已实现 | 半衰期尚未经真实数据校准。 |
| 可靠性 × 锚定 × 任务区分度 × 独立性 × 质量 | `EvidenceSignal.weight`；显性评分、代码测试用例提取器。 | 研究已实现 | 当前权重是基线参数，不是教育学实证参数。 |
| 表现轴与交互语义分离 | `MeasurementRole`、交互状态提取器和“交互不改变表现分”测试。 | 研究已实现 | 交互标签本身尚无真实金标性能。 |
| 同题派生事件不重复计分 | `learning_event_release_adapter.py` 明确跳过 `quiz_correct/quiz_incorrect`；有单测。 | Shadow 已准备 | 不能补偿上游没有正确记录的 attempt 关系。 |
| 代码测试用例、修复链、策略与纠错证据 | `CodeEvidenceExtractor` 已支持合成 `code_submission`。 | 研究已实现 | 现有主应用尚未提供受治理的代码沙箱事件导出。 |
| 对话结构化候选，保留模型/提示词/片段/置信度 | Paddle 候选适配器与交互来源绑定、provenance 测试。 | 研究已实现 | 本地 UIE-mini 零样本未显示可用召回，不能进入真实 Shadow。 |
| 视频与实验/模拟行为证据 | 原始资料建议的模态。 | 未实现/待外部条件 | 当前没有视频或实验链路，且观看时长不会被用作掌握度。 |
| 已验收图谱：先修 DAG、Q-Matrix、资源索引 | `education_graph_release_adapter.py` 将受审核 `PREREQUISITE_OF` 和 `TESTS` 关系转为图快照；R2 结构图明确拒绝被误用。 | Shadow 已准备 | 仓库中没有已验收真实课程先修图。 |
| 图约束补学/复习路径推荐 | `LearningPathRecommender` 与端到端 Shadow 测试。 | 研究已实现 | 合成路径结果不等于真实学习效果。 |
| Agent 消费状态并给出教学响应 | `teaching_adapter.py` 与真实 LangGraph 的合成只读测试。 | Shadow 已准备 | 未注入应用运行时，不影响当前用户回答。 |
| 事件、证据、状态、建议、审计持久化 | 研究输出有版本、证据引用和原因码；Shadow bundle 是本地只读。 | 未实现/待外部条件 | 没有正式五表、append-only 实现或生产写入授权。 |
| 受保护数据、金标、隐私和只读 Shadow 门禁 | `shadow_gate.py`、bundle 完整性校验、数据交接清单。 | Shadow 已准备 | 门禁字段不能由研究代码自行宣布为真。 |
| Preferred/正式学生影响 | 没有实现。 | 未实现/待外部条件 | 不能开启 Feature Flag、改 API、写 Memory 或改变推荐。 |

## 当前客观结论

当前达到的是：

```text
研究基线 + 受治理输入适配 + 完整性校验 + 合成端到端只读 Shadow 回放
```

尚未达到的是：

```text
真实数据 Shadow
真实金标评测
生产 Provider 接入
对学生产生影响的正式算法
```

## 真实 Shadow 的最小验收证据

1. 一门课程的审核通过图：每条 `PREREQUISITE_OF` 和 `TESTS` 有证据、审核记录、课程范围且无环。
2. 经批准的单学生/单课程假名化事件窗口；至少含可评分事件，并与 Q-Matrix 任务 ID 对齐。
3. 对话候选若进入对照，必须有受保护人工金标及按标签的 precision/recall/F1 和失败案例；UIE 零样本空输出不能当作通过。
4. 隐私负责人、图谱审核人、评测负责人、平台负责人按 [真实 Shadow 数据交接清单](KG-MEST真实Shadow数据交接清单.md) 签核。
5. bundle 校验、研究测试和只读运行结果存入 append-only 审计位置；运行前后验证没有生产写入。

只有以上证据齐全，状态才能从“Shadow 已准备”变为“真实 Shadow 已执行”。此后仍需要 Canary、人工金标结果、教师审核和回滚方案，才可讨论 Preferred Promotion。
