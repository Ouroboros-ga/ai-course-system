# KG-MEST 多源证据与知识图谱接入方案

## 1. 目的与结论

拟接入的目标不是让大模型直接给学生“打分”，而是建立一条可审计的链路：

```text
原始学习事实
  -> 受作用域保护的 LearningEvent
  -> 可复核的 LearningEvidence
  -> 学生 × 课程 × 知识点的多维状态
  -> 图谱约束的诊断、补学、复习或迁移练习候选
  -> TeachingAgent 组织教学语言
```

本文把资料中的方案命名为 **KG-MEST**（Knowledge Graph Enhanced Multi-source Evidence State Tracing）。它是后续研究和 Shadow 接入的目标架构，不是当前生产功能已经具备的声明。

当前最合理的接入方式是：先在研究/影子读路径形成新的多维认知状态 Provider；仅在达到评测和隐私门禁后，由教学智能体通过只读 Port 消费其结果。它不改写现有 `MasteryState`、既有推荐 API、正式学生 Memory 或数据库表。

## 2. 当前已验证的基础与差距

| 层 | 已有事实 | 与 KG-MEST 的差距 | 接入结论 |
| --- | --- | --- | --- |
| 学习事实 | `LearningEvent` 是追加式、带学生/课程作用域和幂等键的领域对象。 | 没有知识点集合、资源身份、测量角色、源事件去重组等冻结字段；事件类型也未覆盖代码、提示、对话结构标签和视频/实验事实。 | 不直接扩展生产契约；先定义研究专用输入适配 DTO。 |
| 证据 | `LearningEvidence` 保留 `event_refs`、置信度和来源。 | 不能区分“评分型表现证据”和“交互教学状态”；缺少多维值、可靠性因子、策略版本与稳定排序。 | 新 Provider 输出独立证据包，旧证据仅可作兼容输入。 |
| 掌握度 | `MasteryState` 有单分数、等级、置信度与证据引用。 | 不能表示 mastery、stability、independence、transfer、strategy_quality、recovery_efficiency、hint_dependency、recurring_error_risk 八维及不确定性。 | 保留为旧接口；新增只读多维状态视图。 |
| 旧规则 | `RuleBasedMasteryProvider` 可解释、可测试。 | 课程规则把 engagement/questioning 作为掌握度成分，违反“提问次数、观看时长不等于掌握度”。 | 不能作为 KG-MEST 表现轴的实现，也不能注入 TeachingAgent 的学生状态端口。 |
| 教育图谱 | 有课程/知识点/练习节点、`PREREQUISITE_OF`、`TESTS` 等受约束关系及快照概念。 | 尚无被验收的课程 Q-Matrix、可供生产使用的知识点锚定服务和已确认先修子图。 | 图谱只作为已验收快照的只读输入；不可根据 LLM 临时改图。 |
| 教学工作流 | LangGraph 教学工作流可通过 `StudentModelingPort`、图谱、检索与推荐 Port 工作，默认未注入生产运行时。 | 尚无合规的多维状态读服务和路径推荐服务。 | 工作流只消费结果，不能计算状态或越权写库。 |

以上判断来自当前代码与测试，不以历史规划、比赛材料或宣传文案作为实现证据。

## 3. 冻结的算法边界

### 3.1 状态粒度与输出

状态的最小作用域是：

```text
pseudonymous_student_key × course_key × knowledge_component_id
```

不产生跨课程、永久性的“学生画像向量”。每个知识点输出八个独立维度和不确定性：

```text
mastery
stability
independence
transfer
strategy_quality
recovery_efficiency
hint_dependency
recurring_error_risk
uncertainty
effective_evidence_weight
```

`mastery` 是评分型显性表现的结论；对话、提示、观看和访问行为不得偷偷改变它。交互语义应作为 `confusion_risk`、`inquiry_depth`、`hint_dependency`、`explanation_need` 等独立教学状态输出。

### 3.2 证据权重与可解释性

每条可消费证据的权重由下列因子相乘得到，并保留每个因子的输入值：

```text
source_reliability
× grounding_confidence
× task_discrimination
× independence_factor
× evidence_quality
```

任何状态或推荐输出都必须带有：

```text
policy_versions
evidence_refs
derived_from
reason_codes
confidence
confidence_reasons
rule_contributions
input_scope
data_version
```

列表采用稳定排序：`evidence_refs` 按 `sequence_number, evidence_id`；`derived_from`、`reason_codes`、`confidence_reasons` 稳定去重后按字典序；`rule_contributions` 按 `rule_id, effect, evidence_refs` 排序。

### 3.3 去重、作用域和拒绝语义

同一次作答的首次提交、评分回写与核验迁移必须由同一 `source_event_id`/`attempt_group_key` 关联，只能产生一次表现轴更新。不同学生、课程或图谱快照的输入混合时，整个请求拒绝；不得静默丢弃不匹配事件后给出部分结论。

已有 `LearningEvent` 进入 Shadow 时采用只读发布适配：只消费带评分的主 `quiz_answered` / `exercise_submitted` 事实；派生 `quiz_correct` / `quiz_incorrect` 明确不消费，防止同题重复计分。普通 `question_asked` 没有结构化、可锚定标签时不构成认知证据。发布侧必须把学生数值 ID 替换为假名化 `student_key`，并向适配器声明一个唯一的源学生和课程范围。

拒绝响应必须为完整结构，例如：

```json
{
  "status": "rejected",
  "error_code": "SCOPE_MISMATCH_REJECTED",
  "state": null,
  "recommendations": [],
  "rejected_evidence_refs": ["ev-03"],
  "details": {
    "expected_course_key": "course-a",
    "actual_course_key": "course-b"
  }
}
```

没有足够独立证据时，输出 `unknown` 或高不确定性，并优先提出诊断任务；不生成“已掌握”或补学路径结论。

## 4. 事件到状态的映射

| 输入事实 | 可支持的维度 | 不能据此推出的结论 |
| --- | --- | --- |
| 有评分、可锚定知识点的独立作答/测试用例 | mastery；延迟复测可支持 stability；变式题可支持 transfer | 单次正确不能证明稳定或迁移能力。 |
| 受控代码沙箱的编译、运行、测试用例、错误类型、修复链 | mastery、strategy_quality、recovery_efficiency、recurring_error_risk | 代码总分不能替代逐测试用例的证据；随机修改次数不能独立判断策略差。 |
| 结构化对话候选标签 | confusion_risk、inquiry_depth、explanation_need；提示请求可支持 hint_dependency | 问题多、表达复杂、对话长不得增加 mastery。 |
| 提示等级、撤除提示后的独立重做 | independence、hint_dependency | 使用提示本身不等于不会，只降低该次独立性因子。 |
| 视频回看、暂停、观看完成 | 仅低可靠性的教学上下文 | 观看时长、倍速、回看次数不等于掌握度或不掌握。 |
| 实验/模拟中的假设—操作—观察—解释链 | strategy_quality、transfer、recovery_efficiency | 单纯改参数次数没有稳定测量含义。 |

对话/LLM 只能产生带模型版本、提示词版本、置信度和证据片段的**候选证据**。候选低于冻结阈值、没有可锚定知识点、或同一来源事件重复派生时，不进入状态更新。

## 5. 知识图谱在此架构中的角色

图谱不是展示层，也不是让 LLM 自由查询的数据库。已验收、课程隔离的 `GraphSnapshot` 在 KG-MEST 中只承担四件事：

1. **知识点锚定**：把题目、代码测试和对话证据映射到课程内的知识点，并提供锚定置信度。
2. **Q-Matrix**：说明题目/测试用例测量哪些知识点、诊断价值和题型/难度信息。
3. **先修一致性检查**：依据已验收的 `PREREQUISITE_OF` 边识别已确认薄弱先修，而不是凭当前题目猜测前置缺口。每条可消费边必须有课程范围、非空 `evidence_refs` 和 `review_record_id`；仅标记为 `accepted` 不能成为推荐输入。未来由既有 `education_graph` 的 GraphNode / GraphRelation / ReviewDecision 只读课程导出，经研究区发布适配器验证后供 Shadow 消费。
4. **资源与路径解释**：在已确认薄弱先修集合、当前知识点、复习和变式练习之间选择可追溯资源。

图谱接入的前提是存在课程隔离、可回滚、版本化的验收快照。无快照时，算法只能输出当前点的诊断/练习候选，不能伪造先修路径。

## 6. 推荐决策

第一版采用规则和图搜索，不使用强化学习。推荐器先用不确定性决定“诊断”还是“干预”，再使用八维状态与图谱作候选排序：

```text
高 uncertainty                  -> 诊断题/澄清追问
已确认薄弱先修 + 表现不足       -> confirmed_weak_prerequisite_set 的复习
低 mastery + 重复错误模式        -> misconception_repair
可完成但 hint_dependency 高      -> 渐隐提示后的独立练习
mastery 高但 transfer 低         -> 变式/真实场景练习
mastery 高但 stability 低        -> 间隔复习
```

这里的输出名称统一为 `confirmed_weak_prerequisite_set`（已确认薄弱前置集合），不是“最小补学集合”。它只包含有合格状态证据、足够置信度和已验收先修边三者同时成立的节点。低置信候选只进入 `evidence_needed_set`。

## 7. 分阶段接入路线

### P0：运行基线和依赖审计（阻断生产验证）

1. 扫描应用真实 import，补齐 `pyproject.toml` 的运行依赖并在干净环境执行 `uv sync`。
2. 在禁止启动副作用的配置下验证 `import app.main`，再运行既有路由回归测试。
3. 这一步不安装 Paddle/PaddleNLP 到主应用依赖，不连接生产数据库。

当前 `.venv` 已确认缺少既有主应用实际 import 的 `sqlmodel`、`python-jose`、`python-multipart`、`bcrypt`、`pillow`、`pymupdf`、`docling`、`transformers`、`onnxruntime`、`pdfplumber`、`python-docx` 与 `python-pptx`；另缺 LibreOffice 与 FFmpeg/FFprobe。`jose` 是主应用导入的第一个阻断点，不能据此误判只有它一个问题。

根目录 `pyproject.toml` 是当前根 `.venv` 的清单，却只声明了少量 Web/工作流包；`backend/pyproject.toml` 才包含历史主应用依赖，但它限制 Python `<3.13`，而当前根环境是 Python 3.13。并且通过常规 `from app.common.dependency_checker import ...` 甚至会先经过 `app.common`/`app.core` 的导入副作用并在缺少 `jose` 时失败。故 P0 必须先选定唯一的项目根和 Python 版本，取消“启动时自动 pip 安装”作为运行前提，再生成可复现的锁文件。这是依赖治理问题，不是 KG-MEST 或 LangGraph 引入的问题。

### P1：研究契约与合成数据（不接生产）

在 `research/product1_cognition/` 中实现并测试以下独立对象：

```text
ResearchLearningEventAdapter
EvidenceSignal
ConceptStateVector
BetaStateUpdater
EvidenceDeduplicator
GraphConstrainedPathPlanner
```

使用假名化合成 fixture 覆盖：首次正确、核验迁移重复、延迟复测、变式题、提示依赖、同类代码错误、对话低置信标签、跨学生/课程混入和无图谱快照。结果只能表述为“合成数据上的一致性与规则行为”，不能表述为真实教学效果。

### P2：离线对照与研究冻结

保留规则基线，新增版本化实验候选（例如时间衰减、冲突感知 Beta 更新、贝叶斯证据融合）。对每个候选固定：数据版本、策略版本、输入范围、指标、消融、失败案例和已知限制。

PaddleNLP 可在隔离的研究虚拟环境中用于中文对话结构化标签、信息抽取、嵌入或重排的离线对照；它不提供现成的“学生八维认知 + 课程知识图谱路径推荐”业务算法，也不得改变正式表现分。Paddle 的图学习/深度学习组件可作为后期实验工具，不替代事件契约、证据去重、图谱验收和解释审计。

### P3：Shadow 只读接入

仅当 P2 达到研究冻结后，新增由领域 Owner 提供的只读端口：

```text
get_concept_state(student, course, concept)
get_confirmed_weak_prerequisite_set(student, course, concept)
recommend_learning_path(student, course, concept)
```

返回值必须同时携带图谱版本、策略版本、证据引用和拒绝语义。Shadow 运行只记录对比结果，不写正式 Memory、不改变进度、不影响现有推荐或回答。

### P4：教学智能体消费与晋级

TeachingAgent 的 `StudentModelingPort` 和 `RecommendationPort` 只读取 P3 已验证的输出。LangGraph 继续负责顺序编排、降级和追踪；确定性状态更新与路径排序仍在领域 Provider 内。进入用户可见推荐前必须通过真实数据 Canary、人工金标、教师审核、失败率阈值和回滚演练。

## 8. 验收门禁

| 门禁 | 最低证据 |
| --- | --- |
| 研究可复现 | 固定 fixture、策略/数据/图谱版本、标准库测试、确定性重跑结果。 |
| 证据合规 | 假名化受保护数据边界；无真实聊天、Memory 或生产数据库被用作 fixture。 |
| 算法正确性 | 同序列结果确定；去重有效；交互语义不能修改 `mastery`；无证据为 `unknown`。 |
| 图谱正确性 | 课程隔离、已验收快照、无环先修约束、资源与边均可追溯。 |
| Shadow 安全 | 只读、append-only 审计、超时/不可用降级、开关与回滚；不影响 V1。 |
| Preferred 晋级 | 真实数据 Canary、人工金标、对照实验、教师审核、隐私审计、回滚方案。 |

## 9. 近期执行顺序

1. 修复并验证主应用依赖清单，使现有应用能被可靠导入；这是所有 API 级验证的前置条件。
2. 在研究区完成 P1 的八维状态、证据去重、显性交互分离和合成测试；不修改旧 `rule_baseline.py`。
3. 复用已验收的课程侧车图谱快照做 P2 的锚定、Q-Matrix 和先修路径离线实验。
4. 输出综合 Research Iteration Report 后，决定是否具备 P3 Shadow 条件。

在第 1 项完成前，不宣称主应用已完成 KG-MEST 接入；在第 2 和第 3 项完成前，不向教学智能体注入真实学生建模或推荐 Port。
