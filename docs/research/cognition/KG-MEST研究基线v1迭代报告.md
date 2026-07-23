# KG-MEST 研究基线 v1：迭代报告

## 本轮回答的问题

能否在不访问真实学生数据、不修改生产认知分数的情况下，将多源学习事实转换为可解释的知识点级认知状态，并让图谱约束补学/复习候选？

答案是：在合成输入上，基线已经具备此能力；尚未证明对真实学生的认知诊断准确率或教学效果。

## 已实现

- 八维知识点状态：掌握、稳定、独立、迁移、策略质量、纠错效率、提示依赖、重复错误风险；另有不确定性/有效证据权重。
- 每一维维护 Beta 单元，按维度半衰期做确定性增量更新。
- 评分型显性事件与代码测试用例事件提取表现证据；代码提交优先使用测试用例通过率，而不是粗略总分。
- 对话只产生困惑、探究、提示依赖、解释需求等交互状态；分类置信度低于 `0.70` 时忽略，绝不改写 `observed_performance_score`。
- 同一 `source_event_id` 的同知识点/同维度证据稳定去重；首次作答与核验迁移不能重复计分。
- 固定最近 10 个独立交互证据窗口；正负交互证据相等时输出 `unknown`，而非武断结论。
- 学生、课程或知识点作用域混入时整批拒绝，不返回部分状态，并携带被拒绝证据和期望/实际作用域。
- 使用冻结的合成先修图返回 `review_confirmed_weak_prerequisite`，低/未知置信度仅返回诊断任务。
- 合成 Q-Matrix 可将有评分但未显式带知识点的任务锚定到课程知识点；未映射任务不产生表现证据。

## 策略版本

```text
KG-MEST baseline:        kg-mest/research-baseline/1.0
scoring policy:          observed-performance/1.0
confidence policy:       evidence-confidence/1.0
interaction policy:      interaction-state/1.0
recommendation policy:   graph-path/1.0
```

每个状态输出同时带有证据引用、来源、原因码、置信原因、规则贡献、数据版本和策略版本。稳定排序已由基线固定。

## 复现

```powershell
$env:PYTHONPATH = 'research\product1_cognition'
.\backend\.venv\Scripts\python.exe -m unittest discover -s research\product1_cognition\tests -p 'test_kg_mest.py' -v
```

本轮结果：45 项通过，含版本化合成课程 fixture 回放、契约消融、PaddleNLP 候选适配器、逐标签金标评测入口、Shadow 门禁、图谱适配审计、遗留关系候选桥接、教育图谱发布适配、受审核 Q-Matrix 适配、既有 LearningEvent 只读适配、端到端 Shadow 回放、治理 bundle 预检/完整性校验以及真实 LangGraph 的合成只读消费测试。测试不访问数据库、真实学生聊天、正式 Memory、LLM、Paddle 服务或外部网络。

## 契约消融（不是准确率实验）

相同 `synthetic-course-v1` fixture 的输出如下：

| 方案 | 表现分/行动 | 可得出的结论 |
| --- | --- | --- |
| KG-MEST baseline | `0.50`，`review_confirmed_weak_prerequisite` | 目标点有中等置信表现证据，已确认先修点薄弱。 |
| 去掉 Q-Matrix | `null`，`diagnose` | 未锚定的评分任务不能成为表现证据。 |
| 反例：把 2 条交互标签加到表现分 | `0.70` | 分数被对话量虚高；该反例违反表现/交互分离契约。 |
| 反例：取消源事件去重 | `0.5664`，3 条而非 2 条表现证据 | 同一次作答的迁移副本会改变结果；该反例违反去重契约。 |

复现命令：

```powershell
$env:PYTHONPATH = 'research\product1_cognition'
.\backend\.venv\Scripts\python.exe -m benchmarks.kg_mest_ablation
```

这里没有真实学生标签，因此任何“更准确”或“提升教学效果”的表述都不成立。

## 与旧基线的差异

现有 `RuleBasedMasteryProvider` 把 engagement/questioning 纳入掌握度；KG-MEST 不复用这一语义。二者并存，旧 Provider 不被修改，也不被 KG-MEST 研究基线调用。

## 已知限制

- 输入仍是合成、假名化 DTO；尚未实现生产事件适配器，也未得到真实课程 Q-Matrix 或可用图谱快照。
- Beta 参数、半衰期和阈值是研究启发式，未经过真实学生数据校准。
- 对话提取器只消费外部已分类标签；PaddleNLP/LLM 可在独立实验中提供候选标签，但不能直接成为正式表现结论。
- 当前图搜索是确定性先修规则，不是最短路径、Beam Search、GNN 或强化学习实现。

## Shadow 门禁现状

`benchmarks/shadow_gate.py` 将研究到 Shadow 的门禁机械化。当前状态为 `not_ready`，原因不是代码测试失败，而是没有：已验收课程图谱快照、经审批的受保护人工金标、隐私审查、真实 Provider 契约测试和 append-only 审计。即使未来门禁通过，晋级也仅为 `read_only_shadow`，不改变现有用户行为。

### 遗留知识关系的安全复用

现有 `KnowledgeRelation` 有 `prerequisite` 类型，但记录本身没有课程隔离、关系证据或人工验收状态；`KnowledgePoint.prerequisites` 还是逗号分隔自由文本。因此二者都不是可直接用于路径推荐的正式先修图。

研究区新增 `cognition/legacy_prerequisite_candidates.py`：它只接受外部导出的、已补齐 `course_id` 的只读关系快照，并输出带来源版本和 `legacy_knowledge_relation:<id>` 引用的 `status="candidate"` 边。候选边必须经图谱治理流程补充证据、课程范围、人工验收和无环检查，成为 `status="accepted"` 后，`adapt_cognition_graph` 才会消费。适配器现在还强制每一条已验收边具有非空 `evidence_refs`、`review_record_id` 和等于请求课程的 `course_id`；仅伪造 `status="accepted"` 会整批拒绝。测试明确证明 candidate 边和缺元数据的伪验收边都不能绕过该门禁。

系统已有 `education_graph` 的纯领域模型：`GraphNode`、`GraphRelation`、`ReviewDecision` 和先修 DAG 校验。新增 `cognition/education_graph_release_adapter.py` 用这些既有字段的**只读导出**构造 KG-MEST 输入：节点与关系均需 `accepted`、各自的证据 ID，关系需匹配的、带 `evidence_bundle_id` 的已接受审核决定，并全部绑定同一 `course_id`。其中 `PREREQUISITE_OF` 构造路径约束，`TESTS` 构造冻结 Q-Matrix（任务到知识点）并可携带任务区分度。它不导入主应用、不查数据库、不写快照指针。这样，未来只要教育图谱按既有领域契约发布一个课程隔离导出，就能进入认知 Shadow；R2 结构检索图仍不会被误用。

现有 `domain/learning/LearningEvent` 有追加式 ID、学生/课程范围、时序和版本字段，可作为受保护只读导出的来源。新增 `cognition/learning_event_release_adapter.py` 只消费有评分的 `quiz_answered` / `exercise_submitted`，把数值分数或 `is_correct` 映射为显性表现；`quiz_correct` / `quiz_incorrect` 是同一次作答的派生事件，明确跳过以避免重复计分。普通 `question_asked` 因缺少知识点锚定与置信度标签而不会变成认知证据；只有外部结构化标签齐全时才作为独立交互状态输入。导出前将学生 ID 替换为受保护假名，任一学生或课程混合都会整批拒绝。

交互候选现已贯穿来源绑定：候选必须声明与原 `question_asked.event_id` 相同的 `candidate_source_event_id`，否则不消费。交互状态报告保留每个候选的分类置信度、证据片段、模型版本、提示词版本和候选策略版本；这些仅解释 `confusion_risk` 等教学状态，绝不写入 `observed_performance_score`。当前本地 UIE-mini 仍是低质量零样本候选，不能当作已验证分类器。

`cognition/shadow_pipeline.py` 将两份已治理的只读发布组合为一次端到端 Shadow 回放：课程图 → 先修约束和 Q-Matrix，事件 → 可锚定评分证据，随后运行 KG-MEST、交互状态和路径建议。图发布或事件发布任一失败时返回零状态、零推荐；任务无 Q-Matrix 映射时仅报告未映射，不产生证据。该编排器用于离线/Shadow 对照，不导入主应用、不写数据库、Memory 或既有 MasteryState。

为避免 Shadow 启动时靠人工拼参数，新增 `cognition/shadow_bundle.py` 和 `tools/run_shadow_bundle.py`。它要求本地 bundle 明确声明受保护假名化数据、课程/快照/数据版本、源范围和九项 Shadow 门禁；门禁未齐时不运行。四份输入工件还必须带 canonical JSON SHA-256，防止审核过的 bundle 静默换成另一份图或事件。输出报告不包含源学生 ID、源课程 ID 或原始事件 payload。此工具只是对已授权本地导出的预检与回放入口，不读取生产数据库，也不替代隐私审批或人工金标。

`fixtures/shadow_bundle_synthetic_v1/` 提供五文件、完全合成的可执行示例，用于验证命令入口和报告格式。示例中的 ID `1/2` 是 fixture 标识，绝非真实学生或课程；它不构成真实 Shadow 获批证据。

真实数据的字段映射、禁止项和人工签核项已整理在 `KG-MEST真实Shadow数据交接清单.md`。这份清单将现有 `education_graph` / `LearningEvent` 字段、研究 bundle 和 Shadow 门禁对齐，避免数据负责人把结构检索图、自由文本先修或派生 quiz 事件误交付为正式认知输入。

资料原始要求与现有实现/外部前提的逐项对照见 `KG-MEST接入完成度审计.md`。该审计明确将“研究已实现”“Shadow 已准备”和“未实现/待外部条件”分开，防止合成回放被误述为真实教学算法上线。

已有 R2 课程侧车仅提供课程结构/证据/PPT 映射图，其谓词集不含已验收的 `PREREQUISITE_OF`。`cognition/graph_adapter.py` 因而会明确拒绝把它误用于补学路径；它仍可用于课程检索、知识点锚定和引用闭包。

## TeachingAgent 消费验证

研究侧 `cognition/teaching_adapter.py` 只读地将 KG-MEST 的表现分、置信度、八维风险、证据引用、原因码和策略版本映射到 TeachingAgent Port。合成先修状态已经通过真实 LangGraph 运行，得到 `prerequisite_review / confirmed_weak_prerequisite`。它没有注入应用运行时。

同时，TeachingAgent 策略现在将缺失 `mastery_score` 视为 `observed_performance_unknown` 并提出诊断问题；未知交互/迁移等维度不会被转换成 0 分而触发错误教学策略。

## 下一轮

1. 构建版本化合成课程图、Q-Matrix 与跨知识点测试 fixture。
2. 增加时间衰减/冲突感知参数的离线消融和失败案例报告。
3. 在独立 PaddleNLP 环境比较结构化交互标签候选，保留规则标签基线。
4. 只有完成金标、隐私、课程隔离和 Shadow 门禁后，才实现只读 `StudentModelingPort` 适配器。
