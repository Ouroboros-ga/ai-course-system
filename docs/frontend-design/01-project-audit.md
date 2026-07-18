# 前端产品与实现审计

> 审计日期：2026-07-18
>
> 当前分支：`feature/product1-integration`
> 证据优先级：注册路由与实际调用 > 数据模型 > 自动化测试/运行结果 > 当前产品文档 > 历史规划与比赛材料。

## 1. 产品定位

本系统的当前主产品是面向高校教师与学生的“AI 互动智课生产与学习平台”。它解决的不是一般 LMS 的选课、播放和统计问题，而是把教师已有 PPT、PDF、Word 等静态资料，转化为可编辑的课程结构、讲授脚本、PPT 映射、音频/数字人表现层，并在学生侧提供进度续接、课程内问答、测验和前置知识补学。智能体当前承担的是课程资料辅助处理、脚本/问答/测验/缺口分析等受控生成职责，不是一个可自主改写课程或替代教师决策的“万能聊天机器人”。

当前项目处于 8 月决赛前的稳定与兼容冻结期。教师建课到学生学习已有演示级闭环；真实模型质量、可点击证据、教育知识图谱、学生长期记忆与统一耐久任务系统仍处于待验收、设计或研究阶段。设计可以为这些规划能力预留位置，但原型必须用明显的 Mock/规划标记，不能把目标态当成已交付事实。

与普通在线课程平台的差异：

- 课程不是只上传一个视频，而是由资料、结构、脚本、PPT 页、音频/数字人和学习节点共同组成。
- 学生提问绑定当前课程和知识节点，并可触发前置知识补学与返回。
- 教师需要管理一条包含 AI 生成、长任务、人工检查和发布的内容生产链。
- 比赛要求内容权威、可追溯、交互自然、AI 内容有标识；当前代码只完成了其中一部分流程，证据级引用仍是规划重点。

## 2. 状态口径

| 标记 | 含义 | 设计使用规则 |
|---|---|---|
| 已实现 | 当前注册路由、前端入口和实际调用形成可运行链路 | 可进入近期实现；仍需按真实接口字段设计 |
| 规划中 | 当前产品/重构文档明确提出，尚未形成默认主链 | 可进入信息架构与交互规格，不得冒充已上线 |
| 推导项 | 为连接已实现步骤、降低迷失或解释状态而提出 | 需在文档中说明推导理由；原型用独立 Mock |
| 待确认 | 证据不足或多个文档/实现口径冲突 | 不作为发布阻断的默认事实，进入开放问题 |
| 暂不纳入 | 当前阶段明确禁止或属于产品二/远期研究 | 不进入本轮原型、主导航或完成度宣传 |

## 3. 功能证据表

| 功能 | 角色 | 状态 | 代码/文档依据 | 文件路径 | 已有接口 | 已有页面 | 当前阶段 | 风险与缺口 |
|---|---|---|---|---|---|---|---|---|
| 登录、注册、角色路由 | 全部 | 已实现 | `main.py` 注册 user；路由守卫按角色拦截 | `backend/app/api/v1/endpoints/user.py`；`frontend/src/router/index.js`；`frontend/src/stores/counter.js` | 是 | `/profile` | 保留并复用 | 角色来自 localStorage；前端路由守卫不等于后端完整授权 |
| 教师课程列表与生命周期 | 教师 | 已实现 | 课程列表、发布、下架、删除、统计路由和教师历史页 | `document.py`；`TeacherHistory.vue` | 是 | `/teacher/history` | P0 | 删除风险高；统计语义需与真实样本核验 |
| 教学资料上传与建课 | 教师 | 已实现 | 上传创建课程并进入解析/脚本链 | `document.py`；`document_service.py`；`TeacherDashboard.vue` | 是 | `/teacher/create` | P0 | 请求内职责过多；解析失败/降级来源不够显性 |
| 文档解析结果检查 | 教师 | 规划中 + 部分现状 | 现页显示知识树与解析结果；DocumentIR 规划要求页/块/坐标/质量报告 | `TeacherDashboard.vue`；`docs/refactor/document_kg_v2/R2D0-DocumentIR设计.md` | V1 部分 | 无独立检查页 | 先设计、后接接口 | 缺统一质量字段、逐页 warning、原文 block 定位 |
| 课程结构与脚本编辑 | 教师 | 已实现 | `CourseScript`/`ScriptNode`、保存、快照、回滚 | `course_model.py`；`document.py`；`script_editor.js` | 是 | 教师主页面内 | P0 | 巨型页面；“AI 已生成”与“教师已确认”未分开 |
| PPT 与知识节点映射 | 教师 | 已实现 | 自动/AI/手工映射、应用映射 | `mapping.py`；`mapping_service.py`；`MappingEditor.vue` | 是 | 弹窗 | P0 | 作为大弹窗脱离生产上下文；映射方法/置信度虽有但检查流程弱 |
| TTS 单节点与批量生成 | 教师 | 已实现（fake 回归） | 节点合成、批量状态轮询、兼容状态 | `document.py`；`tts_client.py`；`TeacherDashboard.vue` | 是 | 教师主页面内 | P0 | 内存状态重启丢失；真实质量未验收；需失败节点级重试信息 |
| 数字人生成 | 教师 | 部分完成 | 课程/节点任务创建、任务查询、健康检查 | `video_generation.py`；`video_generation_service.py`；`video_generation_model.py` | 是 | 无完整生产步骤页 | 条件 P1 | 真实 Duix/Gradio 部署待验收；不能把任务成功等同于内容合格 |
| AI PPT 生成 | 教师 | 已实现（fake 回归） | 模板、同步/异步生成接口与弹窗 | `ppt_generation.py`；`PPTGenerationDialog.vue` | 是 | 弹窗 | 条件 P1 | 外部服务；“打开课程”旧跳转仍不一致 |
| 课程预览与发布检查 | 教师 | 推导项 + 部分现状 | 可发布、可进入播放器，但无稳定发布清单 | `TeacherDashboard.vue`；`StudentPlayer.vue`；`docs/产品一-泛雅AI互动智课平台.md` I05 | 发布接口有 | 无完整发布检查页 | P0 设计 | 当前上传链可能自动发布；人工质量门禁没有产品化 |
| 教师素材/形象管理 | 教师 | 已实现 | 素材上传、默认、删除、声音复刻状态 | `asset.py`；`TeacherAssetManager.vue`；`TeacherAvatarSetting.vue` | 是 | 个人中心面板 | P1 | 与课程工作台入口割裂；真实声音复刻外部依赖 |
| 学生选课与课程发现 | 学生 | 已实现 | courses/enroll/my-courses 与课程卡片 | `document.py`；`CourseSelection.vue` | 是 | `/student` | P0 | `/student` 同时承担大厅和学习页，信息层级不清 |
| 学生课程学习空间 | 学生 | 已实现但分裂 | `StudentDashboard` 有 PPT+目录+问答；`StudentPlayer` 有分屏播放器 | `StudentDashboard.vue`；`CourseStructure.vue`；`ChatLearningArea.vue`；`StudentPlayer.vue` | 是 | 两条路由 | P0 原型 | 内容、目录、问答分裂；全屏/抽屉/引用/返回锚点不完整 |
| 播放进度与断点续学 | 学生 | 已实现 | player init/save 与 progress sync/detail/resume | `player.py`；`progress.py`；`useStudentLearning.js` | 是 | 学习页/播放器 | P0 | 多端冲突、精确播放位置与保存反馈规则待确认 |
| 课程内问答与测验 | 学生 | 已实现（流程级） | `/chat/ask`、`/chat/quiz`、QA 模型与组合函数调用 | `chat.py`；`qa_service.py`；`qa_model.py`；`useStudentLearning.js` | 是 | 学习页 | P0 | 无稳定引用/置信/拒答响应契约；真实准确率未证明 |
| 引用与证据定位 | 学生/教师/管理员 | 规划中 + 内部 Shadow | 比赛要求可追溯；P1-04 Evidence Viewer 已独立 admin 路由；V1 学生回答未接 | `EvidenceViewerPage.vue`；`evidence_v2.py`；`docs/refactor/product1/contracts/internal-evidence-api.md` | V2 内部 | `/evidence-viewer/:documentId?`（admin） | 预留 UI，不接生产 | 学生 answer schema 无 citation；DocumentIR/Evidence 仍处 Shadow/研究链 |
| 前置知识补学与返回 | 学生 | 已实现（流程级） | gap、jump、return、jump-stack、learning-path | `prerequisite.py`；`usePrerequisiteJump.js` | 是 | 对话弹窗/学习页 | P0 | 后端有返回接口但当前学习 UI 未形成清晰“补学—返回锚点”条带 |
| 学习路径可视化 | 学生 | 部分完成 | learning-path 接口与 `LearningPathMap` 组件存在 | `prerequisite.py`；`LearningPathMap.vue` | 是 | 无主路由 | P1/待接入 | 入口、数据可信度与推荐理由呈现待确认 |
| 学情与学生状态 | 教师 | 部分完成 | 课程 stats/students、进度图表和学生列表 | `TeacherHistory.vue`；`document.py`；`progress.py` | 是 | 教师历史页抽屉 | P1 | 高频问题、问题证据、内容缺失归因没有接口；理解度不可当精准认知 |
| 高频问题与薄弱知识点分析 | 教师 | 规划中 | 产品/赛题希望学情诊断；当前只有基础进度与理解度 | `docs/产品一-泛雅AI互动智课平台.md` U05；比赛 PDF 第 3-8 页 | 否/不足 | 否 | 只设计信息位 | 不得用观看时长或问题数直接宣称掌握度 |
| 统一长任务中心 | 教师/运维 | 规划中 + 兼容层 | PPT/视频/TTS 有不同查询；R2 规划统一 TaskResult | `docs/refactor/R2统一长任务系统设计.md`；`backend/app/platform/tasks/` | 分散 | 否 | P1 设计 | 无跨任务统一列表、耐久状态和离页恢复契约 |
| 管理员用户与角色 | 管理员 | 已实现 | user list/role 与 AdminPanel | `AdminPanel.vue`；`user.py` | 是 | `/admin` | 保留 | 页面只支持用户角色，不应扩写为全能运维后台 |
| Provider/队列/审计后台 | 管理员/运维 | 待确认或规划中 | platform status 与部分健康接口存在，未形成后台能力 | `platform.py`；`video_generation.py`；R1/R2 文档 | 分散 | 否 | 暂不纳入原型 | 无统一权限、状态、日志、重试和审计接口 |
| 教育知识图谱 | 教师/学生 | 规划中/研究 | 本体、Evidence、教师审核队列与快照发布有设计 | `docs/refactor/document_kg_v2/R2D0教育知识图谱本体与构建算法.md` | 非默认主链 | 占位组件/未注册页 | 只预留入口 | 现有知识树不是已验收知识图谱；GraphRAG 禁止本阶段实现 |
| 学生记忆与可解释认知 | 学生/教师 | 规划中/研究 | LearningEvent -> Evidence -> Memory 语义与研究门禁 | `docs/产品一-泛雅AI互动智课平台.md` 7、11；`docs/research/cognition/` | 无生产接口 | 占位/内部功能 | 暂不纳入 | 合成/研究数据不能当真实学生或生产证据 |
| 计算机垂类、代码执行、复杂多智能体、GraphRAG | 产品二/远期 | 暂不纳入 | 当前阶段 AGENTS 明确禁止；代码为未注册占位 | `docs/产品二-CodeNexus计算机学科智能教学系统.md`；`codebench.py`；`agents.py`；`graphrag.py` | 否 | 占位 | 禁止 | 不进入产品一主导航、原型或完成度表述 |

## 4. 当前前端盘点

### 4.1 真实技术栈

| 类别 | 当前事实 | 结论 |
|---|---|---|
| 框架 | Vue `3.5.29`，Composition API | 保留 |
| 构建 | Vite `7.3.1` | 保留；沙箱内 esbuild 需提升权限 |
| 语言 | JavaScript，未配置 TypeScript/type-check 脚本 | 本轮不迁移 TS |
| 路由 | Vue Router `5.0.3`，history 模式，懒加载 | 保留公开路径，新增原型路径独立隔离 |
| 状态 | Pinia `3.0.4`，真实全局状态主要在 `counter.js`；学生学习集中在 composable | 不虚构完整 domain store；后续按域渐进拆分 |
| UI | 自研 CSS Token + 自研 `Ui*` 组件；没有 Element Plus | 不引入 Element Plus |
| 图标 | `lucide-vue-next` | 全部语义图标复用 Lucide |
| 图表 | Chart.js + vue-chartjs | 分析页继续复用；没有 ECharts |
| 富文本 | marked、highlight.js、KaTeX、DOMPurify | 学习内容继续复用；注意 markdown chunk 体积 |
| 请求 | Axios 封装 `utils/request.js` + `api/*.js`，仍有直接 `request`/`fetch` | 新页面优先走 API 层；原型 Mock 与 API 完全分离 |

### 4.2 路由、页面与布局

- 顶层 `App.vue` 始终渲染浮动 `NavigationBar` 与 `router-view`。
- 教师入口：`/teacher/history`、`/teacher/create`、`/teacher/course/:courseId`。
- 学生入口：`/student`、`/student/course/:courseId`、`/player/course/:courseId`。
- 管理入口：`/admin`；内部证据查看：`/evidence-viewer/:documentId?`。
- `Knowledge.vue`、`StudentHome.vue`、CodeBench/Cognitive/GraphRAG/Agent 等文件存在但不等于已注册能力。
- 当前没有角色化 AppShell。全站导航与工作区内部导航混在一个层级，课程生产和学习页缺少持久上下文栏。

### 4.3 组件复用与状态管理

- 已有基础 `UiButton/UiCard/UiBadge/UiModal/UiTabs/UiProgress/UiEmpty/UiSpinner`，但主流程页面仍大量自定义按钮、状态和卡片。
- 学生侧已有 `CourseSelection`、`CourseStructure`、`ChatLearningArea`、PPT/播放器、前置跳转组件，可作为生产集成参考。
- 教师侧已有 `MappingEditor`、PPT 弹窗、素材管理、版本管理、发布按钮，但关键流程仍堆叠在 `TeacherDashboard.vue`。
- `counter.js` 管登录与角色；agent/cognitive store 是占位；课程、生产任务和学习上下文没有正式 Pinia domain store。

### 4.4 样式与已有设计语言

- `tokens.css` 已建立 8px 间距、Indigo/Purple 主色、语义色、圆角、阴影、动效和 z-index。
- `dark.css` 提供全局暗色 Token，但新业务页没有完整暗色验收证据。
- 当前页已从 emoji 向 Lucide 迁移，但学生节点类型仍以 emoji 字符表达。
- 已有页面大量使用渐变、卡片和悬浮阴影；与本次“高校工具、低干扰、不过度紫色”的方向存在偏差。
- 响应式断点混用；学生学习页在 1024px 以下改成上下堆叠，不是目录/智能体抽屉，导致小屏信息连续性较差。

## 5. 现有页面基线问题

### 学生学习页

1. PPT/课程目录固定占左半屏，AI 区域占右半屏；学习内容与 AI 权重相同，且右侧大量空白。
2. 目录位于播放器下方，观看、定位知识点和问答之间需要频繁跨区扫描。
3. 学生主学习页与独立 `StudentPlayer` 分裂，切换模式会中断当前交互上下文。
4. 问答没有来源列表、证据预览、低置信/拒答样式和返回当前讲解位置。
5. 前置知识有后端 jump/return，但 UI 主要是一次性弹窗，缺少持续可见的“正在补学”和返回锚点。

### 教师生产页

1. 左侧是上传/知识树，中间是内容编辑，用户看不到完整生产流程与依赖关系。
2. 解析、脚本、映射、TTS、数字人、发布的“系统完成、AI 生成、教师确认”状态没有统一语义。
3. 映射与 AI PPT 以大弹窗脱离上下文；长任务状态散落在按钮和 toast 中。
4. 没有发布前质量清单；当前发布按钮无法解释被阻断或仍缺什么。
5. 页面体量过大，独立验证、响应式维护和局部回滚成本高。

## 6. 比赛材料对前端的约束

比赛 PDF 的核心功能与评分要求直接影响产品设计：

- 自然语言、多轮上下文与清晰反馈：AI 面板必须显示当前课程/节点上下文并保留追问。
- 权威可信与内容可追溯：引用入口、证据定位和不足时的拒答/低置信状态应进入核心页，而非二级后台。
- AI 内容显著标识：AI 生成、降级生成、教师确认必须可辨识且不夸大。
- 完整稳定闭环：教师生产流水线、长任务失败恢复和学生补学返回必须可演示。
- 真实用户验证：原型不展示虚构统计；未来分析页必须附数据范围、样本与来源。

## 7. 当前结论

最优先的前端工作不是扩张管理员后台或新增研究功能，而是把两条已存在的主链设计成连续、可解释、可恢复的工作空间：

1. 将学生的 PPT/视频、目录、问答、引用和前置补学组织为一个不中断的学习空间。
2. 将教师的上传、解析、结构、脚本、映射、生成、预览和发布组织为一条可回退、可重试、需人工确认的流水线。
3. 保留当前公开路由/API 和巨型页面，先用独立 Mock 原型验证信息架构，再按步骤抽取现有功能，避免决赛前大规模重写。
## 8. 产品化设计阶段补充审计

本次授权允许设计新增前端、后端接口和真实算法接入方案，但不改变“代码链路才是已实现证据”的状态口径。补充结论如下：

| 能力 | 代码/契约事实 | 当前产品状态 | 设计处理 |
|---|---|---|---|
| internal Evidence API | DTO已冻结、admin路由已挂载 | G4可能为空响应或无页面渲染；非学生能力 | 作为教师/internal接入基础，学生需独立授权API |
| TaskResult/TaskStatus | 领域契约已consumed | 缺跨任务列表、持久化和统一重试入口 | 前端先适配，后端补/tasks聚合 |
| 教育图谱 | enum、dataclass、validation和Shadow存在 | 缺教师审核、持久化和快照产品API | 设计知识治理工作台，按Feature Flag接入 |
| LearningEvent/Evidence/Recommendation | 领域契约与代码存在 | 真实采集、聚合和产品API未完成 | 只设计证据化建议，不宣称已上线 |
| StudentMemory | repository/enums/隔离组件存在 | 无正式路由和产品API；契约状态说明有冲突 | 先解决同意、删除、导出、审计和状态单一事实源 |
| Prototype路由 | 两条路由当前无条件注册 | 进入生产构建的风险存在 | M1改为DEV/显式环境变量注册 |

因此“领域契约已冻结”“Shadow链路已运行”“正式产品已接入”必须在所有页面和汇报中分别表述。
