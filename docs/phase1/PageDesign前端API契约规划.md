# Page Design 前端 API 契约规划

> 状态：规划稿 v1。面向 `page-design.md` 的新前端页面，不把历史页面、未注册组件或
> Shadow 输出误写成正式能力。
>
> 本文的目的：前端可以据此完成页面、路由、状态机、类型和 Mock；后端按同一契约逐域实现。
> **`planned` 接口目前不存在，前端不得把它当作可用服务。**

## 1. 事实基线与使用方式

现有后端已经注册了课程权限、题库、认知、图谱、沙箱、可视化、媒体和 TeachingAgent 等路由；
但新 `/app` 前端尚未覆盖全部页面。因此采用下面的边界：

- `GET /api/v1/facade/**`：面向页面的聚合只读 View Model。已有
  `course/{course_id}/overview`、`citation/{node_id}`、`quiz`，后续继续扩展。
- `GET/POST/PUT/DELETE /api/v1/<domain>/**`：领域命令与明细读接口，例如
  `question-bank`、`graph`、`sandbox`、`course-access`。
- 旧的 `document.py`、`player.py` 等路径在过渡期保留；新页面优先消费 facade 或本文规定的
  领域接口，不能重新耦合到大而杂的历史端点。
- 所有课程范围接口先建立 `CourseAccessContext`，再判断权限和 capability；前端不可依据
  `User.role` 猜测当前课程里的教师身份。

### 1.1 状态标记

学习页的节点轨道必须以 `learning-context.items` 为唯一首屏聚合来源，同时把学习曝光与认知掌握分开显示。认知详情通过现有 `/cognitive/course/{course_id}/state?node_id={cognition.node_id}` 按需读取；跳转知识图谱时使用 `cognition.node_key`，不能把数据库整数 ID 当作公开图谱节点身份。

| 标记 | 含义 | 前端处理 |
|---|---|---|
| `available` | 已注册、真实可调用、具有稳定语义 | 可直接接入并写契约测试 |
| `adapter_needed` | 后端能力存在，但需要 facade/字段适配或仍为实验态 | 可做页面，必须显示能力/降级状态 |
| `planned` | 这是冻结的未来契约，当前未实现 | 可用 Mock 开发，不得请求真实后端 |
| `shadow_only` | 研究或影子能力，不能当学生正式事实 | 仅在 capability 明确开启时显示预览 |

### 1.2 统一协议

除明确标记为历史扁平响应的兼容接口外，新接口必须返回：

```ts
type ApiResponse<T> = {
  code: 200 | 201 | 202
  message: string
  data: T
  request_id?: string
}

type ApiError = {
  error_code: string
  message: string
  request_id?: string
  details?: Record<string, unknown>
}
```

- 分页统一为 `items / next_cursor / total?`，不要混用 page、offset、items。
- 所有异步创建接口返回 `202` 与 `task_id`；前端随后读取 `/api/v1/tasks/{task_id}` 或订阅任务流。
- 可编辑资源必须带 `version` 或 `updated_at`；写入时使用 `If-Match` 或 `expected_version`，冲突返回
  `409 VERSION_CONFLICT`，不可静默覆盖。
- 公开 ID 使用 `course_id`、`node_id`、`question_id`、`snapshot_id`、`task_id` 等稳定标识；不向前端暴露
  内部临时文件路径。
- 所有结果包含明确能力状态：`available | experimental | pending | unavailable | degraded`。

### 1.3 统一错误语义

| HTTP | `error_code` | 前端行为 |
|---:|---|---|
| 401 | `AUTH_REQUIRED` | 进入登录/刷新会话 |
| 403 | `COURSE_ACCESS_DENIED` / `CAPABILITY_DISABLED` | 显示无权或课程未启用，不展示部分数据 |
| 404 | `COURSE_NOT_FOUND` / `RESOURCE_NOT_FOUND` | 失效页与返回入口 |
| 409 | `VERSION_CONFLICT` / `STATE_CONFLICT` | 保留草稿，提示刷新/比较 |
| 422 | `VALIDATION_FAILED` | 字段级错误 |
| 429 | `BUDGET_EXCEEDED` | 显示稍后重试和预算说明 |
| 503 | `DEPENDENCY_UNAVAILABLE` | 降级，不把服务不可用伪装为空数据 |

学习问答的图谱/R2 未就绪不是致命错误：TeachingAgent 可以返回
`status=fallback_required`、`fallback_reason=COURSE_KNOWLEDGE_GRAPH_PENDING`；前端使用 V1 课程问答并明确提示。

## 2. 已有接口：前端可先接入

以下是当前真实注册且最适合作为页面第一版数据源的接口。路径均省略共同前缀 `/api/v1`。

| 页面/能力 | 接口 | 状态 | 备注 |
|---|---|---|---|
| 课程权限与能力 | `GET /course-access/courses/{course_id}/access`、`/capabilities` | `available` | 页面初始加载的权威权限来源 |
| 成员与邀请码 | `GET/PUT /course-access/courses/{course_id}/members`；`POST/DELETE /invite-code`；`POST /courses/join-by-code` | `available` | 已可支持邀请码加入，缺“申请审核”状态机 |
| 课程概览 | `GET /facade/course/{course_id}/overview` | `available` | 新页面优先使用 |
| 我的课程/课程生命周期 | `/document/my-courses`、`/document/course/{id}/enroll|unenroll|publish|unpublish` | `adapter_needed` | 历史接口，后续由课程列表 facade 统一 |
| 学习播放器 | `GET /player/init/{course_id}`、进度保存接口 | `adapter_needed` | 历史扁平响应，前端已有适配层 |
| 笔记 | `GET/POST/GET:id/PUT/DELETE /notes` | `available` | 新 Canvas 可直接接入 |
| 题库与答题 | `/facade/course/{id}/quiz`；`/question-bank/course/{id}/...` | `available` | 题库、版本、作答、判分已存在 |
| 题源映射 | `/question-mapping/course/{id}/...` | `available` | 教师工作台可直接接明细接口 |
| 认知与推荐 | `/cognitive/course/{id}/state|compute|recommend|recommendations|evidence` | `available` | 低置信度必须显示“需要更多证据” |
| 图谱生产化 | `/graph/course/{id}/evidence|reviews|snapshot|publish|snapshots|rollback|candidates|...` | `available` | 缺课程材料批量解析任务 |
| 算法可视化 | `/visualization/algorithms`、`/course/{id}/plan|plans|{plan_id}|{plan_id}/publish` | `available` | 计划必须通过白名单验证 |
| 代码沙箱 | `GET /sandbox/health|languages`、`POST /sandbox/course/{id}/execute` | `available` | 当前是运行能力，不是完整实验业务 |
| TeachingAgent | `POST /teaching-agent/respond` | `adapter_needed` | 图谱不可用时返回结构化降级；当前 Agent 未接真实 SandboxPort |
| 安全策略 | `/safety/course/{id}/safety-policy|sandbox-policy|audit` | `available` | 课程设置页可先接入 |
| WebResearch | `/web-research/course/{id}/config|search|references` | `adapter_needed` | 默认关闭；仅补充资料，不能成为课程事实 |
| 媒体时间轴 | `/media/course/{id}/timeline`、`/media/course/{id}/cues`、`/media/assets` | `adapter_needed` | 资产/时间轴已有，生成工作流未完成 |
| Evidence V2 | `/evidence-v2/documents/{id}/...` | `shadow_only` | 不能作为学生正式引用链 |

## 3. 页面 API 契约

本节是前端应遵循的页面契约。每组都给出页面需要的接口、权限和当前实现状态。

### 3.1 `/app`：登录后首页

| 接口 | 状态 | 说明 |
|---|---|---|
| `GET /facade/home` | `planned` | 聚合“继续学习、我建设的课程、待处理审核、系统任务、最近活动”；避免首页并发拼接十余个领域接口。 |
| `GET /facade/home?mode=student\|teacher` | `planned` | 由有效课程角色与待办决定视图，不使用全局角色猜测。 |

`HomeViewModel`：

```ts
type HomeViewModel = {
  active_mode: 'student' | 'teacher' | 'mixed'
  continue_learning: CourseContinueCard[]
  building_courses: CourseBuildCard[]
  pending_reviews: PendingReviewCard[]
  system_tasks: TaskSummary[]
  capabilities: Record<string, 'available' | 'experimental' | 'unavailable'>
}
```

### 3.2 `/app/courses/*`：我的课程、课程大厅、加入课程

| 接口 | 状态 | 权限/说明 |
|---|---|---|
| `GET /facade/courses?view=learning&cursor=` | `planned` | 当前用户可学习课程、进度和继续学习锚点。后端可先适配 `/document/my-courses`。 |
| `GET /facade/courses?view=building&cursor=` | `planned` | 有 `course.edit` 或建设职责的课程。 |
| `GET /facade/courses?view=hall&query=&subject=&status=` | `planned` | 仅返回允许发现的已发布课程；不可泄露草稿课。 |
| `POST /course-access/courses/join-by-code` | `available` | `{ invite_code }`，直接加入。 |
| `POST /course-access/courses/{course_id}/join-requests` | `planned` | 无邀请码时的申请；创建 `pending` 状态。 |
| `GET /course-access/courses/{course_id}/join-requests` | `planned` | `membership.review`；教师审核列表。 |
| `POST /course-access/courses/{course_id}/join-requests/{id}/approve\|reject` | `planned` | 审核后以共享生命周期 helper 建立/拒绝成员关系。 |

`CourseCard` 必须包含 `course_id, title, cover, status, role, access, capabilities, progress?, build_status?`；
不能要求前端再查询 `teacher_id` 判断角色。

### 3.3 `/app/course/:courseId/overview`：课程概览

| 接口 | 状态 | 说明 |
|---|---|---|
| `GET /facade/course/{course_id}/overview` | `available` | 当前概览、权限、能力、document ID、结构摘要。 |
| `GET /facade/course/{course_id}/overview?view=student\|teacher` | `planned` | 统一学生继续学习/教师待审核与课程健康度，且服务端校验可用视角。 |
| `GET /facade/course/{course_id}/health` | `planned` | 资料、映射、Evidence、图谱、媒体、发布质量门禁摘要。 |

### 3.4 `/app/course/:courseId/learn`：Adaptive Learning Canvas

> 2026-08-07 状态修订：统一学习链已接入新学习页。`/player/init` 只提供 active release 的课程内容和正式 `outline_node_id`；学习事实、断点续学和事件同步统一使用下列 facade 接口。

| 新接口 | 状态 | 权限/语义 |
|---|---|---|
| `GET /facade/course/{course_id}/learning-context` | `available` | `course.learn`；返回 active `release_id`、知识点学习状态、完成原因、认知/推荐状态和 `recent_anchor`；学习轨道以双层状态向学生可见展示。|
| `POST /facade/course/{course_id}/learning-events` | `available` | `course.learn`；记录 `node_opened`、`media_progress`、`read_progress`、`explicit_complete` 等规范化事件，要求幂等键。|
| `POST /facade/course/{course_id}/learning-actions/complete` | `available` | `course.learn`；仅允许当前 active release 的显式完成动作，不产生 mastery 证据。|

旧表中将上述三个接口标记为 `planned` 的文字均由本段状态修订覆盖。

学习轨道状态显示约定：学习完成与认知掌握不合并；绿色“已掌握”只来自正式 `CognitiveState`，黄色“待掌握”对应 `developing/beginner`，未知证据显示“需要更多证据”。认知详细六维状态沿用 `/cognitive/course/{course_id}/state`，由学生点击状态详情后按需读取，不为每个知识点批量请求。

| 子状态 | 接口 | 状态 | 说明 |
|---|---|---|---|
| LEARN | `GET /player/init/{course_id}`、进度保存 | `adapter_needed` | 后续新增 `GET /facade/course/{id}/learning-context` 统一节点、PPT、视频和 return anchor。 |
| UNDERSTAND | `POST /teaching-agent/respond` | `adapter_needed` | 请求必须带 `course_id,node_id,session_id,message,return_anchor`；可降级 V1。 |
| PRACTICE | `GET /facade/course/{id}/quiz`；attempt/grade | `available` | 当前支持题库题；个性化推荐接口见下方。 |
| VISUALIZE | `GET /visualization/course/{id}/plans`、`GET /visualization/{plan_id}` | `available` | 仅显示已发布、允许算法。 |
| NOTE | `/notes` CRUD | `available` | 新增 `node_id,page,timecode` 统一锚点字段适配。 |
| CITATION | `GET /facade/course/{id}/citation/{node_id}` | `available` | Evidence V2 仅显示 experimental，不得假称可验证引用。 |
| VERIFY | `POST /facade/course/{id}/learning-actions/complete` | `planned` | 记录动作完成、返回锚点和是否形成正式证据；非评分动作不得抬高表现分。 |

个性化练习应增加：

```text
POST /api/v1/practice/course/{course_id}/recommendations
GET  /api/v1/practice/course/{course_id}/recommendations/{recommendation_id}
POST /api/v1/practice/course/{course_id}/recommendations/{recommendation_id}/start
POST /api/v1/practice/attempts/{attempt_id}/submit
```

首接口返回 `policy_version, six_dimensions, reason_codes, evidence_refs, confidence,
question_source=bank|generated_draft`。无匹配题时创建 `generated_draft`，**不可直接面向学生发布**。

### 3.4.1 `/app/course/:courseId/analytics`：教师学习分析

| 接口 | 状态 | 权限/语义 |
|---|---|---|
| `GET /facade/course/{course_id}/analytics` | `available` | `analytics.view_course`；返回当前或指定 release 的知识点学习人数、完成率、掌握等级分布、未知/低置信度和待推荐人数，并提供学生完成摘要。|
| `GET /facade/course/{course_id}/analytics/students/{student_id}` | `available` | `analytics.view_member`；返回学生知识点学习矩阵、认知摘要、推荐状态和审计引用，不返回原始聊天、完整答案或 LLM trace。|

教师统计只读取统一学习投影和认知/推荐摘要，不读取 `StudentEnrollment.overall_progress`、旧脚本节点汇总或旧页面统计字段。

### 3.5 `/app/course/:courseId/build`：教师课程建设

建设页需采用一个读模型和多个命令接口，避免前端直接编排历史 `document`、`mapping`、`asset` 的内部细节。

| 接口 | 状态 | 用途 |
|---|---|---|
| `GET /facade/course/{id}/build` | `planned` | Local Rail 的七步状态、未保存变更、质量门禁、发布版本。 |
| `GET/POST /course-build/{id}/materials` | `planned` | 课程资料清单与受控上传；上传只创建任务，不同步 OCR。 |
| `POST /course-build/{id}/materials/{material_id}/parse` | `planned` | 创建解析任务；返回 `202 task_id`。 |
| `GET/PUT /course-build/{id}/structure` | `planned` | 章节/节点树与乐观锁。 |
| `GET/PUT /course-build/{id}/scripts` | `planned` | 教学讲稿编辑、版本、草稿。 |
| `GET/POST/PUT /course-build/{id}/page-mappings` | `planned` | PPT 页映射候选、教师锁定、重跑。可复用已有 mapping 服务。 |
| `GET /course-build/{id}/media-jobs` | `planned` | 音频、数字人、字幕、视频产物任务。 |
| `POST /course-build/{id}/validate` | `planned` | 返回明确的质量门禁明细。 |
| `GET /course-build/{id}/releases` | `planned` | 发布记录、差异、回滚候选。 |
| `POST /course-build/{id}/releases` | `planned` | 发布不可变 release，成功后改变课程可见版本。 |

所有建设写操作需要 `course.edit`；发布需要 `course.publish`。AI/OCR 输出必须是 candidate，
除教师设置的“自动接受但可回退”策略外，不得悄悄覆盖教师锁定值。

### 3.6 `/app/course/:courseId/knowledge`：知识空间与图谱治理

| 接口 | 状态 | 用途 |
|---|---|---|
| `GET /graph/course/{id}/snapshot` | `available` | 读当前发布/指定版本快照。 |
| `GET /graph/course/{id}/nodes/{node_id}/prerequisites` | `available` | 先修关系。 |
| `GET /graph/course/{id}/evidence` | `available` | Evidence 列表。 |
| `GET/POST /graph/course/{id}/reviews`、transition | `available` | 候选审核。 |
| `GET /graph/course/{id}/snapshots|snapshots/diff` | `available` | 版本/差异。 |
| `POST /graph/course/{id}/publish|rollback/{snapshot_id}` | `available` | 发布/回滚。 |
| `GET /facade/course/{id}/knowledge?node_id=` | `planned` | 前端首屏用的局部图、节点定义、相关 Evidence、学习位置、可见治理动作。 |
| `POST /graph/course/{id}/ingestions` | `planned` | 对课程材料创建 OCR/DocumentIR/Evidence/候选图谱解析任务。 |
| `POST /graph/course/{id}/reparse` | `planned` | 明确版本、影响范围与 stale 策略的重解析。 |

### 3.7 `/app/course/:courseId/experiments` 与平台实验室

Judge0 执行接口仍保留，但新页面不得直接把“执行一段代码”等同于“完成课程实验”。

| 接口 | 状态 | 用途 |
|---|---|---|
| `GET /sandbox/health|languages`、`POST /sandbox/course/{id}/execute` | `available` | 基础运行能力；后端代理 Judge0。 |
| `GET/POST /experiments/course/{id}/definitions` | `planned` | 教师管理课程实验定义、语言、任务说明、限制与发布状态。 |
| `GET/PUT /experiments/{experiment_id}/versions/{version_id}` | `planned` | 实验版本、测试用例、隐藏测试和可回滚配置。 |
| `POST /experiments/{experiment_id}/attempts` | `planned` | 学生创建一次实验尝试。 |
| `POST /experiments/attempts/{attempt_id}/runs` | `planned` | 提交代码；异步返回运行 task。 |
| `GET /experiments/attempts/{attempt_id}` | `planned` | 代码、编译/运行/测试分层结果、资源消耗和 return anchor。 |
| `POST /experiments/attempts/{attempt_id}/finalize` | `planned` | 通过评分规则后形成正式评分型 Evidence；失败不写掌握结论。 |
| `POST /experiments/attempts/{attempt_id}/agent-hints` | `planned` | CodingAgent 的受控分层提示，不能执行任意前端代码。 |
| `GET /lab/catalog|course-tasks|my-experiments|records` | `planned` | 平台实验室四个列表页。 |

### 3.8 `/app/course/:courseId/members` 与 `/settings`

| 接口 | 状态 | 用途 |
|---|---|---|
| Course Access 的成员、能力、邀请码、关闭/重开接口 | `available` | 成员/权限/邀请码第一版。 |
| `GET /facade/course/{id}/members` | `planned` | 成员、分组、加入申请、泛雅同步健康度的页面读模型。 |
| `GET/POST/PUT/DELETE /course-groups/course/{id}/groups` | `planned` | 课程分组与成员分配。 |
| `POST /integrations/fanya/course/{id}/sync` | `planned` | 显式异步同步，不在页面请求中隐式调外部平台。 |
| `GET /facade/course/{id}/settings` | `planned` | 基础信息、发布、Agent、合规、沙箱、平台集成的聚合读模型。 |
| `PUT /course-settings/course/{id}/profile` | `planned` | 名称、简介、封面、可见性等基础信息。 |
| `/safety/course/{id}/...` | `available` | 安全与沙箱策略明细。 |
| `PUT /course-settings/course/{id}/agent-policy` | `planned` | 允许工具、策略版本、确认门槛、教师锁定项。 |

### 3.9 `/app/resources/*`：资源库

当前 `TeacherAsset`、`MediaAsset`、课程文档只覆盖特定用途，不是通用资源库。以下均为 `planned`：

```text
GET    /resources/files?scope=mine|course|recent|trash&cursor=
POST   /resources/files                         # 创建上传任务/预签名会话
GET    /resources/files/{resource_id}
PATCH  /resources/files/{resource_id}           # 名称、标签、描述
POST   /resources/files/{resource_id}/references # 引用到课程/节点
GET    /resources/files/{resource_id}/references
DELETE /resources/files/{resource_id}           # 软删除
POST   /resources/files/{resource_id}/restore
DELETE /resources/files/{resource_id}/purge      # 明确清理，需更高权限
```

需支持 `ResourceItem / ResourceVersion / ResourceReference / ResourceAcl / ResourceTag / RecycleBinEntry`，
删除时返回下游影响而非静默删除。

### 3.10 `/app/tasks/*`：任务中心

下列契约均为 `planned`，统一承载 OCR、导入、图谱构建、媒体生成、实验运行、外部同步等长任务：

```text
GET  /tasks?view=todo|created|system|completed&cursor=
GET  /tasks/{task_id}
POST /tasks/{task_id}/cancel
POST /tasks/{task_id}/retry
GET  /tasks/{task_id}/events                 # 轮询或 SSE 的事件序列
POST /tasks/{task_id}/acknowledge            # 用户确认已读/已处理
```

`TaskViewModel` 至少包含 `task_id,type,status,progress,stage,owner,course_id,created_at,
updated_at,error_code,error_message,retryable,result_ref,affected_resources`。

### 3.11 媒体、TTS、数字人与时间轴

| 接口 | 状态 | 用途 |
|---|---|---|
| `GET /media/course/{id}/timeline`、`POST /media/course/{id}/cues` | `adapter_needed` | 时间轴读写已存在。 |
| `POST /media/assets`、`GET /media/assets/{object_key}` | `adapter_needed` | 资产上传/读取已存在。 |
| `GET /media/digital-human/presets` | `available` | CPU 数字人候选声明。 |
| `POST /media/course/{id}/generation-jobs` | `planned` | TTS/数字人/字幕/封装视频创建异步任务。 |
| `GET /media/course/{id}/releases` | `planned` | 已发布媒体版本、哈希、时间轴版本与播放兼容性。 |
| `POST /media/course/{id}/releases/{id}/activate` | `planned` | 激活可回滚的媒体版本。 |

## 4. 前端实施纪律

1. 在 API client 中按本文定义 `available / adapter_needed / planned / shadow_only`，不能以 404 或空数组推断能力。
2. `planned` 页面使用 MSW/本地 fixture 时必须有醒目的开发标记；上线配置不得把 fixture 当数据源。
3. 每个课程页的第一请求为 `GET /course-access/courses/{id}/access` 或 facade 里返回的同等 access View Model。
4. 对异步任务，页面只依据任务状态显示进度；禁止前端计时猜测任务成功。
5. 对 Citation、R2、Graph、认知、WebResearch 统一显示成熟度与降级原因。
6. 每新增 API，在 `frontend/src/api/` 增加类型、调用、错误映射和契约测试；后端在 OpenAPI 与集成测试中锁定路径、权限和失败语义。

## 5. 与现有接口的迁移规则

- 不立即删除历史 `/document/**`、`/player/**`、`/chat/**`；旧页面继续工作。
- 新 `/app/**` 页面优先使用 facade 和本文件的新领域端点。
- 一个 planned endpoint 实现并通过权限、课程隔离、异常与前端契约测试后，状态才可从 `planned` 改为 `available`。
- 页面若没有真实后端能力，使用 `CapabilityMaturityTag` 与可解释空状态，不显示“已完成”或虚构数据。
