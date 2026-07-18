# 前端适配模型、接口与算法接入方案

> 目的：让教师/学生页面消费稳定的前端ViewModel，而不是直接依赖当前零散、命名不一致的后端响应。本文件允许规划新增后端接口与真实算法接入，但坚持新增兼容、Feature Flag、Shadow/Canary和可回滚，不改变现有公开路径与字段语义。

## 1. 技术边界

当前真实栈为Vue 3.5、Vite 7、JavaScript、Pinia、Vue Router、自研Ui组件、Lucide和Chart.js。没有Element Plus、ECharts和TypeScript。

本轮不迁移TypeScript。契约使用JSDoc typedef、运行时parser和contract test表达；未来若迁移TypeScript，可从同一schema生成类型。

推荐分层：

~~~text
backend DTO
→ api/*.js 原始请求
→ adapters/*.js 校验、兼容和ViewModel转换
→ stores/composables 业务状态
→ pages/components 只消费ViewModel
~~~

组件不得知道code/message外壳、snake_case/camelCase差异、provider私有字段和V1/V2 Feature Flag。

## 2. 统一请求与错误适配

现有request.js默认剥离code/message并返回data；Evidence API使用独立fetch且允许HTTP错误。因此新增适配层统一为：

| 字段 | 说明 |
|---|---|
| ok | 请求和业务均成功 |
| data | 校验后的ViewModel |
| error.code | 稳定前端错误码 |
| error.message | 用户可读说明 |
| error.recoverable | 是否可重试 |
| error.retryAfter | 可选等待时间 |
| error.requestId | 审计/排障ID |
| meta.contractVersion | 消费的后端契约版本 |
| meta.featureMode | off/shadow/canary/production |

不强制所有后端立即改成同一响应外壳；api层保留现有行为，adapter负责归一。未知major版本、缺失稳定ID和非法bbox必须fail-closed。

## 3. 核心ViewModel

### 3.1 PlaybackContext

| 字段 | 类型 | 说明 |
|---|---|---|
| courseId | string | 课程稳定ID |
| nodeId | string或null | 当前知识节点 |
| playbackTime | number | 秒 |
| duration | number或null | 秒 |
| slideNumber | number或null | 1-based |
| scriptBlockId | string或null | 当前脚本块 |
| mode | guided/study/review | 学习模式 |
| conversationId | string或null | 问答上下文 |
| savedAt | ISO时间或null | 服务端确认时间 |
| revision | string或null | 进度并发版本 |

保存时使用revision或If-Match解决多端冲突；前端不得默认为“最高进度获胜”。

### 3.2 KnowledgeAnchor

字段：courseId、nodeId、artifactId、documentId、unitId、blockId、evidenceId、slideNumber、charStart、charEnd、bbox、scriptBlockId、playbackTime、versionRef。

所有字段可选但至少有courseId和一个具体锚点。不能用知识点标题充当稳定ID。

### 3.3 CitationViewModel

| 字段 | 说明 |
|---|---|
| key | 稳定citation key；无证据为null |
| statement | 被支持的回答陈述 |
| sourceTitle | 学生可读来源 |
| anchor | KnowledgeAnchor |
| validationStatus | verified/partial/mismatch/stale/no_evidence/unavailable/forbidden |
| locationPrecision | span/block/page/source_only/none |
| abstain | 是否应停止生成强结论 |
| abstainReason | 证据不足原因 |
| confidence | 可选；仅为引用校验辅助 |
| versionRef | 来源版本 |
| actions | locate/open_page/retry/report |

后端CitationStatus已包含verified、partial、mismatch、stale和no_evidence。unavailable、forbidden及locationPrecision是前端或API网关派生状态，不回写领域枚举。

### 3.4 LongTaskViewModel

| 字段 | 说明 |
|---|---|
| taskId | 稳定任务ID |
| taskType | document_parse/script_generation/ppt_generation/tts_node/tts_batch/digital_human_video/voice_clone/platform_sync/remote_video |
| status | pending/running/succeeded/failed/cancelled/timeout/partial_success |
| progress | 0–1或null |
| stage | 当前阶段文案 |
| courseId/nodeId | 业务上下文 |
| provider | 可选服务方 |
| errorCode/errorMessage | 失败信息 |
| retryable | 是否可重试 |
| retryStrategy | restart/reuse_partial/retry_failed_units |
| parentTaskId | 重试或批任务关联 |
| startedAt/updatedAt/finishedAt | 时间 |
| artifactRef | 成功产物 |

retrying不是TaskStatus，而是存在新task且parentTaskId指向失败任务的UI状态。stale是产物版本状态，不是任务状态。

### 3.5 ReviewCandidateViewModel

字段：candidateId、kind、nodeOrRelationType、name、aliases、sourceRunId、sourceVersion、status、confidence、evidence[]、validationIssues[]、reviewVersion、reviewer、reviewedAt、reviewReason、before、after。

status映射ReviewStatus：proposed、accepted、rejected、needs_review、superseded。conflict由validationIssues派生。

### 3.6 GraphSnapshotViewModel

字段：snapshotId、courseId、ontologyVersion、sourceRunId、status、nodeCount、relationCount、acceptedCount、active、createdBy、createdAt、activatedAt、qualityGate、previousSnapshotId。

active是指针状态，不改变不可变snapshot内容。

### 3.7 StaleDependencyViewModel

字段：sourceRef、sourceVersion、targetRef、targetType、currentState、reasonCode、affectedUnits[]、requiredAction、blocking、detectedAt。

currentState：current、stale、missing、rebuild_required、building、blocked。依赖由后端计算，前端只展示。

### 3.8 LearningEvidenceViewModel

字段：evidenceId、studentId、courseId、nodeId、evidenceType、eventRefs[]、observedValue、observedAt、sourceVersion、qualityFlags[]、visibility。

它表示观察证据，不表示最终认知结论。页面必须展示eventRefs或可读来源。

### 3.9 LearningRecommendationViewModel

字段：recommendationId、type、priority、title、description、nodeId、evidenceRefs[]、reasonSummary、uncertainty、source、sourceVersion、createdAt、expiresAt、actions。

除continue外evidenceRefs必须非空。interaction semantics只能进入reasonSummary/uncertainty，不能单独生成掌握度。

### 3.10 StudentMemoryViewModel

字段：memoryId、type、content、courseScope、source、sourceRefs[]、reason、lifecycleState、createdAt、expiresAt、confidence、allowedForPersonalization、editable、deletable、auditSummary。

lifecycleState：active、expiring、expired、corrected、soft_deleted。跨课程默认不共享。当前registry把student-memory/1.0标为frozen-major，但enums.py文件头仍写draft；在产品API接入前必须由契约Owner消除该状态冲突。

## 4. 前端目录建议

~~~text
frontend/src
├─ app
│  ├─ shells
│  └─ navigation
├─ domains
│  ├─ course
│  ├─ learning
│  ├─ evidence
│  ├─ knowledge-governance
│  ├─ tasks
│  └─ student-memory
├─ pages
│  ├─ student
│  └─ teacher
├─ shared
│  ├─ ui
│  ├─ states
│  └─ accessibility
└─ prototypes
~~~

不要求一次搬迁现有目录。每个里程碑只创建正在接入的domain adapter和页面薄壳，旧组件通过facade复用。

## 5. 现有接口接入

### 学生

- document courses、my-courses、enroll。
- player init、knowledge-points、progress save/get。
- progress detail/resume/sync。
- chat ask、quiz、history。
- prerequisite analyze-gap、jump、return、jump-stack、learning-path。

### 教师

- document上传、课程列表、课程生命周期、脚本保存/快照/回滚。
- mapping详情、页文本、auto、ai-match、单点/批量保存、apply。
- PPT主题、生成和任务查询。
- TTS节点/批量状态。
- video generation任务。
- asset上传、列表、默认、删除和声音克隆。

### 内部可信能力

- /api/v1/evidence-v2已冻结DTO，但当前为admin/flag门禁，G4行为可能是空Evidence或页面渲染不可用。
- 教育图谱、LearningEvent、LearningEvidence、MasteryState、Recommendation和StudentMemory存在领域契约/代码，不等于已存在教师/学生产品API。

## 6. 建议新增接口

所有接口均为新增，不替换V1已有路径。

### 6.1 学生聚合与学习上下文

| Method | 路径 | 用途 |
|---|---|---|
| GET | /students/me/dashboard | 继续学习、任务和可用建议摘要 |
| GET | /courses/{courseId}/learning-context | 课程、目录、媒体、映射、进度和权限的聚合初始化 |
| PUT | /courses/{courseId}/playback-context | 带revision保存上下文 |
| GET/POST/PUT/DELETE | /courses/{courseId}/notes | 页/节点/时间锚定笔记 |
| GET | /students/me/activity | 学习事实时间线 |
| GET | /students/me/questions | 历史问答和版本状态 |

### 6.2 Citation学生访问

- chat/ask响应增量增加optional citations、citation_validation和answer_scope，不删除现有字段。
- GET /courses/{courseId}/citations/{citationKey}：课程授权后返回学生可见CitationViewModel数据。
- GET /courses/{courseId}/evidence/{evidenceId}/view：返回脱敏页面/文本和定位信息。
- 后端必须校验学生已选课和Evidence属于该课程；不得复用admin_only端点直接放开。

### 6.3 教师任务与版本

| Method | 路径 | 用途 |
|---|---|---|
| GET | /tasks | 按用户、课程、类型、状态分页 |
| GET | /tasks/{taskId} | 任务详情和阶段 |
| POST | /tasks/{taskId}/retry | 创建关联重试任务 |
| POST | /tasks/{taskId}/cancel | provider支持时取消 |
| GET | /courses/{courseId}/versions | 聚合资料、脚本、映射、图谱和发布版本 |
| POST | /courses/{courseId}/dependencies/impact | 计算变更影响 |
| GET | /courses/{courseId}/publish-check | 阻断项和警告 |
| POST | /courses/{courseId}/publish-version | 发布显式版本 |

### 6.4 知识治理

接口见11-knowledge-evidence-governance.md。写请求包含idempotencyKey、reviewVersion、sourceRunId和reason。

### 6.5 学情、推荐与Memory

| Method | 路径 | 条件 |
|---|---|---|
| GET | /courses/{courseId}/analytics/overview | 现有progress聚合即可先实现 |
| GET | /courses/{courseId}/analytics/questions | 问答聚合和课程授权 |
| GET | /courses/{courseId}/analytics/rag-quality | Citation生产链和质量口径稳定 |
| GET | /students/me/recommendations | 推荐通过Shadow/Canary门禁 |
| POST | /students/me/recommendations/{id}/feedback | 记录接受/忽略，不直接改分 |
| GET/PATCH/DELETE | /students/me/memory | 同意、删除、审计契约稳定 |
| POST | /students/me/memory/export | 隐私导出 |
| PUT | /students/me/memory-consent | 课程级或全局授权 |

教师读取学生Memory需要单独政策。默认教师分析只展示聚合学习证据，不展示学生私密Memory全文。

## 7. 后端真实算法接入顺序

### A. DocumentIR生产化

1. 真实parser provider在离线基准上达到门禁。
2. 保留V1主链，V2先Shadow。
3. 页面和block真实渲染、稳定ID、Geometry和质量warning可回放。
4. Canary课程人工验收后才成为Evidence来源。

### B. Evidence与可信检索

1. 从DocumentIR生成EvidenceSpan和版本引用。
2. 检索保留evidence IDs，不在rerank/prompt中丢失。
3. Citation validator输出verified/partial/mismatch/stale/no_evidence和abstain。
4. 无证据不生成伪citation key；stale不展示为当前依据。
5. 学生访问单独做课程授权和脱敏。

### C. 教育图谱治理

1. 结构节点确定性生成。
2. 语义节点和关系只生成candidate。
3. 类型矩阵、方向、自环、先修DAG和Evidence不变量由确定性代码校验。
4. 教师审核持久化。
5. accepted对象生成不可变snapshot并原子切换active pointer。
6. 当前阶段不实现GraphRAG；RAG可独立消费Evidence和必要知识锚点。

### D. 学习证据与建议

1. LearningEvent append-only、幂等、可更正。
2. LearningEvidence保留eventRefs和sourceVersion。
3. 首个生产版本只采用可解释规则和显式表现证据。
4. 交互语义保持evaluation_only或Shadow，作为原因上下文，不直接修改MasteryState。
5. Recommendation必须携带evidenceRefs和不确定性。
6. BKT/HMM/LSTM/DKT不进入当前实施范围。

### E. StudentMemory

1. 先完成同意、课程隔离、生命周期、删除、导出和审计。
2. 只允许经过批准的LearningEvidence和显式学生/教师输入生成候选Memory。
3. 敏感或低置信候选需要人工/学生确认。
4. Shadow阶段不注入正式QA Prompt。
5. Canary通过后以Feature Flag逐课程开放，并提供一键关闭和删除。

## 8. 安全、权限与并发

- 每个course scoped接口后端校验课程归属/选课关系。
- 写请求使用幂等键；审核、笔记、进度和发布使用revision或If-Match。
- 403与404语义按防信息泄漏策略统一，前端不猜。
- 页面不可读取provider密钥、原始本地文件路径和其他课程Evidence。
- 删除Memory、发布、回滚、删除课程、重建索引均写审计记录。
- Feature Flag默认off或V1；Shadow结果不得返回学生。
- 未知contract major、缺稳定ID、无Evidence时fail-closed。

## 9. 契约测试

每个adapter至少覆盖：

1. 正常V1响应。
2. 新增optional字段。
3. 缺必填稳定ID。
4. 未知major。
5. 403/404/409/422/503/504。
6. stale、partial、no_evidence。
7. 分页和空结果。
8. 重复提交与revision冲突。
9. Feature Flag关闭。
10. snake_case/camelCase兼容边界。

真实外部LLM、TTS、PPT和数字人服务不进入自动化测试；使用fake adapter并验证业务调用关系。
