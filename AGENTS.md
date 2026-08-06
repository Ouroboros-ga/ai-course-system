# AGENTS.md

本文件是本项目 Agent 行为的唯一权威规则。与历史文档冲突时以本文件为准;
与 `CLAUDE.md` 冲突时以本文件为准(`CLAUDE.md` 仅在多 Agent 并行任务卡片
模式启用时补充,当前阶段不启用)。

---

## 1. 当前阶段

项目处于**本地原型 Demo 与能力持续打磨阶段**。Agent 架构迁移已完成并已推送,
三智能体(TeachingAgent / Prep Agent / Coding Agent)已按
`backend/app/platform/agents/` 下的目录结构物理分离,共享 Runtime/Contracts/
Providers/Tools 层已落地。bootstrap 已注入真实 Judge0 沙箱、真实 LLM 与各
session-scoped Port,不再使用 fake provider 占位实现。

本阶段的工作原则:

- 优先保证可运行、可体验、可回退的端到端闭环;
- 允许试错、替换旧实现和局部/模块级重构,但必须同步更新真实调用方;
- 用可运行行为、手工体验、样例数据、日志、自动化测试或命令输出记录结论,
  不得假定旧实现正确,也不得假定文档描述等同于已实现;
- 每次有意义的改动保持可理解、可运行、可回退;
- 历史 Demo、Shadow 和旧 API 可被替代,但必须明确迁移或下线语义。

**这不是线上生产环境授权**。真实学生数据、真实生产数据库、真实密钥和未经
授权的付费外部服务不进入开发、测试或提交物。

---

## 2. 仓库与架构事实

以下为代码实际结构,Agent 工作时必须以此为准,不得从历史文档推断:

### 2.1 后端布局

- `backend/app/api/v1/endpoints/`:已注册的 FastAPI 路由,是公开 API 的权威来源。
- `backend/app/services/`:业务服务层。`course_build_service.py` 同时包含
  `CourseBuildService` 与 `CourseReleaseService`;`course_release_service`
  的 `rollback_to_release` 是回滚入口。
- `backend/app/models/`:SQLModel 数据模型。权限相关模型集中在
  `access_control_model.py`、`agent_governance_model.py`、`course_lifecycle_model.py`。
- `backend/app/domain/`:领域逻辑(education_graph、knowledge_bundle、learning、
  safety、student_memory)。
- `backend/app/core/`:`config.py`、`feature_flags.py`、`time_utils.py`(必须使用
  时区感知时间,不得再用 `utcnow_naive()`)、`security.py`、`signature_middleware.py`。
- `backend/app/platform/`:平台层,见 2.2。
- `backend/alembic/`:数据库迁移。结构变更由部署流程显式
  `alembic upgrade head` 执行,不在应用启动时隐式 `create_all`。
- `backend/tests/`:测试套件,按 `canary/`、`education_graph/`、`evidence/`、
  `feature_flags/`、`learning/`、`product1/contracts/`、`safety/`、`shadow/`、
  `student_memory/` 等子目录组织。

### 2.2 智能体平台层(`backend/app/platform/agents/`)

三 Agent 已物理分离,各自拥有独立的 state/workflow/profile/composition:

| 子目录 | 职责 |
|---|---|
| `edu/` | TeachingAgent:教学问答与教学动作。工作流固定为 ScopeValidator → StudentState → Cognition → Optional Tools → TeacherPolicy → Response。 |
| `prep/` | Prep Agent:备课 PatchProposal 生成。`evidence_refs` 校验是硬门;只能修改 draft 内非锁定节点的标题与脚本内容/风格,不能增删移节点、不能改已发布/锁定内容。详见 `prep/DESIGN.md`。 |
| `coding/` | CodingEduAgent:代码诊断与教学。连接真实 Judge0 沙箱。 |
| `contracts/` | Port 定义(cognition/experiment/governance/llm/research/retrieval/sandbox/teaching/tools)。Agent 间不共享可变状态,只通过 Port 协作。 |
| `providers/` | Provider 实现,包装现有 Service。`container.py` 是装配入口。 |
| `runtime/` | 共享 Runtime(base/checkpoint/concurrency/dispatcher/events/registry/teaching_runtime/validation)。Runtime 按 course/student 创建,不全局共享。 |
| `shared/` | 跨 Agent 共享工具(state/tracing/workflow_utils)。 |
| `tools/` | Tool 实现。每个 Tool 自行做 course/role 校验,不依赖调用方传参保证。 |
| `policies/` | 教学动作策略(teaching_action)。 |
| `prompts/`、`workflows/` | 教学 prompt 与工作流编排。 |
| `bootstrap.py` | 应用启动时注入真实 LLM、Judge0、各 session-scoped Port;fake provider 不得再进入 bootstrap。 |

历史兼容层(顶层 `composition.py`、`gateway.py`、`platform.py`、`registry.py`、
`state.py` 等)是迁移期保留的转发声明,只做最小再导出,不要在其中新增逻辑。
需要修改时改对应子模块。

### 2.3 前端布局

- `frontend/src/api/`:API 客户端,路径必须与后端注册路由一一对应。
  权限判定必须消费 `course_access.js` 提供的能力视图模型,不得从全局
  `User.role` 或 UI 状态推断"当前课程教师"。
- `frontend/src/router/index.js`:路由与权限挂载点。
- `frontend/src/utils/request.js`:请求拦截与统一错误处理。

**前端设计权威**:`design.md`(项目前端设计指南 v0.4)是前端视觉令牌、
布局与滚动模型、页面过渡动画、组件外观、助教智能体面板、建设页面
stageActions 机制、按钮规范、已删除组件清单的**唯一权威文档**。

Agent 在以下场景**必须**先读 `design.md` 再动手:

- 新增页面、组件、布局容器或路由过渡;
- 修改 `frontend/src/app/styles/tokens.css` 或
  `frontend/src/app/styles/base.css`;
- 调整 AppShell / CourseLayout / BuildLayout / 助教智能体面板结构;
- 新增按钮(必须使用 `SfxButton.vue`,禁止原生 `<button>`);
- 处理滚动溢出、过渡抖动、菜单消失等已知反模式(见 `design.md` §5、§6);
- 恢复任何已删除组件前(见 `design.md` §11 清单,禁止恢复 LearnContextBar、
  `--contextbar-height`、自定义全屏模式、"备课 Agent" 命名)。

`design.md` 与 `frontend/docs/` 历史文档冲突时以 `design.md` 为准。
代码实际行为与 `design.md` 不一致时,以代码为准并同步更新 `design.md`,
而不是改代码迁就文档。

### 2.4 文档布局

- `docs/phase1/`:本阶段实施文档。涉及权限架构、统一课程建设九步、路由契约、
  功能现状审计、代码风险清单、测试环境设计等。修改代码后若涉及架构决定,
  对应文档需同步更新。
- `docs/refactor/`:历史重构报告(R1/R2 系列),归档参考,不作为现状证据。
- `docs/phase1/功能现状审计表.md`:发现历史文档描述不准确时的记录入口。

---

## 3. 默认授权范围

除本文件第 4 节硬边界明确禁止的事项外,Agent 可自主完成以下工作,无需逐模块
等待批准:

1. 阅读、审计、修复、重构和替换现有前端、后端、配置、测试、文档及构建脚本。
2. 新增、修改或删除本地 Demo 所需的代码路径、服务、API、View Model、页面、
   组件、任务、模型和部署配置;允许修正旧字段和旧模型的错误语义,但必须提供
   迁移路径并更新实际消费者。
3. 在 `platform/agents/` 三 Agent 与共享层内推进能力打磨:工具、Port、Provider、
   Workflow、Policy、Prompt;新增或重组模块、目录、类、协议和依赖。
4. 删除已确认未使用的死代码、过时端点、重复实现和占位模块,并同步修改调用方、
   路由、迁移和测试;删除前在提交说明中写明原因。
5. 新增单元、集成、端到端、迁移、回归、性能和人工冒烟测试,以及 fixture、fake、
   stub、mock、临时数据库和本地样例数据。
6. 在 `docs/phase1/` 或直接相关的模块文档中记录架构决定、外部依赖、风险、
   已知限制、部署和回滚方式。
7. 使用课程能力开关、Demo 配置或明确的发布状态,逐步把新能力接入本地体验;
   新能力不必永久保持 Shadow 状态。

---

## 4. 硬边界

### 4.1 安全与数据边界

1. 不得把学生代码放入主应用进程执行;代码执行必须经过独立沙箱服务(Judge0)。
2. 不得把真实学生聊天、Memory、身份数据或生产数据库复制到 fixture、日志、
   文档或仓库;Demo 使用合成或经授权且假名化的数据。
3. 不得读取、输出或提交真实 API Key、Token、密码或其他密钥。Xfyun 凭据不得
   进入前端、日志或测试。
4. 不得在自动化测试中调用真实付费 LLM、TTS、PPT、数字人或其他付费服务。
5. 不得让外网资料、LLM 输出或交互频次无证据地直接成为正式掌握度、课程事实或
   已发布图谱关系;WebResearch 结果必须标记为"补充参考",并作为可审计候选或
   独立证据处理,不得直接写为课程事实、掌握结论或图谱边。
6. 不得绕过 Course Access v1 的课程、学生、成员和能力校验。授权决策必须经
   `backend/app/services/course_access_service.py` 与 `CourseMembership`、
   `CourseCapability`、`PlatformPermissionAssignment` 解析;
   `User.role`、`Course.teacher_id`、`StudentEnrollment` 仅作为遗留迁移输入,
   不得作为兜底授权来源。
7. 媒体资产必须通过 `object_key` 访问,绝对路径不得写入业务数据;媒体发布
   不可变,修改脚本或形象必须新建版本,旧版本标记为 stale 而非静默指向新文件。
8. 数字人形象必须有授权与撤销记录;教师可撤销授权,后续课程发布不得再选被
   撤销的形象;被禁用的形象档案必须阻止新的预处理任务。

### 4.2 兼容、迁移与重构

1. 允许改变公开 API、请求/响应结构、数据库结构、启动配置和用户可见行为,
   前提是同步更新真实调用方、迁移脚本和必要文档;对仍在使用的接口保留兼容层
   或提供明确版本化迁移方案。
2. 允许重构或替换核心模块;重构前应识别实际路由、调用链和数据模型,重构后必须
   覆盖主流程与失败/降级路径。
3. 不得静默删除仍有消费者的数据、接口或功能。删除前需迁移消费者,或明确标记为
   废弃并给出替代入口。
4. 数据库迁移必须可重入,关键迁移需带 batch 标识和回滚脚本;不得用当前
   `SQLModel.metadata` 替代真实升级前 schema 做历史迁移。
5. 不得为"看起来完成"创建未接线的空目录、空类、伪实现或虚构成功状态。fake
   provider 只能存在于 `providers/fakes.py` 与 `tools/fakes.py` 中用于测试,
   不得进入 bootstrap 与正式运行路径。

### 4.3 结果诚实性与测试边界

1. 禁止调用真实付费 LLM / TTS / PPT / 数字人服务执行自动化测试。
2. 禁止读取生产 API Key、Token 或其他密钥;禁止使用生产数据库运行测试。
3. 可以替换已被替代功能对应的旧测试,但必须在新功能侧补等价验证,并在提交说明
   或代码注释中写明原因。**不得为通过测试而削弱断言、跳过断言或伪造断言**。
4. 不得把未运行、失败或仅 Mock 验证的结果表述为"真实环境全绿"、"真实效果"或
   "已上线能力"。
5. 不得伪造功能状态、准确率、性能数据和测试结果。Agent 审计
   (`agent_tool_invocations`)与正式 `LearningEvidence` 严格分离,符合数据
   最小化策略;只有服务端评分结果(Quiz/Judge0)或 CodingAgent 可写入
   `LearningEvidenceRecord`,学生提交的分数必须拒绝。
6. 高风险教学动作必须经教师确认;经教师批准后由 handler 执行并标记
   `dispatched: true`,失败时保留原 `error_code`,不得伪装成功。

---

## 5. Agent 子系统工作规则

### 5.1 通用

1. Runtime 按 course/student 创建,不全局共享;Agent 上下文不得持久化原始
   问题、完整答案或完整 LLM trace,只能保留会话摘要。
2. 每个 Tool 在执行前自做 course/role 校验,不依赖调用方传参保证;被禁用的
   Tool 跳过并写审计日志。
3. Tool 治理实现 per-tool policy check,在每个 tool node 之前执行。
4. `AgentPolicyVersion` 使用乐观锁(`expected_version`),每个版本存完整
   `policy_snapshot`。
5. `GraphSnapshot` 一旦发布不可变,支持版本对比与回滚。

### 5.2 TeachingAgent(edu/)

- 工作流固定:`ScopeValidator → StudentState → Cognition → Optional Tools →
  TeacherPolicy → Response`。
- 初始连接的 Tool 仅限:`StudentStateTool`、`CognitionTool`、课程检索、图谱
  读取、题库。BKT/HMM/LSTM/GraphRAG 不得在初始版本中实现或上线,保持当前
  可解释证据规则方式。
- 低置信度推荐只能进入"需要更多证据"状态,不得直接断言薄弱。
- JSAV 可视化只支持白名单算法。
- WebResearch 默认禁用;启用时必须 fail-closed:若安全阀 `create_proposal`
  失败,标记 `SAFETY_VALVE_UNAVAILABLE` 并跳过高风险 web research。

### 5.3 Prep Agent(prep/)

- 不需要 LLM-facing Tools;所有依赖均为确定性调用的 Dependencies。
- 工作范围由前端选定的 `outline_node_id`、draft 状态与锁定节点排除共同决定。
- 只能修改 draft 内非锁定节点的标题与脚本内容/风格;不能增删移节点、不能改
  已发布/锁定内容。
- `evidence_refs` 校验是硬门,通过后才能进入 PatchProposal 流程;PatchProposal
  使用正式 Proposal 状态机,不再使用 `approved: bool`。
- LLM 必须返回符合 `AgentPlan` schema 的 JSON;返回不符合时按结构化重试策略
  处理,并记录原始 LLM 响应便于排查。

### 5.4 CodingEduAgent(coding/)

- 必须连接真实 Judge0 沙箱(由 bootstrap 注入 `Judge0SandboxPort` 单例,
  EDU 与 Coding 共享);沙箱不可用时返回 `SANDBOX_UNAVAILABLE` 而非 `ACCEPTED`,
  不假造执行。
- 健康检查在构造时执行并缓存结果,主流程在 Judge0 不可用时不中断(降级语义)。

### 5.5 Prep 双链路统一

- Initial 与 Incremental 共享 Port:`StructuredLLMPort`、`AgentRunStorePort`、
  `AgentRunEventPort`、`PrepPlanValidatorPort`。
- Initial 专用:`InitialCoursePrepPort`;Incremental 专用:`IncrementalPrepPort`、
  `PatchProposalPort`。
- Provider 实现包装现有 Service:`InitialCoursePrepProvider` 包装
  `InitialCoursePrepService`,`IncrementalPrepProvider` 包装
  `CoursePrepAgentService`。
- `PrepLLMAdapter` 作为 LLM 适配层,把 `StructuredLLMPort` 转换为 Service 所需
  接口;修改 Service 构造函数以注入该适配器,而不是绕过 Service 直接持久化。
- `StageEmitter` 作为事件适配层,处理阶段事件的持久化与 SSE 广播;Graph 层
  不得绕过 Service 直接处理持久化逻辑。

---

## 6. 测试与验证策略

本地 Demo 默认优先实现、集成与真实手工体验。测试、构建、全量回归和覆盖率是
**推荐工具**,不是继续开发、提交或切换功能的硬门槛。Agent 可以在尚未补齐测试的
情况下提交可运行的阶段性实现,并在交接时如实说明已验证与未验证的部分。

- 能快速运行相关测试时优先运行;不能运行或成本过高时不阻塞开发。
- 前后端改动可以先用真实页面、接口调用、日志和样例数据验证,再集中补回归测试。
- 数据库、权限、沙箱或外部服务改动仍须保留可理解的失败语义、迁移路径和回退方式,
  但不要求本地每次都完成全量迁移/回归演练。
- 前端 API 契约必须用测试覆盖前端 client 到后端 route 的映射(包括 G5 存储管理
  路由的 `{object_key:path}` 映射);契约不匹配属于关键功能失败,不能仅靠后端
  测试通过就认为已上线。
- 全量测试套件必须能从仓库根目录执行,Alembic 路径配置正确;验收测试覆盖
  权限矩阵、跨课程隔离、迁移回滚、任务失败、依赖降级、API 契约六大包。

---

## 7. 文档与历史材料处理

### 7.1 讨论后的方案变更必须同步

与开发者讨论并确认的产品方案、技术路线、组件选型、发布门槛、真实阻塞或完成度
变化，必须在同一开发变更中落实到：

1. 根目录 `README.md` 的当前方案与状态；
2. 对应的 `docs/phase1/` 现行实施/审计/契约文档；
3. `docs/DOCUMENTATION_INDEX.md` 的入口与文档状态；
4. 必要时同步实际调用方、测试和迁移说明。

文档更新必须写明日期、变化原因和代码证据，不能只改宣传性描述。被替代的方案、
旧 API、旧 Provider、旧播放器或旧数字人路线必须在原文档顶部标记“已废弃/仅历史
追溯”，并链接到现行文档；不得继续将其作为实现依据、验收依据或“已完成”证明。
删除历史文档前必须确认没有仍在使用的消费者；否则保留文件但明确废弃语义。

历史材料用于审计,不作为真实实现证据。以下内容不得直接作为功能已完成的依据:
README、ARCHITECTURE、旧比赛申报材料、功能规划、V3.1 重构文档、产品宣传文案、
未验证的测试数据、`docs/refactor/` 下的历史重构报告。

设计文档与实际代码不一致时,必须以以下证据为准:

1. 实际注册的路由;
2. 实际执行的函数和调用链;
3. 数据库模型;
4. 前端真实调用;
5. 可运行行为;
6. 自动化测试;
7. 命令输出。

本阶段原则上不得直接修改历史比赛材料和旧规划文档。发现历史文档描述不准确时,
记录到 `docs/phase1/功能现状审计表.md`。

业务领域硬约束(如 Course Access v1 的完整迁移与回滚门、R2 检索白名单与降级、
Excel 题库导入幂等、对象存储可恢复迁移与 SHA 校验、AvatarPreparationJob 幂等键、
媒体 URL 按课程权限签名等)的权威来源是代码与 `docs/phase1/` 下对应文档
(尤其是 `权限架构重构Goal.md`、`统一课程建设与解析基线.md`、`路由契约基线.md`、
`阶段8_媒体TTS数字人PPT_实施规划.md`)。修改这些领域前必须先读对应文档与代码。

---

## 8. 提交与变更纪律

1. 不得执行 `git push --force`、`git reset --hard`、`git checkout .`、
   `git clean -f`、`git branch -D` 等破坏性操作,除非用户明确要求。
2. 不得修改 `.git/config`;不得擅自 `commit`、`push`、`merge`、`rebase`、
   创建 PR,除非用户明确授权。
3. 暂存文件时按文件名逐个添加,不得用 `git add -A` 或 `git add .`,避免误纳入
   `.env`、凭据或大文件。
4. 不得修改 `refactor/codemind-v3` 与 M7 维护基线;不得 restore/pop/drop/modify
   任何现有 stash;不得触碰无关的 untracked 文件。
5. 安装、升级、删除依赖前必须经用户明确批准。

---

## 9. 冲突优先级

1. 本文件 > 历史文档与 README。
2. 本文件 > `CLAUDE.md`(`CLAUDE.md` 仅在多 Agent 并行任务卡片模式启用时补充,
   当前阶段不启用)。
3. 代码实际行为 > 任何文档描述;不一致时记录到 `docs/phase1/功能现状审计表.md`
   而不是改代码迁就文档。
4. `docs/phase1/` 中的业务硬约束文档 > 历史规划文档。
