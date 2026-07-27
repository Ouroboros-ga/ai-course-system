# Page Design 后端全量实施路线图

> 2026-07-27 适用性更新：本路线图仍用于阶段性核对；其中课程材料解析、课程结构、讲稿和 PPT 映射的现行目标以 [统一课程建设与解析基线](统一课程建设与解析基线.md) 为准。旧课程不再安排自动历史迁移，统一新文件上传路径完成后通过重新上传创建新课程。

> 目标：将后端补全到 `page-design.md` 所描述的课程建设、学习、知识空间、实验、资源、任务和媒体能力。
> 本路线图不把“有模型/有路由”当作完成；每一阶段必须达到数据模型、权限、API、任务、失败语义、测试和前端接线都闭环。

## 1. 总体原则

1. 新页面只依赖 `PageDesign前端API契约规划.md` 的 facade/领域契约；历史端点逐步适配而非继续扩散。
2. Course Access v1 是唯一课程授权来源。每个 `course_id` 请求都必须先做课程范围校验。
3. 长任务不在 HTTP 请求中执行：OCR、解析、图谱构建、导入、媒体生成、实验运行、外部同步都进入统一任务中心。
4. LLM、OCR、WebResearch、Agent 输出只产生候选或带来源的辅助结果；它们不能绕过教师审核、课程隔离和正式认知证据契约。
5. 学生代码只能经独立 Judge0 沙箱；主应用不执行代码、不持有沙箱容器权限。
6. 每个数据库变化均需要版本化迁移、预检、回滚说明和临时数据库测试；`create_all()` 只可作为新 Demo 数据库的便利，不是结构演进方案。

## 2. 推荐实施顺序

```text
0 契约与迁移底座
  → 1 工作首页与课程列表读模型
  → 2 成员、设置、加入与课程生命周期
  → 3 任务中心与课程建设工作流
  → 4 课程材料解析、Evidence 与图谱治理
  → 5 题库、练习推荐、正式学习证据
  → 6 课程实验、Judge0 与 CodingAgent
  → 7 资源库与平台实验室
  → 8 媒体、TTS、数字人和时间轴发布
  → 9 TeachingAgent 全工具化与教师安全阀
  → 10 稳定化、数据补建、演示/部署验收
```

前端可从第 0 阶段起，按 API 规划先完成路由、骨架、状态页与 Mock；后端按阶段替换 Mock 数据源。

## 3. 阶段 0：契约、迁移与基础运行底座

### 要做什么

- 建立统一的版本化迁移机制（建议 Alembic 或等价的受版本控制迁移工具）。
- 保留现有 Course Access 和 Agent Log 的专项 preflight/rollback，并接入统一迁移记录。
- 建立 OpenAPI 路径快照、前端 API 契约测试、统一错误码与分页/异步任务协议。
- 建立 `Task` 基础领域模型与后台 worker 适配接口，先支持本地进程 worker，未来可替换 Redis/Celery/RQ。

### 数据库

```text
schema_migration_records
tasks
task_events
task_resource_links
idempotency_keys
```

### 验收

- 空数据库升级、已有 SQLite Demo 数据库升级、重复运行迁移均可验证。
- 每次迁移可输出预检报告、备份建议和明确回滚边界。
- 任务创建、查询、失败、重试、取消、权限拒绝均有 API/集成测试。

## 4. 阶段 1：工作首页、课程列表与聚合读模型

### 要做什么

- 实现 `GET /facade/home`、课程列表 facade、教师/学生概览 facade。
- 将现有 `/document/my-courses`、dashboard、Course Access、课程状态整合为稳定 View Model。
- 增加课程大厅的发现范围和可见性规则，禁止泄露草稿课程。

### 数据库

优先复用 `Course`、`CourseMembership`、`CourseCapability`、`StudentEnrollment`；如需聚合缓存，增加
可失效的 `course_read_model_snapshots`，不要复制授权事实。

### 验收

- 同一个用户在不同课程角色下得到正确的 learning/building/hall 列表。
- 跨课程、关闭课程、移除成员、能力禁用后结果立即失效或可解释地更新。
- 前端首页和我的课程页面不再通过多个历史接口拼装角色。

## 5. 阶段 2：成员、课程设置、加入申请与生命周期

### 要做什么

- 在已有邀请码加入基础上实现申请加入、审核、过期/撤销、审计和通知。
- 实现课程分组、成员批量管理、泛雅同步任务状态。
- 实现课程设置聚合模型：基本信息、可见性、能力开关、Agent 策略、安全策略、沙箱策略、平台集成。

### 数据库

```text
course_join_requests
course_groups
course_group_members
course_setting_versions
course_audit_events
integration_sync_runs
```

### 验收

- 成员的加入、退出、移除、重新加入全部经 Course Access 生命周期 helper。
- 申请审批幂等，不可用全局 `User.role` 越权。
- 设置更新使用版本冲突控制；课程关闭、重新开放、邀请码变更具有审计记录。

## 6. 阶段 3：统一任务中心与教师课程建设工作流

### 要做什么

- 实现 `/course-build/{course_id}` 聚合和七步建设状态：资料、结构、讲稿、页映射、媒体、校验、发布记录。
- 把上传、OCR、文档解析、映射、生成、校验改为任务中心驱动。
- 建立课程 release：发布的是一组一致的结构、讲稿、映射、Evidence、图谱和媒体版本，不是散落字段。

### 数据库

```text
course_build_drafts
course_build_steps
source_materials
source_material_versions
course_quality_gate_runs
course_releases
course_release_artifacts
```

### 验收

- 教师能看到每步输入、产物、失败原因、重试和下游影响。
- 教师锁定的映射/讲稿不被 AI 重跑覆盖。
- 发布前质量门禁可阻断，发布后学生只读不可变 release；回滚产生新激活版本而非破坏历史。

## 7. 阶段 4：课程材料解析、Evidence、Citation 与图谱

### 要做什么

- 为“课程材料版本”实现 OCR/DocumentIR/Evidence/图谱候选的异步解析流水线。
- 实现旧课程的受控批量补建：按课程与材料版本执行，绝不能按每个学生重复解析。
- 从 V2 Shadow 提炼稳定的 student-readable Citation facade；支持页码、文本段、bbox/页面图、版本、stale/orphaned。
- 将教师审核、GraphSnapshot、差异、回滚与 release 关联。

### 数据库

```text
document_parse_runs
document_blocks
evidence_spans
evidence_citations
evidence_render_assets
graph_candidate_batches
graph_relation_reviews
graph_release_links
```

### 验收

- 任一图谱关系可追溯到 Evidence 或教师确认。
- 课程 A 的 Evidence、节点和 Citation 永不出现在课程 B。
- 重解析/删除后历史引用返回 stale/orphaned，不静默指向新内容。
- 图谱不可用时正常问答降级；不会对学生返回“系统 503 拒绝回答”。

## 8. 阶段 5：题库、个性化练习与正式学习证据

### 要做什么

- 完成 Excel 导入的可审计题源、教师映射、发布和版本流。
- 实现“题库优先检索 → 无匹配题则约束生成草稿 → 教师审核/发布”的编排服务。
- 实现六维认知驱动的诊断题、补弱题、提示撤除题和解释后核验题推荐。
- 把判分后的 Quiz/实验完成等写入正式 `LearningEvent / LearningEvidence` 契约；交互语义和 Agent 审计继续独立。

### 数据库

```text
question_import_runs
question_generation_drafts
question_recommendation_runs
question_recommendation_items
assessment_policies
learning_evidence_links
```

### 验收

- 每次推荐携带 `policy_version, reason_codes, evidence_refs, confidence`。
- 数据不足返回 `unknown / evidence_needed`，不把提问次数或观看时长当掌握度。
- 未归属、未映射、未发布、教师拒绝的题目不能被学生检索或推荐。

## 9. 阶段 6：课程实验、Judge0 与 CodingAgent

### 要做什么

- 基于现有 Judge0 后端代理实现实验定义、版本、测试用例、尝试、运行和提交记录。
- 将语言白名单、资源限制、网络关闭和课程能力校验固化在服务端。
- 实现结果分类：编译错误、运行错误、超时、内存超限、测试失败、通过；每类给出可解释但不泄露隐藏测试的反馈。
- 以真实 `SandboxPort` 替换 TeachingAgent 当前 `UnavailableSandboxPort`，并让 CodingAgent 只能请求受控执行和分层提示。

### 数据库

```text
experiment_definitions
experiment_versions
experiment_test_cases
experiment_attempts
experiment_runs
experiment_run_artifacts
coding_hint_records
```

### 验收

- 前端不直接访问 Judge0；主应用不执行学生代码。
- 学生只能看自己的尝试，教师只能管理所属课程实验。
- 最终评分型结果才产生 LearningEvidence；单次运行日志不直接修改认知状态。
- Judge0 不可用时课程学习页可以降级，且保留明确恢复提示。

## 10. 阶段 7：资源库、平台实验室与任务中心页面

### 要做什么

- 完成通用资源库：文件版本、标签、课程引用、回收站、下游影响与权限。
- 完成平台实验大厅、课程任务、我的实验、实验记录和实验工作区的读模型。
- 将第 3--6 阶段的所有异步任务接入任务中心。

### 数据库

```text
resource_items
resource_versions
resource_tags
resource_references
resource_acl_entries
recycle_bin_entries
lab_catalog_entries
```

### 验收

- 删除资源先展示受影响课程/发布版本，软删除后仍可恢复。
- 任务中心可定位到源课程、源资源、失败原因和恢复动作。
- 平台实验与课程实验共享沙箱能力，但课程实验可回写课程证据和 return anchor。

## 11. 阶段 8：媒体、TTS、数字人与 PPT 时间轴

### 要做什么

- 把现有 `MediaAsset` 与 `MediaTimelineCue` 纳入 generation job/release 模型。
- 接入锁定依赖的独立 TTS 与 CPU 数字人服务；首版优先预生成，不塞进实时问答。
- 实现视频、PPT 页、字幕、讲稿的统一全局时间轴，且支持版本哈希和回滚。
- 本地存储继续使用 `object_key` 抽象；增加 OSS adapter、迁移工具、访问策略和垃圾回收策略。

### 数据库

```text
media_generation_jobs
media_generation_attempts
media_releases
media_release_cues
media_provider_runs
```

### 验收

- 外部完整视频和预生成数字人视频均可按 Cue 驱动 PPT 与字幕。
- 模型/服务不可用返回可解释任务失败，不伪造视频已生成。
- 本地与 OSS 存储对 API 消费者保持相同 object_key/版本契约。

## 12. 阶段 9：TeachingAgent、工具治理与教师安全阀

### 要做什么

- 固定 Agent 工作流：ScopeValidator → StudentState → Cognition → 可选工具 → TeacherPolicy → Response。
- 将 Graph、课程检索、题库、实验、可视化、LearningEvent、WebResearch 注册为具备自身课程/角色校验的工具。
- 实现 Agent 动作提案、教师确认、拒绝、锁定、重跑和审计。
- 保持当前数据最小化策略：会话摘要可持续，上下文不得保存原始提问、完整回答或完整 LLM trace。

### 数据库

```text
agent_tool_policies
agent_action_proposals
agent_action_decisions
agent_tool_invocations
agent_policy_versions
```

### 验收

- Prompt 不能绕过工具权限、课程隔离或教师禁用策略。
- 缺少图谱/R2 时可降级普通课程问答；缺少沙箱时 CodingAction 显示不可用而非虚构执行。
- Agent 审计、会话摘要与正式 LearningEvidence 严格分离。

## 13. 阶段 10：稳定化、历史数据补建与上线验收

### 要做什么

- 建立历史课程补建清单：材料版本 → 解析任务 → Evidence → 图谱候选 → 教师审核 → release。
- 实施负载、超时、资源、任务重试、对象存储迁移、数据库备份恢复和可观测性测试。
- 运行完整权限矩阵、跨课程隔离、迁移回滚、任务失败、外部依赖降级、前端构建和端到端验收。

### 必须完成的验收包

1. 课程 A/B、学生 A/B、教师/管理员/观察者的授权矩阵。
2. 课程材料重解析、发布、回滚、引用 stale 的全链路测试。
3. Quiz、代码实验、认知推荐的证据来源与“低置信度不武断”测试。
4. Judge0 超时、内存限制、编译失败、服务不可达和恢复演练。
5. Agent 的 Graph/R2/Sandbox/WebResearch 可用与不可用双路径测试。
6. SQLite Demo 升级演练；未来 PostgreSQL/OSS 的迁移演练。

## 14. 每阶段交付门槛

一个阶段只有同时满足以下条件才算完成：

- 数据模型与版本迁移已提交；
- 路由已注册并出现在 OpenAPI；
- 每个课程接口使用 Course Access v1；
- 至少有成功、权限拒绝、跨课程拒绝、依赖不可用四类测试；
- 前端 API client、类型、错误映射与页面空/错/加载状态已接线；
- 异步操作已进入任务中心并可看见失败原因；
- 文档明确外部依赖、数据边界、回滚及已知限制。

这条路线允许前端和后端并行：前端以冻结的 planned contract 实现页面，后端逐阶段将接口变为 available，
每次替换都通过契约测试，而不是依赖人工口头同步。
