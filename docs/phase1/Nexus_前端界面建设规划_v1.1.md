# Nexus 前端界面建设规划 v1.5（文件名沿用 v1.1，版本以本变更头为准）

> **v1.5 变更（2026-09-07 晚，启动页重设计 v2 → 已实现）**：用户指出线上启动页「好丑」。
> 先出的 v1（编辑部/杂志方向）**被否**——根因不是细节，是**角色错了**：把落地页手法
> （46px 衬线大标题、300px 幽灵描边字、竖排刊号、※脚注系统）搬进了聊天控制台。
> 这块界面只服务一件事：**让用户打出第一句话**。且与已拍板的 v4/v6（NexusLab）视觉词不一致。
> **v2 = 控制台方向**，见 `2026-09-07_Nexus_启动页重设计_v2.html`，已落地：
> - **左对齐到消息列**（`margin: auto 0` + 横向铺满），发第一条消息不再跳位；标题降到 27px 无衬线。
> - 左内容 + 右 300px「**本会话上下文**」面板：课程 / Web 检索 / CS 知识库 / 课程资料 / 会话存储，
>   能力三态只读 `nexusCapabilities.js`，文案沿用 P2-8（已生效 / 已连接·未生效 / 未建立）。
> - 模式切换：两张 `.nx-mode-card` → **一行分段控件 `.nx-seg`** + 一行 mono 工具白名单（含 `+n` 折叠）。
> - 起点建议：三张 `.nx-quick-card` → **发丝线行式清单 `.nx-starter`**（序号·标题·描述·箭头）。
> - 课程绑定：淡蓝满宽引导条 `.nx-start-course` **删除**，并入上下文面板一行 + 26px 描边按钮。
> - accent 全屏只用**一处**：`.nx-starter:hover .nx-starter-ar`（箭头右移并着色）。
> - 零装饰字符；3% 纸纹未加（沿用页面既有质感，避免再叠一层）。
> **回归**：`npx vite build` ✓；契约测试 88/89（#88 过期断言，基线未变）；eslint 无新增错误（存量 10 条）。
> **待定**：`--nexus-accent` 是否由 #007AF4 降饱和至 #2A6FAD（v4/v6 口径，会影响全站，未擅改）。

> **v1.4 变更（2026-09-07 晚，v6 定版 → 已开工实现）**：用户对 v5 方向认可，但要求四处**落位**改动，
> 见定版设计板 `2026-09-07_NexusLab_研究与实验一体化设计板_v6.html`（4 屏）。本轮**只动落位，不动信息架构**：
> ① **视图切换器固定右上角**（不做小方框、不随视图漂移）；**工作台内不再有左上「← 返回研究对话」**——切换器即返回。
> ② **左上角显示当前视图身份**：研究对话=会话名 +「Research 会话」；工作台=实验名 + job_id。
> ③ **审批浮窗挂到输入框上方**（`[批准执行] [查看完整方案]` +「↓ 在下面输入框提出修改，改完重新确认」），
>   与「提出修改」同一视线落点；消息流里那张卡保留作留存记录。
> ④ **「询问 Nexus」改为可自由拖动的浮窗**（fixed + sessionStorage 记位，默认让开右侧图标轨+抽屉，z-index 70），
>   继承同一研究会话上下文，关闭不影响运行。
> **已落地代码（本轮）**：
> - 新增 `frontend/src/app/pages/nexus/reproShared.js` —— run 的**只读投影**（状态/阶段/耗时/日志/步骤）单一真相源，
>   会话内 Console 与实验工作台共用，禁止两处各写一份。
> - 新增 `components/NexusExperimentWorkspace.vue` —— 主舞台工作台（状态 + run 切换 + 询问/取消/分析/再运行；
>   六段阶段条；左「运行配置·只读」+步骤时间线，右 tab 日志/指标/产物；空态「这个会话还没有实验」）。
>   注：其头部**不再重复实验名**——名在页面顶栏，重复正是上一版被判「臃肿」的原因。
> - 新增 `components/NexusAskWindow.vue` —— 可拖询问浮窗。
> - `NexusPage.vue`：顶栏 `.nx-top-left`（模式选择器 + 视图身份）/ `.nx-view-switch`（右上固定）；
>   `.nx-lab-host` 按 `isLabView` 挂载工作台；composer 内 `.nx-approval-dock`；
>   会话内联复现卡新增「打开工作台」（`openRunInWorkspace`）；对话区四块加 `v-show="!isLabView"`。
> - 实验名**后端无定义**：`nexus_runs` 无 title/name 字段（`nexus_run_service.py:38` DDL）。
>   首版用 `experimentName()` 本地命名 = `{preset_id} 复现 · #{同 preset 序号}`，如实表达已知事实。
>   **待家良决定**：是否给后端立项「自定义实验名」（加 `title` 字段）。
> **回归**：`npx vite build` 通过；`node --test src/api/__tests__/apiContracts.test.cjs` = 88/89（#88 仍为过期断言，基线未变）；
> 新文件 eslint 无错（NexusPage.vue 剩余 10 条 no-unused-vars 为历史存量，非本轮引入）。
> **未部署**：工作区改动尚未构建上线。

> **日期**：2026-09-06。**性质**：规划文档，不是实现声明。所有"已有"以代码实测为准，"待建"均未开工。
> **v1.1 变更（2026-09-06）**：**撤回 S3「NexusLab 作业列表页」**。v1.3 C4 原文为「**会话内**只读实验详情」，
> 设计上没有独立的作业列表页，且后端无 list API —— 该页属我越权加入，不是设计缺口。
> Console（原 S4）改为**会话内就地展开**，先建。
> **v1.2 变更（2026-09-07，用户拍板）**：**S4 形态升维 —— 「会话内就地展开」改为「主舞台实验工作台」**。
> 依据：用户实测反馈「运行工作台堆在右边太挤、很怪；这是帮教师复现论文的工作台，要能调参数、看细节输出」，
> 并对照真实科研复现工作流调研（W&B / MLflow / Hydra / TensorBoard 实践，见设计板 v3 §调研）。
> 新形态：**会话流里的实验卡降为一行「引用条」，完整工作台占据主舞台（≥55% 宽）**；窄屏二选一切换。
> 仍是 Nexus 内组件，**不新增路由、不做作业列表页**（该裁定不变）。
> 全文凡写「会话内就地展开」处，形态均以 v1.2 为准。
> **v1.3 变更（2026-09-07，用户拍板）**：**Research 与工作台统一为「同一个研究会话的两个视图」**，不再是两个产品。
> 用户指出：v4 只画了「实验运行以后怎么看」，缺「实验开始以前怎么准备」和「结束以后怎么继续研究」。
> 新增三处连接（见 `2026-09-07_NexusLab_研究与实验一体化设计板_v5.html`）：
> ① **视图切换** —— Research 会话顶部常驻 `[研究对话] [实验工作台 · N 个运行中]`；General 模式不显示任何实验入口。
> ② **准备态 Board 3** —— 「准备实验」进入主舞台的准备态：目标 / 资料来源 / 环境与执行方案 / 资源预算，
>   每项标注 **已确认 · 待补充 · 当前不支持**；默认只问三件事（验证什么 / 用什么 / 花多久），高级配置折叠。
>   约束：**打开工作台不启动任务，改方案不自动执行**；审批仍在准备态末尾，走既有服务端硬门。
> ③ **结果返回对话 Board 7** —— 主动作「分析本次结果」→ 回研究对话 + 结构化引用，输入框**预填但未发送**；
>   次动作「调整方案再运行」（原「基于此 run 调整」改名）：复制冻结配置 → 新提案 → 展示差异 → 重新审批 → 新 run。
> 另补：**工作台空态**（Board 2，不得要求用户先用对提示词才有入口）、**询问 Nexus 抽屉**（Board 5，
> 只传 run ID + 步骤 + 有界日志末 40 行，不复制全量日志、不混入其他会话）、**后台完成轻提示不强制跳转**。
> **v1.3 同步更正三处过期事实**（详见设计板 v5 说明表）：
> - ~~GAP-2「无 run list API」~~ **作废**：`GET /runs`、`GET /runs/{run_id}` 已上线（某会话我的 runs，含实时态合并），
>   前端 `listNexusRuns` 已封装并调用 2 次。
> - ~~Verifying 画成绿色完成~~：当前 preset **无干净环境 B 验证**，应显示 **不适用**（虚线空心点 + 灰字）。
> - ~~预算「不超过 15 分钟」~~ 属编造：`REPRO_PRESETS["nanogpt"].estimated_minutes = 5`，且可执行 preset **目前只有 1 个**。
> **v1.3 唯一新缺口**：`_public_approval`（`nexus/src/nexus/tools/reproduction.py:300`）不返回 `steps` 与
> `expected_metrics` —— 准备态的步骤与判定指标不能由前端拼，需会话侧 plan 投影供给。
> **同日事实更新**：NX-E2/E3 已由并行工作线交付并通过浏览器真实链路验收
> （`验收记录/NX-E2E3_验收_2026-09-06.md`）——stage_events / live_log_tail(2000) /
> steps_result.log_tail(2000) / cancel 全部有真数据。**§1.3 与 §4.4 的「数据源缺口」表已过时**，
> 以 `nexus_proxy.py:502 _trim_job_record` 与验收记录为准；现行缺口见设计板 v3 Board C（GAP-1~4）。
> **依据顺序**：AGENTS.md → `design.md`（视觉/布局/按钮权威）→ [v1.3 架构](CodeNexus_转型设计与实施方案_v1.3.md) → [P2/NX 开发计划](CodeNexus_P2开发计划.md) → [前端规格 v3.0](Nexus_AI_前端开发规格与UX落地说明.md) → 代码事实。
> **核对基线**：`dev-liu`，HEAD=`5bd7bd48`，工作区有大量未提交改动（含 NX-G1/G2/G3、NX-A1 附件、NX-E1 runs），**未部署**。本文凡引用未提交能力处均显式标注。
> **硬约束**：fail-closed。无数据源的能力一律显示"未建立"，禁止用演示数据冒充真实状态。

---

## 0. 结论先行

盘点后有 **9 个界面/界面组** 需要建设或改造。其中 **3 个是 P0**：

| 优先级 | 界面 | 理由 |
|---|---|---|
| **P0** | **审批中心**（会话外独立页） | NX-G2 硬审批已在 Runtime 落地（未部署），但审批卡只内嵌在会话里；用户离开会话就找不到待办，批准入口与"批准并执行"端点已就绪却无独立可达路径 |
| **P0** | **NexusLab Console**（**会话内就地展开**） | v1.3 C4 明确「会话内只读实验详情」。目前只有会话内实验卡（`nx-repro-card`），缺 Stage/日志/指标/取消四要素，且其中 3 项**后端尚无数据源** |
| **P0** | **资料与产物库** | 附件 API（8 端点）与 artifact API 已就绪（未部署），前端只有 composer 里的 chip，**没有列表、没有状态查看、没有重试/删除入口** |
| P1 | 论文研究工作区 | 依赖 NX-R1，当前只有 Paper Search 列表 |
| P1 | Plan/Todo 面板 | 依赖 NX-H1 |
| P1 | 运行历史与执行轨迹 | 依赖 NX-E4 |
| P2 | 能力健康看板、Artifact 详情页、课程实验 Lab 补全 | 见 §2.3 |

> **v1.1 撤回**：~~S3「NexusLab 控制台 · 作业列表」~~ —— 见文首变更说明。Console 的入口改为**会话内的实验卡**，
> 不做独立路由。跨会话可回溯属 NX-E4 运行历史（S8）范畴，不是作业列表页。

**头号信息架构问题**：产品里已存在 `/app/lab`（课程实验，Judge0、课程内、学生编程实验），与 NexusLab（Repro Worker、课程外、论文复现）**名字撞车但领域完全不同**。必须先做区分，否则用户无法形成正确心智模型。处理方案见 §3.2。

---

## 1. 现状盘点（代码事实，逐条核对过）

### 1.1 已有界面

| 路径 | 文件 | 规模 | 实测状态 |
|---|---|---|---|
| `/app/nexus` | `pages/nexus/NexusPage.vue` | **5260 行** | 会话工作区。三栏（左会话栏 / 中央聊天 / 右 48px 图标轨 + 340px overlay 抽屉）。已含：复现实验卡 `nx-repro-*`、审批确认面板 `nx-repro-confirm-pane`、日志流 `nx-log-*`、附件 chip `nx-attach-*`、产物卡 `nx-artifact-*`、能力行 `nx-cap-*`、信息源 `nx-src-*` |
| `/app/lab/hall` | `pages/lab/LabHallPage.vue` | 118 行 | **课程实验**，Judge0 沙箱（`getSandboxHealth`/`getSandboxLanguages`）、按课程取目录。与 NexusLab 无关 |
| `/app/lab/course-tasks` | `LabCourseTasksPage.vue` | 62 行 | stub |
| `/app/lab/my-experiments` | `LabMyExperimentsPage.vue` | **30 行** | stub |
| `/app/lab/records` | `LabRecordsPage.vue` | **31 行** | stub |

### 1.2 API 层已封装但界面未接（实测调用次数）

| API（`frontend/src/api/nexus.js`） | 在 NexusPage 中的调用次数 | 缺口 |
|---|---|---|
| `decideNexusApproval` | 2（导入 + 1 处） | ✅ 已接 |
| `executeApprovedRepro` | 2 | ✅ 已接 |
| `uploadNexusAttachment` | 2 | ✅ 已接（composer chip） |
| `deleteNexusAttachment` | 2 | ✅ 已接 |
| `listNexusRuns` | 2 | ⚠️ 仅一处调用，无独立展示 |
| **`getNexusApproval`** | **0** | ❌ **未接**：无审批状态轮询，批准/过期/冲突态在 UI 上无来源 |
| **`listNexusAttachments`** | **0** | ❌ **未接**：无附件列表，上传后无法回看、无法看解析状态、无法重试 |

### 1.3 后端可用数据（已核实字段）

**复现作业** `GET /api/v1/nexus/repro/jobs/{job_id}`（`_trim_job_record`）：
```
job_id, status, preset_id, repo_url, requested_license, license_checks, seed_used,
submitted_at, started_at, finished_at, code, detail, artifacts[]
steps_result[ ≤10 ]: { command(≤160字符), exit_code, timed_out, duration_s, log_tail(末 300 字符) }
```
> **⚠️ 已过时（2026-09-07）**：NX-E2/E3 已上线验收——`stage_events`（6 阶段真实边界）、
> `current_step`、`live_log_tail`（2000 字符环形）、`steps_result[].log_tail`（2000）、cancel 端点均已存在
> （`nexus_proxy.py:502`）。上方"关键缺口"结论不再成立，现行缺口见设计板 v3 Board C：GAP-1 全量日志、
> GAP-2 run 列表、GAP-3 指标时序、GAP-4 结构化 config。

**审批** `GET /api/v1/nexus/approvals/{id}`（`_public_approval`）：
```
approval_id, status, preset_id, repo_url, repo_license, plan_hash,
budget: { estimated_minutes, max_steps, cpu_friendly }, expires_at, job_id
```
错误码：`APPROVAL_NOT_FOUND`(404，合并"不存在/他人/重启丢失")、`FORBIDDEN`(403)、`EXPIRED`(409)、`STATE_CONFLICT`(409)、`BAD_DECISION`(422)。

**附件** `GET /api/v1/nexus/attachments`（`_attachment_public`）：
```
attachment_id, filename, ext, mime, size_bytes, sha256, session_id,
status, error_code, error_detail, stats, created_at, updated_at, expires_at, download_path
```
白名单 9 格式：`pdf, docx, jpg, jpeg, png, xlsx, pptx, ppt, doc`。
状态机：`uploading → queued → parsing → ready | partial | failed`，另有 `expired / deleted`。不可用态（failed/expired/deleted）返回 422。

### 1.4 设计系统组件（`frontend/src/app/ui/`）

已有：`SfxButton` `SfxBadge` `SfxCapabilityTag` `SfxDrawer` `SfxEmpty` `SfxError` `SfxField` `SfxLocalRail` `SfxSkeleton`

**缺，需要补**（§5.3 详细规格）：`SfxStatusPill` `SfxStepBar` `SfxLogView` `SfxMetricRow` `SfxConfirmDialog` `SfxPollingPanel` `SfxFileCard` `SfxDiffRow`

### 1.5 与设计指南的既有偏差（必须先定性，不是缺陷但需决策）

| 项 | `design.md` §3.3 规定 | 代码现值 | 建议 |
|---|---|---|---|
| Local Rail 宽 | 232px（收起 56px）——**已过时** | `tokens.css:121` `--rail-width: **280px**`；`--nexus-rail-width: **264px**` | 三处不一致。Nexus 保持 264px；`design.md` 更新为 280px。见 §8 Q2 |
| 详情抽屉宽 | 420 / 480 / 640px | 340px | 340px 是 overlay 抽屉（覆盖主区），与挤压式抽屉不同性质，**不算违规**，但要在文档里写明这是第三类 |
| 响应式 | 断点 1250px / 760px | **NexusPage.vue 零 media query** | 必须补，见 §5.4 |

---

## 2. 界面清单

### 2.1 目标用户

| 代号 | 角色 | 主要诉求 | 权限约束 |
|---|---|---|---|
| **U1 学生** | 选课学生 | 课程外通用问答、资料整理、读论文、看复现结论 | 需 `platform.nexus.use`；绑定课程不提升权限 |
| **U2 教师 / 研究者** | 任课教师、科研人员 | 论文复现、实验验证、生成可引用报告、管理资料 | 同上；NexusLab 属 Research 模式 |
| **U3 平台管理员** | 运维 / 管理者 | 依赖健康、配额、审计 | 独立于 Nexus；本文只做接口预留，不排期 |

### 2.2 建设清单

| # | 界面 | 主用户 | 核心任务 | 典型场景 | 状态 | 优先级 |
|---|---|---|---|---|---|---|
| **S1** | **Nexus 会话工作区** | U1/U2 | 提问题、看回答、切模式、绑课程、发起复现 | "帮我总结这篇论文的方法" → 得到带引用的回答 + 可选复现 | 已有，需**瘦身重构** | P0 |
| **S2** | **审批中心** | U2 | 查看/批准/拒绝复现提案，查看已批准作业 | 关掉浏览器第二天回来，还有 1 条待批准的复现 | **待建** | **P0** |
| **S3** | **NexusLab 控制台 · 列表** | U2 | 跨会话查看我提交过的所有复现作业及终态 | "上周跑的那个 nanoGPT 结果是多少" | **待建** | **P0** |
| ~~S3~~ | ~~NexusLab 作业列表~~ | — | — | — | **v1.1 撤回**（设计无此页，后端无 list API） | — |
| **S4** | **NexusLab Console（会话内就地展开）** | U2 | 看 Stage/命令/耗时/退出码/日志尾/指标/报告，取消 | 复现跑到一半想看进度、想取消 | **待建**（部分数据源缺失） | **P0** |
| **S5** | **资料与产物库** | U1/U2 | 管理会话附件生命周期、下载产物 | 上传的 PDF 解析到哪一步了？失败了能不能重试 | **待建** | **P0** |
| **S6** | **论文研究工作区** | U2 | Research Question → 候选 → 全文 → 证据 → 比较 → Citation | 围绕一个问题系统读 5 篇论文 | 待建，依赖 NX-R1 | P1 |
| **S7** | **Plan / Todo 面板** | U1/U2 | 看智能体的计划与实际执行进度，取消/恢复 | 长任务跑了一半，想知道还剩几步 | 待建，依赖 NX-H1 | P1 |
| **S8** | **运行历史与执行轨迹** | U2 | 跨会话回溯某次运行的完整事件 | 换设备后想看昨天那次运行的工具调用 | 待建，依赖 NX-E4 | P1 |
| **S9** | **能力健康看板** | U2/U3 | 看各能力 ready/degraded/unknown 及检查时间 | "为什么 CS 知识库搜不出来" | 待建（依赖 NX-G3 动态健康） | P2 |
| **S10** | **课程实验 Lab 补全** | U1 | 我的实验、实验记录 | 学生查看自己做过的课程编程实验 | 已是 stub（30/31 行） | P2 |

### 2.3 明确不做的（避免范围蔓延）

- Subagent / Workspace 界面 —— **TARGET**，门槛未到位
- DOCX / PPTX **输出**界面 —— **TARGET**（输入解析属 S5）
- 模型选择器 —— v1.3 §D 列为 OPTIONAL，已有"只读引擎标识"替代
- Personal Context —— OPTIONAL
- 任意 GitHub 仓库 + 自定义命令的执行界面 —— **安全红线**，v1.3 B4 明确禁止

---

## 3. 信息架构

### 3.1 设计原则

1. **单一入口不破**：v1.3 要求"前端新功能收敛为单一 Nexus 入口"。因此 Nexus 内部用**二级导航**，不在一级导航里新增一堆 Nexus 项。
2. **深链优先**：任何会话内的对象（审批、作业、附件）都必须有可分享的 URL。用户从通知/书签回来不能靠"翻聊天记录"。
3. **会话内轻量、会话外完整**：会话里只给摘要卡（一屏内能判断），点进去才是完整控制面。

### 3.2 「Lab」命名冲突的处理（**需决策，见 §8 Q1**）

**问题**：`/app/lab` 是课程实验（Judge0，课程内），NexusLab 是论文复现（Repro Worker，课程外）。同名不同域。

**建议方案（默认采纳）**：

| 层 | 现状 | 改为 |
|---|---|---|
| 一级导航文案 | 「实验室」 | **「课程实验」** —— 只改显示文案，不动路由，零风险 |
| Nexus 内 | 无 | **「NexusLab」** —— 二级导航项，路径 `/app/nexus/labs` |
| 产品文案 | 混用 "lab / 实验 / 复现" | 统一：**课程实验** = Judge0 编程实验；**复现 / Reproduction** = NexusLab；禁用裸词「实验」指代复现 |

> 我不建议把 `/app/lab` 路由改名（`lab/` 有 4 个子路由、LabLayout、api/labs.js 与 labProjectionContract.js 依赖面）。改文案的收益/风险比远好于改路由。

### 3.3 路由结构（新增部分）

```
/app/nexus                          → NexusLayout.vue （新增：二级导航外壳）
   ├─ ''                            → NexusPage.vue        （S1 会话工作区，从 5260 行瘦到 <1400）
   │                                                          └─ S4 Console 在此页内就地展开，**不占路由**
   ├─ 'approvals'                   → NexusApprovalPage.vue（S2）
   └─ 'library'                      → NexusLibraryPage.vue （S5，Tab: 附件 / 产物）
```

> **v1.1**：删除 `labs` 与 `labs/:jobId` 两条路由。Console 是会话内组件，不是页面。
> 理由：v1.3 C4「会话内只读实验详情」；且无 list API 时独立详情页的 `job_id` 只能来自会话，
> 做独立页等于把会话内组件换个 URL，**没有新增可达性，只增加路由维护成本**。

> 深链对象（单个审批、单个附件）**暂不开独立路由**，用 `?approval=xxx` 查询参数在对应列表页自动展开详情。理由：NX-G2 审批是**一次性票据**（过期即失效），给它永久 URL 会诱导"收藏待办"的错误心智。若后续审批需要长期可查（审计），再升为 `/approvals/:id`。

### 3.4 页面区域划分（Nexus 二级外壳）

```
┌──────────────────────────────────────────────────────────────┐
│ 一级导航 PrimaryNav（56px，复用）                                │
├────────┬─────────────────────────────────────────────────────┤
│ Nexus  │  页面主体（随路由切换）                                 │
│ 二级    │                                                      │
│ 导航    │  S1 会话：左 rail 264 │ 中央聊天 │ 右 48+340 抽屉      │
│ 200px   │  S3/S4/S5：标准内容区（max-width 1200，居中）           │
│        │                                                      │
│ · 会话  │                                                      │
│ · 审批③│                                                      │
│ · 复现②│                                                      │
│ · 资料④│                                                      │
└────────┴─────────────────────────────────────────────────────┘
```

二级导航项带**真实计数徽标**（不是装饰）：审批=待我处理数、复现=运行中作业数、资料=解析中/失败数。计数来自服务端，取不到时**显示 `–` 而不是 0**（fail-closed）。

### 3.5 跳转关系

| 从 | 到 | 触发 | 返回 |
|---|---|---|---|
| S1 会话 | S2 审批 | 点审批卡「查看详情」/ 导航「审批」 | 浏览器后退 + 面包屑 |
| S1 会话 | S4 Console | 点实验卡展开箭头 | **原地展开，不跳转**（会话内组件） |
| S1 会话 | S5 资料库 | 点附件 chip「管理资料」 | 后退 |
| S2 审批 | S1 会话 + S4 | 批准后「查看执行」 | 跳回发起该审批的会话，**自动展开对应 Console** |
| S4 Console | S5 资料库 | 点报告/产物下载 | 新标签页，Console 保持展开 |
| 任意 | S1 会话 | 导航「会话」 | 恢复上次会话 |

> 跨页返回必须保留列表状态（筛选/滚动）。实现：列表页状态写入 `sessionStorage`，返回时恢复。
> Console 展开态按 `job_id` 记在 `sessionStorage`，从审批页跳回会话时据此自动展开。

---

## 4. 各界面详设

### 4.0 三态统一模型（全界面共用，后面不再重复）

任何异步区域必须实现全部四态，**禁止只做成功态**：

| 态 | 触发条件 | 视觉 | 文案基准 |
|---|---|---|---|
| **加载** | 首次请求进行中 | `SfxSkeleton`，形状贴合真实内容（不是整屏转圈） | 无文案，或「正在读取…」 |
| **空** | 成功返回但无数据 | `SfxEmpty` + 图标 + 主文案 + 次文案 + **1 个主行动** | 「还没有{对象}」+「{怎么做才会有}」 |
| **异常** | 4xx/5xx/网络失败 | `SfxError` + **错误码** + 人话解释 + 重试 | 显示真实错误码，如 `REPRO_WORKER_UNAVAILABLE` |
| **数据** | 成功且有数据 | 正常渲染 | — |

外加两个 Nexus 特有的必做状态（v1.3 A4 硬性要求）：

| 态 | 含义 | 视觉 |
|---|---|---|
| **未知 unknown** | 健康检查失败/过期/从未探测 | 灰胶囊「未知」+ 上次检查时间。**禁止沿用旧的成功态** |
| **待批准 pending_approval** | 需要用户批准才能执行 | 琥珀胶囊「等待确认」+ 倒计时。**禁止显示"执行中"或"已开始"** |

### 4.1 S1  Nexus 会话工作区（重构，非重写）

**目标用户**：U1/U2　**核心任务**：提问题、看回答、发起复现

**已有组件（保留，不要重写）**：三栏骨架、模式卡 `nx-mc-*`、能力行 `nx-cap-*`、信息源 `nx-src-*`、附件 chip `nx-attach-*`、产物卡 `nx-artifact-*`、日志流 `nx-log-*`、实验卡 `nx-repro-card`、审批确认面板 `nx-repro-confirm-pane`、图标轨 + overlay 抽屉 `nx-detail-*`。

**关键组件**：Composer、TurnList（含 Markdown/LaTeX 渲染）、ProcessSummary（工具过程折叠行）、ReproCard、ApprovalPane、RightDrawer（上下文/执行轨迹/信息源）

**数据要素**：`session_id`、`mode`、`course_id`（绑定，非授权）、turn 列表、tool_call/tool_result 投影、sources、artifacts、attachments、approval_id

**主要交互流程**：
1. 输入 → 前端在发请求**前**校验 mode（General 不得带 Paper/NexusLab 工具）→ SSE `token`/`tool_call`/`tool_result`/`done`
2. 工具过程默认折叠为一行摘要；失败的步骤折叠行转琥珀（已实现 `is-failed`）
3. 复现提案到达 → 渲染审批面板（**不显示"实验开始"**）→ 用户批准 → `decideNexusApproval` → `executeApprovedRepro` → 轮询 job
4. 绑定课程仅影响检索范围，**不提升权限**（逐次 Course Access 校验）

**重构要点**：把审批、附件、作业轮询三块抽成 composable（§6.2），目标是 5260 → <1400 行。**不动视觉与交互**，纯结构拆分。

**状态覆盖**：
- 空：启动页（模式预设卡 + 课程引导条），已实现
- 加载：SSE 首 token 前的思考指示
- 异常：SSE 断连 → 显示真实失败，**不停在假进度**（v3.0 §4 要求）
- 未知：能力状态依赖 health 返回 unknown 时显示「未知 · 上次检查 {时间}」

---

### 4.2 S2 审批中心（新建，P0）

**目标用户**：U2　**核心任务**：查看并处理待批准的执行提案

**为什么必须独立成页**：审批是一次性票据，绑 `expires_at`。用户关掉浏览器后，会话里的审批卡**可能已过期**，但用户无从得知。会话内卡片无法回答"我还有几条没处理"。

**关键组件**：
- `ApprovalCard`：preset 名 / repo（含 License）/ **plan_hash 短码** / 预算三元组 / **倒计时** / 双按钮
- 分组：待处理（默认展开）、已批准、已拒绝、已过期（默认折叠）
- 空/异常态按 §4.0

**数据要素**（来自 `_public_approval`，全部已有）：
```
approval_id, status, preset_id, repo_url, repo_license,
plan_hash, budget{estimated_minutes, max_steps, cpu_friendly}, expires_at, job_id
```

**主要交互流程**：
```
进入页面 → 列表加载（待处理优先）
  ├─ 点「批准」 → 二次确认（design.md §9.2）→ decideNexusApproval('approved')
  │                ├─ 成功 → 卡片转「已批准」→ 显示「执行复现」按钮
  │                ├─ 409 EXPIRED → 卡片转「已过期」+「请让 Nexus 重新提案」
  │                ├─ 409 STATE_CONFLICT → 刷新为服务端真实状态（**不猜**）
  │                └─ 403 FORBIDDEN → 明示「无权处理他人审批」
  └─ 点「执行复现」→ executeApprovedRepro（幂等，重试返回原 job）→ 跳转 S4
```

**必须遵守**：
- 批准接口**重新鉴权**，不能因为"列表里看得见"就认为可操作
- 票据**一次性**：执行按钮在已消耗后必须禁用，避免重复提交（幂等是后端保证，UI 是第二道防线）
- 计划/预算/命令变化 → 批准失效，UI 必须提示"需重新提案"，**不得复用旧批准**

**状态覆盖**：
- 空：「还没有待处理的执行提案」+ 次文案「当 Nexus 需要运行复现实验时，会先在这里征求你的同意」
- 加载：`SfxSkeleton` 卡片 ×2
- 异常：
  - 404 `APPROVAL_NOT_FOUND` → **合并语义**（不存在/他人/重启丢失）→ 文案「这条审批已不可恢复，请让 Nexus 重新提案」，**不得**提示"你可能没有权限"（避免泄露归属）
  - 网络失败 → `SfxError` + 重试
- 未知：轮询失败超过 N 次 → 卡片挂「状态可能已过期，点击刷新」而非继续显示旧状态

---

### 4.3 ~~S3 NexusLab 控制台 · 作业列表~~（**v1.1 撤回**）

**撤回理由**：v1.3 C4 原文为「**会话内**只读实验详情」——设计上就没有独立的作业列表页。
后端也没有 list API（`nexus_repro_job_service` 只有按 `job_id` 单查的 `_owned_job_or_404`）。

**这是我 v1.0 的越权加入**：我把"数据源缺口"当成了"设计缺口"，倒推出一个设计里不存在的页面。
正确做法是照 v1.3 C4 把 Console 做在会话内，而不是为了让页面存在去申请新 API。

**跨会话可回溯**仍然需要，但归 **NX-E4 / S8 运行历史**（v1.3 C5，事件与游标），**不是作业列表页**。
两者区别：S8 是「这次会话里发生过什么」的时间线；作业列表是「我所有作业的经营看板」——后者设计里没有。

---

---

### 4.4 S4 NexusLab 实验工作台（P0，**v1.2：主舞台形态**）

**目标用户**：U2　**核心任务**：盯日志、看阶段、看指标、看产物、调参重跑（经审批）、取消

**形态（v1.2 定，用户拍板 2026-09-07）**：**实验工作台占据主舞台（≥55% 宽），会话流里的实验卡降为一行「引用条」**。

- 依据：真实复现工作流调研——复现是「配置 → 跑 → 盯日志/loss → 改 → 再跑 → 对比」的**多 run 循环**，
  日志与命令需要主舞台级宽度；挤在会话右栏里 COMMAND/DURATION 被截断，不符合工具定位
- 宽屏（≥1100px）：左会话轨 264px + 对话列（24–32%）+ 工作台（≥55%）
- 窄屏（<1100px）：主区二选一 tab（对话 | 实验台），图标轨入口带运行徽标
- 引用条：44px 一行（状态点 + 名称 + 当前步骤/时长 + 「打开工作台」），点击切换主舞台，**不跳路由**
- 会话内既有的就地展开 Console（NX-E2E3 批次按 v1 设计板交付）改造为引用条；展开态逻辑迁入工作台组件
- 组件落点：`components/nexus/ExperimentWorkspace.vue`（主舞台）+ `ReproReferenceBar.vue`（引用条）

**关键组件**：
- `ExperimentStageBar`：Preparing → Building → Running → Metric → Verifying → Completed（失败/超时/取消为独立终态）
- `ExperimentStepList`：命令 / 退出码 / 耗时（**只读**，无命令编辑、无 stdin、无交互终端）
- `LogView`：最近 20 行（可调 10–30），纯文本转义，**服务端已脱敏/过滤控制符**
- `MetricRow`：真实指标 + 容差 + 来源
- `ReportPanel`：确定性判定结论
- `CancelButton`：独立 job cancel（**当前后端无 API → 禁用并标注**）

**数据要素**：`status`、`steps_result[]{command, exit_code, timed_out, duration_s, log_tail}`、`seed_used`、`requested_license`、`license_checks`、`artifacts[]`、报告

**主要交互流程**：
```
会话中出现复现提案 → 审批通过 → executeApprovedRepro 返回 job_id
  → 渲染实验卡（收起）→ 用户展开 → 拉 job + 报告
      ├─ 运行中：2–5s 轮询 → 追加新日志到 LogView（不整块重绘）
      ├─ 点「取消」→ 二次确认 → cancel API（待后端）→ cancelling → 回收确认后 cancelled
      ├─ 点「下载报告」→ artifact 下载（新标签页）
      └─ 终态：停止轮询，展示完整结果
```

**⚠️ 本表已过时（2026-09-07）**：NX-E2/E3 已上线，Stage/live_log_tail/Cancel 均有真数据（见文首 v1.2 变更）。
现行缺口 = GAP-1 全量日志回看/下载、GAP-2 我的 run 列表（工作台 run 切换器数据源，**不是**作业列表页）、
GAP-3 指标时序、GAP-4 结构化 config；Worker 重启对账属 NX-E4。下表仅作历史留档。

| v1.3 C4 要求的要素 | 当前数据源 | 处理 |
|---|---|---|
| Stage（6 阶段） | ❌ 无 | **首版不显示 Stage 进度条**，只显示终态状态。等 NX-E2 |
| Command label | ⚠️ 有 `command`（截断 160 字符） | 显示，截断处加「…（已截断）」提示 |
| Elapsed | ⚠️ 可由 `started_at`/`finished_at` 推算 | 显示，标注"服务端时间戳" |
| Exit code | ✅ `exit_code` | 显示；运行中显示 `—`（**不是 0**） |
| 日志尾 20 行 | ⚠️ `log_tail` 末 300 字符，且**只到步骤级** | 显示，明确标注"仅最近 300 字符"。等 NX-E2 增量日志 |
| Metric | ❌ 无（在报告里） | 从报告解析；无报告时显示「暂无指标」 |
| Report | ✅ 有独立端点 | 显示 |
| Cancel | ❌ **无 cancel API** | 按钮**禁用并标注"暂不支持"**，**不得**用聊天 Stop 冒充（v1.3 C4 明确禁止） |

> 这表里 4 项缺失。我建议首版就叫「**实验详情（只读）**」而不是「Console」，等 NX-E2/E3 落地再改名。**先建壳、标注缺口，比画一个跑不通的 Console 强。**

**状态覆盖**：
- 空：不存在该状态（详情页必有 jobId）
- 加载：Stage 区骨架 + 日志区骨架
- 异常：
  - 404 → 「作业不存在或不属于你」（合并语义，防枚举）
  - 503 `REPRO_WORKER_UNAVAILABLE` → 「复现服务不可用」+ 保留最后一次已知状态但**标注"可能已过期"**
  - 断线 → 状态转「未知」，**不是"失败"**
- 取消竞态：取消请求发出后作业自然完成 → **保持真实终态**（completed），不强行改成 cancelled

---

### 4.5 S5 资料与产物库（新建，P0）

**目标用户**：U1/U2　**核心任务**：管理会话附件的完整生命周期

**关键组件**：
- Tab：附件 / 产物（Artifact）
- `FileCard`：文件名 + 格式图标 + 大小 + **状态胶囊** + 进度（解析中）+ 操作（重试/移除/下载）
- 上传区：拖拽 + 点击，白名单 9 格式
- 筛选：按状态（就绪/解析中/失败）、按会话

**数据要素**（附件，全部已有）：
```
attachment_id, filename, ext, mime, size_bytes, sha256, session_id,
status, error_code, error_detail, stats, created_at, updated_at, expires_at, download_path
```

**状态机与呈现**（严格对应后端）：
```
uploading → 进度条 + 「上传中」
queued    → 「排队中」
parsing   → 「解析中」+ 不确定进度用不确定动画
ready     → 绿胶囊「可用」+ 页数/页数统计（stats）
partial   → 琥珀胶囊「部分可用」+ 说明哪些部分失败
failed    → 红胶囊「失败」+ error_code + 「重试」「移除」
expired   → 灰胶囊「已过期」+ 「重新上传」
deleted   → 不显示（已从列表移除）
```

**必须遵守**：
- **上传 ≠ 模型可用**：卡片必须区分"已上传"与"已解析可用"
- 图片：**视觉可用性与 OCR 状态分开**展示（v3.0 §6），不支持视觉时明确"文字降级"，**不把 OCR 冒充看图**
- 引用定位：文档显示页/段落，表格显示 sheet/cell，PPT 显示幻灯片号。**做不到就不显示，不编造**
- 长文按块，**禁止静默截断**（截断必须显式提示）
- 删除立即撤销读取；UI **不承诺**"删除文件即抹净历史"（v3.0 §6）

**主要交互流程**：上传 → 立即入列表（uploading）→ 轮询/回调更新状态 → ready 后可在会话引用 → 失败可重试 → 可移除

**状态覆盖**：
- 空（附件）：「还没有上传资料」+「支持 PDF / Word / 图片 / Excel / PPT 等 9 种格式」+ 上传按钮
- 空（产物）：「还没有生成产物」+「Nexus 生成的报告与文件会出现在这里」
- 加载：骨架卡片 ×6
- 异常：
  - 配额超限 → 明示具体限制。**已实现**：单文件 `MAX_FILE_BYTES = 20 MiB`、用户合计 `MAX_USER_ACTIVE_BYTES = 50 MiB`（`nexus_attachment_service.py:65-66`）。
    **未实现**：单次文件数上限（v1.3 C2 只是"首版建议"，后端无此校验）——因此 UI **不要**宣称"最多 5 个文件"
  - 格式不在白名单 → 在**选择文件时**就拦截，并显示允许的格式列表
  - 解析超时 → `failed` + 可重试
  - 不可用态（failed/expired）被引用 → 422，提示"该资料不可用，请重新上传"

---

### 4.6 S6 论文研究工作区（P1，依赖 NX-R1）

**目标用户**：U2　**核心任务**：围绕一个研究问题系统性地找、读、比对、引用论文

**关键组件**：Research Question 输入、候选论文列表、全文可用性标记、证据卡（引用原文 + 定位）、方法比较表、Citation 输出

**数据要素**：当前只有 `search_arxiv_papers` 的**元数据**（标题/作者/摘要/arXiv ID）。**全文获取、证据定位、比较表均无数据源**（NX-R1 未完成）。

**分两期**：
- **S6a（现在可做）**：候选列表 + 元数据筛选 + 跳转外链。明确叫「**论文检索**」，**不叫「研究」**（v1.3 C1 明确要求）
- **S6b（NX-R1 后）**：加全文、证据、比较、Citation，再改名「论文研究」

**状态覆盖**：空 → 「输入一个问题开始检索」；加载 → 骨架列表；异常 → arXiv 不可用显示 `ARXIV_UNAVAILABLE`，**不得返回演示论文**

### 4.7 S7 Plan / Todo 面板（P1，依赖 NX-H1）

**关键组件**：步骤列表（计划步骤 vs 实际工具执行）、进度、取消/恢复
**必须遵守**：计划修改与实际工具状态**分开显示**；**无静态假进度**（P2 计划 §4 NX-H1 验收门）
**位置**：右栏抽屉新增一个 tab「计划」，不占常驻空间
**状态覆盖**：空 → 「简单任务不会生成计划」（v1.3 C1：简单 General 不强制 Todo）；加载 → 骨架；异常 → 事件流中断显示「计划状态未知」

### 4.8 S8 运行历史与执行轨迹（P1，依赖 NX-E4）

**关键组件**：时间线（session → turn → run → job）、事件列表（仅工具开始/结束/错误、阶段、耗时、错误码、资源引用）
**必须遵守**：**不含**完整 Prompt、模型思维、原始 Tool 参数/输出（v1.3 C5 最小化要求）；快照 + 游标事件去重；**不重新提交实验来恢复**
**状态覆盖**：空 → 「还没有运行记录」；**无关联的历史 → 显示"过程不可恢复"，不根据回答补造 Trace**（P2 计划 §5 明确要求）

### 4.9 S9 能力健康看板（P2）

展示 §A4 的 effective capability 五元交集：`manifest ∩ mode ∩ 工具面 ∩ 依赖健康 ∩ 用户/作用域策略`。
每行显示：能力名、当前状态（可用/待接入/依赖不可用/健康未知/无权限/待批准）、**上次检查时间**。
**必须遵守**：有配置 ≠ 健康；健康未知/过期显示 `unknown`，**不沿用永久 Ready**。

### 4.10 S10 课程实验 Lab 补全（P2）

三个 stub 页面（30/31/62 行）补全为真实列表 + 详情。**注意这是 Judge0 课程实验，不是 NexusLab**，UI 文案必须区分（§3.2）。

---

## 5. 统一的视觉与交互规范

### 5.1 布局与层级

| 层级 | 规格 | 来源 |
|---|---|---|
| 一级导航 | 56px，复用 `PrimaryNav` | `design.md` §3.3 |
| Nexus 二级导航 | 200px 固定，含计数徽标 | 本文新增 |
| 会话页三栏 | rail 264 / 中央 flex / 详情区 48 + overlay 340 | 现有实现 |
| 内容页（S3/S4/S5/S6） | `max-width: 1200px` 居中，左右 padding 32px | 本文新增 |
| 控制高度 | 40px（图标按钮 ≥40×40） | `design.md` §3.3 |
| 表格行高 | 44px（Compact 36px） | `design.md` §3.3 |

**滚动模型**：严格遵守 `design.md` §5.1 三层滚动容器。S3/S5 的列表区独立滚动，**不整页滚**；S4 的日志区是**唯一**可滚的子区域。

### 5.2 视觉令牌

全部取自 `frontend/src/app/styles/tokens.css`（`.sfx` scope），**禁止裸值**：

| 用途 | 令牌 |
|---|---|
| 强调 / 强调强 / 强调底 / 强调描边 | `--nexus-accent` / `-strong` / `-soft` / `-line` |
| 成功 / 警告 / 中性 | `--green-100/500/700` / `--amber-100/500/700` / `--ink-100` |
| 表面 | `--surface-page` / `--surface-panel` / `--surface-soft` / `--surface-canvas` |
| 文字 | `--text-primary` / `--text-secondary` / `--text-muted` |
| 边框 | `--border-subtle` |
| 阴影 | `--shadow-xs` / `--shadow-sm` |

**状态色语义（全站唯一映射，不得自定义）**：

| 状态 | 配色 | 胶囊文案 |
|---|---|---|
| 成功 / 可用 | `--green-100` 底 + `--green-700` 字 | 已完成 / 可用 / 已生效 |
| 警告 / 待处理 | `--amber-100` 底 + `--amber-700` 字 | 等待确认 / 部分可用 / 已连接·未生效 |
| 失败 | 红系 | 失败 / 已拒绝 |
| 未知 / 未建立 | `--ink-100` 底 | 未知 / 未建立 |
| 进行中 | `--nexus-accent-soft` 底 + `-strong` 字 | 运行中 / 解析中 |

### 5.3 组件复用策略

**强制复用（`design.md` §9.1）**：所有按钮用 `SfxButton`，**禁止原生 `<button>`**（契约测试有断言）。

**新增组件规格**（建议落 `frontend/src/app/ui/`）：

| 组件 | 用途 | 关键 props |
|---|---|---|
| `SfxStatusPill` | 状态胶囊 | `status`, `label`, `checkedAt` |
| `SfxStepBar` | 阶段进度（S4） | `stages[]`, `current`, `terminalState` |
| `SfxLogView` | 日志尾（S4） | `lines[]`, `maxLines=20`（10–30 可调）, `truncated` |
| `SfxMetricRow` | 指标 + 容差（S4） | `name`, `value`, `expected`, `tolerance`, `source` |
| `SfxConfirmDialog` | 二次确认 | `title`, `body`, `danger`, `confirmText` |
| `SfxPollingPanel` | 轮询容器（统一 2–5s、退避、错误、超时） | `fetcher`, `interval`, `stopWhen` |
| `SfxFileCard` | 文件卡（S5） | `file`, `state`, `progress`, `actions` |
| `SfxDiffRow` | A/B 指标比较（NX-P2 后） | `a`, `b`, `tolerance` |

**轮询统一由 `SfxPollingPanel` 管**：2–5s 间隔、终态自动停、断连指数退避、**页面隐藏时暂停**（`visibilitychange`）。禁止各页面各写一套 `setInterval`。

### 5.4 响应式（**当前缺口，必须补**）

`NexusPage.vue` **零 media query**，本次一并规划：

断点取值**必须复用代码里已有的**，不新造。实测 `frontend/src` 内 `@media` 宽度分布（出现次数）：`760px`(35) · `768px`(12) · `640px`(11) · `720px`(8) · `900px`/`700px`(6) · `1024px`(6) · `1100px`(3)。**代码里不存在 1250px 断点**（`design.md:1066` 那句只是说助教面板不随它隐藏）。

| 断点 | 行为 |
|---|---|
| `>1100px` | 完整三栏 + 二级导航展开 |
| `1024–1100px` | 二级导航收成图标轨（56px）；会话页左 rail 可折叠 |
| `760–1024px` | 会话页左 rail 变 overlay 抽屉（默认收起）；内容页 padding 降到 20px |
| `<760px` | 三栏塌成单栏堆叠；右详情抽屉全屏；二级导航变底部 tab（`design.md` §1068 已有先例） |

Nexus 特有的窄屏规则：右 overlay 抽屉在 `<1024px` 时占满宽度（`design.md` §3.3 的 340px 只适用于桌面）。

### 5.5 动效

遵循 `design.md` §4 令牌（`--duration-fast`、`--ease-out`）。**禁止**引入新的动画曲线。页面过渡用 `design.md` §6.2 规则，**注意 §6.4 的 `key` 滥用反模式**（会导致组件重挂载，丢了轮询状态）。

---

## 6. 前端结构与数据流方案

### 6.1 目录结构（目标）

```
frontend/src/
├── api/
│   └── nexus.js                    # 唯一 HTTP/SSE 出口（已有，保持）
├── stores/
│   └── nexus.js                    # Pinia：跨页面共享（新增）
├── composables/nexus/
│   ├── useNexusJob.js              # 作业轮询 + 状态机 + 终态判定（新增）
│   ├── useNexusApproval.js         # 审批状态 + 倒计时 + decide/execute（新增）
│   ├── useNexusAttachments.js      # 上传队列 + 状态轮询 + 重试（新增）
│   ├── useNexusSession.js          # 会话/mode/course 绑定（从 NexusPage 抽）
│   └── useNexusCapability.js       # effective capability 聚合（NX-G3 后接）
├── components/nexus/
│   ├── ExperimentConsole.vue       # S4 主体（**会话内就地展开**，非页面）
│   ├── ExperimentStageBar.vue
│   ├── ExperimentStepList.vue
│   ├── LogView.vue
│   ├── MetricRow.vue
│   ├── ReportPanel.vue
│   ├── ApprovalCard.vue
│   ├── AttachmentTray.vue
│   ├── ArtifactCard.vue
│   ├── PlanTodoPanel.vue
│   └── PaperCandidateList.vue
└── app/pages/nexus/
    ├── NexusLayout.vue             # 二级导航外壳（新增）
    ├── NexusPage.vue               # S1，目标 <1400 行；内嵌 ExperimentConsole
    ├── approvals/NexusApprovalPage.vue  # S2
    └── library/NexusLibraryPage.vue     # S5
```

> **v1.1**：删除 `labs/` 两个页面。Console 是组件不是页面。

### 6.2 数据流分层（**单向，禁止组件直接调 API**）

```
组件  ──emit──▶  composable  ──▶  api/nexus.js  ──▶  Backend/Runtime
  ▲                  │
  └──── reactive ────┘
                     │
                     ▼
              stores/nexus.js（跨页面共享：待办计数、运行中作业数）
```

**规则**：
1. 组件**只**通过 composable 取数，不直接 `import { getNexusReproJob }`
2. composable 负责：轮询、状态机、错误归一化、loading/error/empty 三态
3. store 只放**跨页面共享**的最小状态（待办计数、运行中作业集合），**不缓存列表数据**（列表数据归页面所有，避免陈旧）
4. 所有错误码映射成 `{ code, humanMessage, retryable }`，UI 只消费这个结构

### 6.3 状态归一化（关键，避免各页面各判一套）

`composables/nexus/useNexusJob.js` 输出的作业状态统一为：

```
unknown | pending_approval | queued | running | cancelling |
succeeded | failed | timed_out | cancelled | interrupted
```

后端 `status` 字符串 → 上述枚举的映射**只写一处**。缺失/不可恢复 → `unknown`，**禁止 fallback 到 `succeeded`**。

### 6.4 实施分期

| 批次 | 内容 | 依赖 | 前置阻塞 |
|---|---|---|---|
| **B0** | **S4 Console 外壳**（`ExperimentConsole.vue` + 阶段条/步骤表/日志区/指标区/报告区）+ 新增 UI 组件 | 无 | **无 · 立即开工** |
| **B1** | `NexusLayout` 外壳 + 二级导航 + 路由骨架 | 无 | 无 |
| **B2** | S2 审批中心 + `useNexusApproval`（**先补 `getNexusApproval` 轮询缺口**） | NX-G2 部署 | 无 |
| **B3** | S5 资料与产物库 + `useNexusAttachments`（**先补 `listNexusAttachments` 缺口**） | NX-A1 部署 | 无 |
| **B4** | S1 瘦身重构（5260 → <1400） | B1 | 无 |
| **B5** | Console 接真实 Stage / 增量日志 / Metric（后端 NX-E2 后填空） | NX-E2 | **是** |
| **B6** | Console 接 Cancel（后端 NX-E3 后启用） | NX-E3 | **是** |
| **B7** | S6a 论文检索 → S6b 研究、S7 Todo、S8 历史 | NX-R1/H1/E4 | **是** |

> **v1.1 重排**：Console 提到 **B0 最前**，因为它无后端阻塞（现有 job API 已够撑外壳），
> 且是用户点名要先看的。原 B4「作业列表」整批删除。
> B2/B3/B4 也在补**已存在的接线缺口**，性价比最高。
>
> **v1.2 重排（2026-09-07）**：NX-E2/E3 已由并行线交付，**B5/B6 前提消失**（阶段条/增量日志/取消均已接真实数据）；
> B0 的形态改为**主舞台工作台**（ExperimentWorkspace.vue + ReproReferenceBar.vue），
> 会话内既有就地展开 Console 改造为引用条。下方 TODO(NX-E2/E3) 注释规范**已作废**——
> 现行待后端注释前缀为 `// GAP-1/2/3/4`（见设计板 v3 Board C）。

**B0 的"外壳"定义（重要）**：先把 Console 的**结构、状态机、三态、布局**做出来，
数据源缺失的字段**留占位并显式标注「待后端 NX-E2/E3」**，不做假数据、不做假进度。
代码里每个待后端处加统一注释前缀：

```js
// TODO(NX-E2): 后端尚无 stage 字段，当前由 status 推导终态，阶段条等 NX-E2 真实事件后再接线
// TODO(NX-E3): 后端无 cancel API，按钮禁用。禁止用聊天 Stop 冒充（v1.3 C4）
```

---

## 7. 验收口径

1. 每个界面**必须**能通过 §4.0 的四态 + 两特殊态检查（人工逐态构造）
2. 契约测试 `node --test src/api/__tests__/apiContracts.test.cjs` 不新增失败
   （当前基线 **88/89**，#88 是 S3 工作线留下的过期断言，非本规划引入）
3. `npx vite build --emptyOutDir=false` 通过
4. 禁止出现：演示数据冒充真实、假进度、把 disabled 当安全边界、把配置当健康

---

## 8. 待确认问题与默认假设

| # | 问题 | 默认假设（未回复即按此执行） |
|---|---|---|
| **Q1** | `/app/lab`（课程实验）与 NexusLab 命名冲突 | 按 §3.2：只改一级导航文案为「课程实验」，路由不动；Nexus 内用「NexusLab」 |
| **Q2** | Rail 宽度三处不一致：`tokens.css:121` `--rail-width: **280px**` · `--nexus-rail-width: **264px**` · `design.md` §3.3 写 **232px**（已过时） | Nexus 保持 264px 不动；`design.md` §3.3 的 232px 应更新为 280px（**改文档不改代码**，符合 AGENTS.md §2.3「以代码为准并同步更新 design.md」） |
| ~~Q3~~ | ~~缺"列出我的复现作业"API~~ | **✅ 已澄清（2026-09-06 家良）**：设计上就没有这个页面。v1.3 C4 是「**会话内**只读实验详情」。**S3 已撤回**，不再申请 list API |
| ~~Q4~~ | ~~首版叫「实验详情（只读）」还是「Console」~~ | **✅ 已澄清（2026-09-06 家良）**：直接叫 **Console**。后端待完成处用 `TODO(NX-E2/E3)` 注释标注，不改名 |
| **Q5** | 审批是否需要长期可审计（影响是否开 `/approvals/:id` 永久路由） | 首版**不需要**审计，用查询参数展开。若有审计需求再升路由 |
| **Q6** | S5 是否要支持跨会话复用资料（附件绑定到用户而非会话） | 首版按**用户维度**展示全部，可按会话筛选（后端已支持 `session_id` 过滤） |
| **Q7** | 窄屏（<760px）Nexus 是否要完整支持？ | 首版只做到**不破版**（单栏堆叠 + 抽屉全屏），不做移动端专属交互优化 |
| **Q8** | S10 课程实验 Lab 补齐是否在本批 | 不在。与 Nexus 无关，另排；但**文案区分（Q1）必须先做** |
| **Q9** | U3 管理员视图（能力健康/配额/审计）是否本批 | 不在本批。S9 先按 U2 视角做"我能用什么"，不做管理功能 |

---

## 9. 与其他文档的边界

- 本文**只规划界面**，不改冻结设计。与 v1.3 / P2 计划冲突时，**以 v1.3 + P2 为准并回来修订本文**
- 本文不改 `design.md`。若 §5 的偏差项（Q2）确认，应同步更新 `design.md` §3.3 而非改代码
- 前端规格 v3.0 继续承载**契约与现状**；本文承载**建设规划**。实施完成后，结果回流 v3.0
