# 组件清单

> 本清单同时覆盖已有能力、规划能力和本轮原型。是否已有以实际代码为准；“建议”不等于当前已实现。

## 1. 分层约定

- 基础组件：无业务角色，承载布局、反馈、搜索和状态语义。
- 教育组件：承载课程、知识点、播放、学习进度、问答、引用和补学。
- 教师生产组件：承载资料、结构、脚本、映射、生成任务、质量检查和发布。
- 页面容器只负责组合、路由参数和页面级状态；Mock、正式 API adapter 与展示组件分离。
- 组件事件使用动词过去/意图语义，如 select-node、retry-task、confirm-step；禁止子组件直接拼 API URL。

## 2. 基础组件

| 组件 | 用途 | 关键 Props | Events | 状态/变体 | 可访问性 | 现状 | 建议复用 |
|---|---|---|---|---|---|---|---|
| AppShell | 角色化应用外壳 | role, navItems, user | navigate, logout | student/teacher/admin | skip link、landmark | NavigationBar 承担部分能力 | 普通列表与后台页 |
| RoleSidebar | 角色一级导航 | role, items, collapsed | select, toggle | expanded/collapsed/drawer | aria-current、aria-expanded | 未形成统一组件 | 角色工作空间 |
| TopHeader | 全局或工作区顶栏 | title, context, actions | action | default/workspace | header landmark | 分散在页面 | 两个工作区 |
| PageHeader | 页面标题与关键动作 | title, description, actions | action | compact/default | 标题层级连续 | 分散 | 列表、详情 |
| Breadcrumb | 上下文返回路径 | items | navigate | compact | nav label | 未统一 | 教师详情、管理页 |
| StatusBadge | 状态文本与图标 | status, label, tone | — | neutral/info/AI/review/success/warning/danger | 不能只靠颜色 | 分散 | 全站 |
| EmptyState | 无数据下一步 | title, description, action | action | compact/full | 状态文本可读 | 分散 | 课程、问答、任务 |
| ErrorState | 错误与恢复 | title, detail, retryable | retry, view-log | inline/panel/full | role=alert 仅严重错误 | 分散 | 媒体、任务、页面 |
| LoadingState | 局部加载 | label, progress | cancel | skeleton/progress/spinner | aria-busy/progressbar | 分散 | 页面和任务 |
| ConfirmDialog | 高风险确认 | title, impact, confirmLabel | confirm, cancel | danger/default | 焦点圈闭、Esc | 分散 | 删除、回滚、发布 |
| SearchInput | 可清除搜索 | modelValue, placeholder | update, clear | compact/default | label、清除按钮名 | 已有多份实现 | 目录、课程、用户 |
| FilterBar | 筛选组合 | filters, values | change, reset | inline/wrap | 字段关联 label | 分散 | 历史、任务、学情 |
| WorkspaceDrawer | 响应式辅助轨 | open, side, title | close | left/right/bottom | focus trap、恢复焦点 | 推导项 | 目录、智能体、检查轨 |
| SegmentedModeSwitch | 同一上下文的任务模式 | modelValue, options | change | compact | tablist/keyboard arrows | 本轮新增 | 跟随讲解/课件研习 |

## 3. 教育组件

| 组件 | 用途 | 关键 Props | Events | 状态/变体 | 可访问性 | 现状 | 建议复用 |
|---|---|---|---|---|---|---|---|
| CourseCard | 课程摘要与继续入口 | course, progress, role | open, continue | student/teacher | 标题为链接、状态文本 | 已有类似实现 | 课程大厅/列表 |
| CourseOutlineTree | 章节和知识点定位 | chapters, activeId, query | select, toggle, search | learning/editable | tree/treeitem、键盘展开 | 已有多份目录 | 学习空间 |
| KnowledgePointItem | 节点标题和学习状态 | point, active | select | completed/current/upcoming/review | aria-current | 已有类似 | 目录/结构 |
| LearningProgress | 课程进度 | value, label | — | bar/compact/ring | progressbar 值 | 已有 | 顶栏/课程卡 |
| MasteryIndicator | 掌握度 | level, evidence | open-evidence | tentative/confirmed | 解释计算依据 | 规划中 | 正式认知模型通过后 |
| PrerequisitePath | 前置知识路径 | nodes, originAnchor | start, return | suggestion/active | 清楚返回目标 | 接口存在、UI 不完整 | 学习空间 |
| QuestionComposer | 问题输入 | modelValue, context, disabled | submit, stop | idle/generating | label、快捷键说明 | 已有类似 | 智能体轨 |
| AgentAnswer | AI 回答单元 | answer, status, confidence | followup, copy, feedback | streaming/complete/low-confidence/error | aria-live 克制播报 | 已有回答，契约有限 | 学习空间 |
| CitationList | 引用摘要列表 | citations, expandedIds | toggle, locate | locatable/unavailable | button 状态和来源文本 | 规划中/Shadow | 学生回答 |
| EvidencePreview | 页/块证据预览 | evidence, highlight | close, locate | page/block/text | 不仅颜色高亮 | 管理 Shadow 已有 | 未来学生引用 |
| PPTViewer | PPT/课件主画面 | slides, page, mode | change-page, locate | playback/study | 页码、替代文本 | 已有播放器 | 两种学习模式 |
| TranscriptViewer | 当前讲解/全文 | blocks, currentTime | seek, expand | excerpt/full | 可搜索、当前段 aria-current | 已有脚本文本 | 跟随讲解/研习参考 |
| LearningCheckpoint | 小测与理解检查 | question, options | answer, retry | quiz/reflection | fieldset/legend | chat quiz 已有 | 章节结束 |
| PlaybackControls | 播放控制 | playing, time, duration, rate | play, seek, rate, subtitle | compact/full | 每个图标具名 | 已有类似 | 跟随讲解 |
| StudyNotes | 学生笔记 | modelValue, savedAt | update, save | local/synced/error | textarea label、保存状态 | 推导项；无稳定接口 | 课件研习 |
| LearningAnchorBar | 补学返回锚点 | origin, time, question | return | compact/sticky | 目的地清楚 | 推导项 | 补学状态 |
| LearningStage | 双模式主舞台 | mode, playback, slide, note | change-mode, play, note | guided/study/focus | tablist、媒体语义 | 本轮原型新增 | 学生核心页 |

## 4. 教师生产组件

| 组件 | 用途 | 关键 Props | Events | 状态/变体 | 可访问性 | 现状 | 建议复用 |
|---|---|---|---|---|---|---|---|
| CoursePipeline | 完整生产流程 | steps, activeKey | select, collapse | desktop/drawer | 有序列表、当前步骤 | 未统一 | 教师工作台 |
| PipelineStep | 单步状态与阻塞 | step, active | select, retry | all pipeline statuses | 状态文本、计数可读 | 本轮新增 | 流程轨 |
| MaterialUploader | 上传教学资料 | accept, files, limits | upload, remove, retry | empty/uploading/error | 键盘上传替代 | 已有类似 | 教学资料 |
| ParsingResultViewer | 文档解析检查 | document, warnings | locate, confirm | page/tree/warnings | 页/块结构可导航 | 局部已实现，DocumentIR 规划 | 文档解析 |
| ChapterTreeEditor | 章节树编辑 | chapters, selectedId | add, move, rename, select | editable/readonly | 拖拽键盘替代 | 已有类似 | 课程结构 |
| KnowledgePointEditor | 知识点编辑 | point, relations | save, link-source | manual/AI-generated | 字段错误关联 | 已有局部 | 知识点 |
| ScriptEditor | 脚本块编辑 | blocks, activeId | update, regenerate, map | AI/manual/dirty | 编辑区标签、快捷键 | 已有 | 教学脚本 |
| SlideScriptMapper | PPT 与脚本映射 | slides, blocks, mappings | map, unmap, auto-map | manual/AI-suggested/conflict | 双列表键盘操作 | 已有 modal | PPT 映射 |
| GenerationTaskCard | 单个长任务 | task | retry, cancel, view-log | queued/running/success/failed | progressbar、错误文本 | 分散 | TTS/PPT/数字人 |
| LongTaskDock | 跨页面任务停靠 | tasks, expanded | expand, open-center | compact/expanded | 状态变化播报 | 规划 R2 | 工作台底部 |
| QualityGatePanel | 当前步骤质量检查 | checks, suggestions | locate, resolve, confirm | check/suggestion/log | tabs、问题可跳转 | 规划+推导 | 检查轨 |
| PublishChecklist | 发布前置条件 | items, progress | open-item, publish | blocked/ready | 阻断原因与按钮关联 | 推导项 | 发布检查 |
| VersionHistory | 版本快照/回滚 | versions, current | preview, rollback | compact/full | 表格标题、风险说明 | 接口已实现 | 课程详情 |
| AIProvenanceMark | AI 产物来源 | providerLabel, generatedAt | — | inline/block | 文本而非仅紫色 | 推导项；比赛要求 | 脚本/建议/内容 |
| ReviewConfirmation | 教师确认 | reviewer, time, version | confirm, revoke | pending/confirmed/stale | 解释确认范围 | 规划/推导 | 所有 AI 步骤 |

## 5. 组件状态契约

所有异步业务组件至少接收或内部归一化以下状态：idle、loading、success、empty、warning、error、forbidden。长任务额外使用 queued、running、review-required、confirmed、failed、stale。

以下状态不得合并：

- API 请求成功与业务生成成功。
- AI 生成成功与教师确认完成。
- 可继续警告与阻断失败。
- 引用存在与引用可稳定定位。
- 本地笔记已保存与服务端已同步。

## 6. 本轮原型组件落点

- 学生：StudentLearningPrototype、CourseOutlinePanel、LearningStage、LearningAgentPanel、PrototypeStatusBadge。
- 教师：TeacherPipelinePrototype、CoursePipelineNav、PipelineWorkArea、QualityGatePanel、PrototypeStatusBadge。
- 数据：frontend/src/prototypes/mock/frontendDesignMocks.js，只服务原型，不进入现有 API 封装。
- 样式：frontend/src/prototypes/styles/frontend-design.css，全部限定在 fd-workspace 作用域。
## 7. 全产品新增组件域

以下是产品化阶段的目标组件，不表示当前均已实现。组件先消费 [12-frontend-contracts-and-api-plan.md](./12-frontend-contracts-and-api-plan.md) 的 ViewModel，不直接消费后端零散 DTO。

### 7.1 学生学习与个性化

| 组件 | 用途 | 关键 Props | Events | 状态/变体 | 可访问性 | 当前状态 | 复用位置 |
|---|---|---|---|---|---|---|---|
| ContinueLearningRow | 恢复最近课程 | course, playbackAnchor | resume | loading/stale/ready | 按钮名称含课程和位置 | 推导项 | 学生首页/课程列表 |
| LearningModeSwitch | 跟随讲解/课件研习 | mode, disabled | change | guided/study | tablist、方向键 | 原型已有局部实现 | 学习空间 |
| GuidedMediaStage | 视频主画面+PPT辅助画面 | media, slide, context | swap, seek, fullscreen | video/avatar/audio-only | 媒体文本替代、字幕 | 需产品化 | 学习空间 |
| StudySlideWorkspace | PPT主画面+笔记 | slide, noteDraft, context | save-note, locate | editing/saving/conflict | 标签、保存状态播报 | 原型局部 | 学习/复习 |
| RecommendationReason | 展示建议与证据 | recommendation | open-evidence, dismiss | rule-based/uncertain | 不只用优先级颜色 | 规划/领域契约已有 | 首页/建议页 |
| LearningEvidenceList | 学习结论依据 | evidence[] | locate | event/quiz/question | 明确数据时间和来源 | 规划/领域契约已有 | 建议/报告 |
| MemoryEntryEditor | 查看、修改、删除Memory | entry, permissions | update, delete | active/stale/disabled | 删除确认、焦点恢复 | 隔离组件已有雏形 | Memory设置 |
| PersonalizationControl | 个性化授权 | consent, scope | change, export, delete-all | on/off/pending | 开关状态文本可读 | 规划中 | 隐私设置 |

### 7.2 教师知识治理与质量

| 组件 | 用途 | 关键 Props | Events | 状态/变体 | 可访问性 | 当前状态 | 复用位置 |
|---|---|---|---|---|---|---|---|
| KnowledgeGovernanceShell | 知识审核三栏工作区 | course, snapshot, selection | navigate, publish | v1-mapping/shadow/production | landmark 与标题层级 | 规划；V1映射可复用 | 知识治理 |
| ReviewQueue | 候选审核队列 | items, filters | select, batch-action | proposed/review/conflict | 表格替代、批量说明 | 领域契约已有，无产品页 | 知识治理 |
| KnowledgeTreeEditor | 知识点/关系浏览编辑 | nodes, relations | select, merge, split | tree/relationship | tree键盘语义 | 当前知识树可复用 | 生产/治理 |
| SourceEvidenceCanvas | PPT/文档/脚本同步证据画布 | sources, anchor | locate, compare | slide/document/script | 缩放、文本替代 | Evidence Viewer 可复用 | 治理/问答质量 |
| CandidateInspector | 候选、依据、置信与审核 | candidate, evidence | accept, revise, reject | node/relation/mapping | 表单错误就近提示 | 规划中 | 知识治理 |
| SnapshotBar | 草稿run与active snapshot | run, activeSnapshot | compare, publish, rollback | clean/dirty/stale | 风险范围可读 | 领域契约已有，无产品页 | 治理/版本 |
| StaleImpactPanel | 上游修改影响 | dependencies[] | regenerate, acknowledge | affected/unaffected/blocked | 不只用连线/颜色 | 规划中 | 生产/版本 |
| RAGQualityBreakdown | 检索与引用质量 | metrics, failures | filter, inspect | overview/knowledge/question | 图表表格替代 | 规划中 | 教师分析 |
| LearningInsightPanel | 学情结论与依据 | insight, evidence | inspect, annotate | observed/uncertain | 时间范围和样本明确 | 部分数据/规划聚合 | 教师分析 |

### 7.3 平台状态与版本

| 组件 | 用途 | 关键 Props | Events | 状态 | 当前状态 |
|---|---|---|---|---|---|
| GlobalTaskDock | 跨页任务停靠 | tasks | open, retry, dismiss | running/failed/partial | 规划；TaskResult契约已有 |
| VersionDiffViewer | 对比资料/脚本/映射/快照 | before, after, scope | restore | loading/ready/error | 规划中 |
| PermissionBoundary | 统一无权限和只读态 | permission, reason | request-access, back | forbidden/read-only | 推导项 |
| FeatureMaturityLabel | internal/shadow/canary/beta | mode | — | 非生产能力提示 | 推导项，仅内部页面 |
