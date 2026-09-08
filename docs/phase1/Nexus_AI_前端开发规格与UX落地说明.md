# Nexus AI 前端开发规格与 UX（v3.1 Current / Roadmap）

> 现行依据：[v1.3 架构](CodeNexus_转型设计与实施方案_v1.3.md)、[NX 开发计划](CodeNexus_P2开发计划.md)。视觉/滚动/按钮/过渡以根目录 design.md 为准。
> 基线 dev-liu / HEAD d2c694a0，存在未提交工作区修正，见架构 B2。本次为规格更新，未实现新增 UI 或做线上验收。
>
> **v3.1 变更（2026-09-07）**：补 §12「新增功能的前端显示界面」与 §13「按钮设计体系」，
> 并更正 §11 三条已作废的启动页条目（v2 已替换模式卡与课程引导条）。
> **§12/§13 均为规格，不是实现声明**：除已标注"已接线"者外均未实现。
> 接线状态按 2026-09-07 实测（后端路由表 + `frontend/src/api/nexus.js` 封装与调用计数）。
>
> **§11 更正（启动页 v2 已落地）**：下表第 4/5/6 项**作废**——`.nx-mode-card`、
> `.nx-start-course`、启动页绿色 `.nx-tool-pill` 已随启动页 v2 删除（改为 `.nx-seg`
> 分段控件 + 右侧 `.nx-ctx` 上下文面板 + mono 工具白名单）。历史描述保留，不再作为当前规范。
> 启动页 v2 另修：模式切换抖动（建议条数 3↔4 加垂直居中导致整块平移）→ 改顶部对齐 + 锁行高。
> 依据：`2026-09-07_Nexus_启动页重设计_v2.html`。

## 1. 产品入口与规划状态

CURRENT=限定范围真实验收；NEXT=下一批必需；TARGET=最终目标但本批不做；OPTIONAL=按需。规划状态不直接决定按钮可点，运行时可用性见 §3。

`/app/nexus` 为全局 Nexus，默认 General；显式切换 Research 后增加 Paper/NexusLab，同一 Harness。绑定课程不提升权限。真实对话、Course/CS/Web、Markdown/LaTeX Artifact、preset job 结果与报告已经接线，不再标纯演示；demo 数据源单独显式标识，不计真实验收。

左栏会话、中央聊天/Composer、详情面板沿用当前布局，视觉实现遵守 design.md。附件/视觉、Todo、Paper Research、Console、服务端 Session、受控 A/B 为 NEXT；Subagent/Workspace、DOCX/PPTX 输出 TARGET；Personal Context OPTIONAL。

## 2. Mode、身份与注册工具面

前端显式传 nexus_general/nexus_research，服务端同时接受 general/research。冻结契约：missing/null→General，unknown/空串→400 INVALID_NEXUS_MODE（工作区 unknown 仍降 General，NX-G1 待修）。非法请求须在模型/SSE 前拒绝。服务端会话偏好不覆写缺省安全语义。

| Mode | 产品工具 |
| --- | --- |
| General（4） | web_search、search_course_materials、search_cs_knowledge、write_artifact |
| Research（7） | 全部 General + search_arxiv_papers、plan_reproduction、run_reproduction |

两模式内部另有 read_file 用于 StateBackend 历史，不展示为通用文件产品工具。注册不等于健康/获准执行。

HEAD 的 NexusLab manifest 仍含 General，工作区已改 Research-only；nexusAdapter 的 tools 仍旧四工具，NX-G1 要修真实消费者和全入口测试。General 不显示 Paper/NexusLab pill、Chip、执行入口；伪造 tool_call 也要 Runtime 拒绝。Base Prompt 中性，Research 只在 Profile 增加身份规则。

### 2.1 Research 专属 Ask / Auto（2026-09-07 冻结，NEXT）

**唯一能力差别：是否允许调用实验代码沙箱。** Ask不是简单问答、少步骤模式或“每个工具询问一次”；两者使用同一研究Harness、模型、上下文及非实验工具，均可自主规划、反复搜索、读论文/附件、比较综合、调用研究子任务、生成及下载各种已支持格式的文档。

| 能力 | Research · Ask | Research · Auto |
| --- | --- | --- |
| 自主多步骤研究、Todo、搜寻与补查 | 允许 | 允许 |
| 读取资料、现有实验日志/指标和分析结果 | 允许 | 允许 |
| 生成代码文本、实验方案/环境配置文件，作为文档交付 | 允许，不执行 | 允许 |
| Markdown / LaTeX / Word等文档生成与下载 | 允许 | 允许 |
| 调用实验沙箱安装依赖、写实验文件、跑代码、排错和重试 | 禁止 | 一次确认实验范围后允许 |

格式支持状态对两者相同：Ask不能因不许做实验而禁用正式文档渲染；尚未落地的Word/LaTeX工程仍标NEXT，不因本次模式设计宣称已实现。平台固定文档转换服务可使用自己的隔离渲染环境，这不属于模型可调用的实验代码沙箱；不得借文档转换接口执行任意实验脚本。

**界面：**只在Research的输入框工具栏、发送区域附近显示一枚分段选择器 `[Ask | Auto]`，中文辅助文案为“研究与写作 / 研究与实验”。它不是右上角的“研究对话/实验工作台”视图切换器，也不是工作台“询问Nexus”浮窗。General隐藏它，General既有能力不因此改变。新会话/旧会话无记录默认Ask；同一会话研究对话与询问浮窗共享选择，不能浮窗默认为Auto。

- Ask提示：“自主研究与文档输出，不运行实验。”
- Auto提示：“可在确认后自主配置、运行和修复实验。”
- 切换不清空历史、附件、Todo、研究结果或已有实验记录；不是新开另一位智能体。
- Ask收到“帮我运行”时继续可以做的准备与研究，简短说明运行需Auto，给出切换入口；不停止所有帮助，不擅自切Auto。
- 单独切Auto不等于批准某个实验。沿用已有实验确认卡，目标/范围确认一次后持续执行；Ask下确认卡的运行按钮改为“切换Auto并批准执行”，用户明确点击可合并完成切换和该次批准，不另弹第二个模式确认。
- Auto切Ask只约束切换后的新请求/新实验，已经批准并启动的run继续按原授权执行。若存在活跃run，显示“已启动实验继续运行，可在工作台取消”。不静默取消，也不把Ask请求追加为正在运行实验的新命令；用户Cancel仍可随时使用。
- Ask下可查看历史工作台、下载报告、读取已有日志以及由用户取消活跃run；禁止新启动/复跑/沙箱操作。既有run内部的授权内排错继续，不以聊天选项变化逐步重新批准。切General同样不暗中取消旧run。

**后端契约（NEXT，需同步实现）：**

```json
{"mode":"nexus_research", "research_execution_mode":"ask"}
```

新增 `research_execution_mode: ask | auto`，不要复用现有General/Research的mode，也不要混用实验任务的setup/smoke/reproduce字段。Research缺失/null归Ask，未知值400 `INVALID_RESEARCH_EXECUTION_MODE`；General不传，兼容传入合法值也不产生实验授权，未知值仍拒绝。用户明确选择可保存到服务端会话偏好，客户端恢复后显式发送；未传字段不从旧Auto偏好偷偷升级。

客户端与服务端均显示/返回本次effective模式；偏好保存失败不假称跨设备已保存，本地只能缓存。请求提交时冻结该值并用于研究图/工具注册；切换后未启动的执行提案重新核对模式，避免延迟消息在Ask页面启动实验。不能由模型工具参数修改模式，模型缓存/graph装配须区分Ask/Auto，不能修改全局工具注册导致串模式。

Ask不绑定所有会触发实验沙箱的工具，包括现有preset run、启动实验图及通过子任务间接execute；服务端启动端点/审批消费和内部调度也检查，直接调用返回403 `EXPERIMENT_EXECUTION_DISABLED`，Worker零提交。Auto仍核对本次实验批准，不把字段值当批准票据。独立活跃run继续使用启动时的Auto授权，不反复读取聊天偏好。

**验收：**General无开关；Ask能自主完成多轮研究和正式文档输出但实验调用为0；Ask伪造run/旧票据/子任务绕行被拒；Auto一次批准后缺包修复不二次审批；刷新与浮窗保持一致；Auto→Ask不启动新run、不暗中中断旧run，Cancel仍真实回收。本文只冻结规格，界面与字段尚未实现。

## 3. Manifest 与 effective capability（NX-G3）

nexusCapabilities.js 是声明，不是运行时“唯一真相源”。`effective = manifest ∩ mode ∩ actual tools ∩ health/config ∩ user/scope policy`；副作用执行还要 per-run approval。

- ready/wired/unwired 仅表接线；UI 区分可用、待接入、依赖不可用、健康未知、无权限、待批准。
- Worker URL 配置不等于健康；health 应有时间戳/TTL，失联/过期不能永久 Ready，恢复也不自动执行。
- manifest、模式菜单/tools pills、Runtime 白名单一致；执行端独立校验，不信前端按钮。
- 当前静态 helper 尚未完成此聚合，NX-G3 待改；不得写成已实现动态可用性。

## 4. 当前请求与消息历史

Backend/Runtime 已接收 mode/context，旧“字段未接收”注释归档。当前请求示例：

```json
{"message":"请检索课程内容","session_id":"session-id","mode":"nexus_general","context":{"course_id":42}}
```

课程请求范围由 Course Access 校验。attachment_ids、审批 resume、产品事件游标为 NEXT 契约，不混进现有接口示例。已有聊天 token/tool_call/tool_result/error/done 处理，具体格式以实际 client/main.py 契约验证；异常显示真实失败，不停在假进度。

消息历史仅 user/最终 assistant；工具投影缺失不代表 checkpoint 未存 ToolMessage。同设备缓存可能保留工具卡，换设备更明显丢失过程。

## 5. Approval UX（既有preset审批＋NEXT自主实验）

2026-09-07本地代码已有服务端审批决定/核销及前端批准执行调用；旧“只有UI Gate”结论不再适用于当前实现。NEXT自主实验沿用提案→本人确认→服务端核销→执行，增加§2.1的Research Ask/Auto约束。确认卡简要显示实验目标、数据/访问范围、资源与最长时间，自动安装排错包含在本次授权内。

确认调用专用批准接口提交引用，不用再次发送“我同意”的聊天文本授权。服务端绑定 owner/session/run/tool/plan hash/预算/有效期并一次性消耗；旧preset保持精确指纹；NEXT自主实验只在授权范围改变时重新批准，正常依赖/命令修复不重新批准，票据不让模型生成。重复点击、网络重试、断线恢复不得重复 job；拒绝/过期/无权限给明确状态。批准前不显示实验开始。

## 6. 附件与视觉（NX-A1）

共用 PDF/DOCX/JPG/PNG/XLSX/PPTX/PPT/DOC 上传，论文只是处理 Profile。文件卡显示上传/排队/解析/可用/部分/失败/过期/删除、重试/移除和可读范围；上传不等于模型可用。

图片缩略图、视觉可用性与 OCR 状态分开；视觉模型直传优先，无需等 OCR，不支持视觉时明确辅助模型/文字降级。文档引用页/slide/段落，Excel 引用 sheet/cell；长文按块，禁止静默截断。前端传 attachment_ids，由服务端校验 owner/session/retention；私有对象，不自动入课程 KB/LearningEvidence/Graph。删除上下文保留由服务端处理，UI 不承诺只删对象即抹净历史。

## 7. Experiment Console（NX-E2 / E3）——✅ 已上线（2026-09-06）

CURRENT 已由"终态步骤结果"升级为会话内只读 Console（设计板 2026-09-06 v1，
按设计板落地）：Stage 竖轨（真实边界事件）/Command label/Elapsed/Exit code
（运行中显示 —）/最近 20 行日志（运行中增量，服务端脱敏）/Metric/Report/
Cancel（cancelling→cancelled 状态机，回收确认才置终态）。轮询 5s（2–5s 内
合规），无 WebSocket、无 stdin、无命令编辑；无 B 环境 Verifying 如实显示
"not_applicable"。恢复路径（刷新/换设备/本地落后远端终态）拉取一次快照即
更新并自行停止。验收证据见 [NX-E2E3 记录](验收记录/NX-E2E3_验收_2026-09-06.md)。

| 字段 | 规则 |
| --- | --- |
| Stage | Preparing/Building/Running/Metric/Verifying/Completed 由真实边界触发，失败/超时/取消独立 |
| Command label | 服务端审核标签，无命令编辑/交互 stdin |
| Elapsed / Exit code | 服务端时间戳，运行 exit=null，断线标未知 |
| Log tail | 默认 20 行，限制字节，服务端脱敏/控制符过滤，前端纯文本转义 |
| Metric / Report | 真实指标/容差/来源与确定性结果；缺指标不可判定 |
| Cancel | 独立 job cancel，cancelling→回收确认→cancelled；不等于聊天 Stop |

预构建显示复用/跳过；无 B 时 Verifying 未实施/不适用，不能以 metric compare 冒充 B。Worker 增量读取先接线，再代理和 2–5 秒轮询，不要求 WebSocket/交互终端。取消须精准回收对应进程组/容器，不影响共享 Worker/他人 job。

## 8. Session / Execution History（NX-E1 / E4）

CURRENT localStorage+remote merge，mode/course/pin 未全在服务端，remote-only 工具事件为空；Worker _jobs 在内存。NEXT 服务端权威 session/turn/run/job/attachment/artifact 与 mode/course/pin/title/version；本地只缓存和设备偏好。

先拉快照、后游标事件去重，恢复原 job 轮询，不重新提交。产品事件仅工具开始/结束/错误、阶段、耗时、错误码和资源引用，不含完整 Prompt/原始 Tool 输出/思维；checkpoint 管续跑，产品事件管历史。旧无关联则显示不可恢复，不根据回答补造 Trace。

并发使用服务端 version，旧缓存不覆盖较新状态；跨设备重新检查课程/资源权限。Worker 重启需快照/实例对账，不确定显示 interrupted/unknown，不自动重跑；删除/过期覆盖事件/对象/checkpoint 的保留策略。

## 9. Harness / Paper / 复现目标投影

**NX-H1——✅ 本地开发/验证完成（2026-09-07，线上部署后待人工复验）**：
`write_todos`（已安装 TodoListMiddleware，两模式同置，简单 General 由提示词
约束不强制建计划）→ 真实 state 投影 `plan` SSE 事件/同步 plan 字段 →
折叠**计划卡**（原生三态 pending/in_progress/completed，无百分比/定时推进，
渲染于消息列尾）。恢复：`GET /nexus/plan/{session_id}`（权限门同链），
planState 状态机两条语义——流事件只接受严格更大 revision（乱序/重复忽略），
恢复读取无条件替换并重置基线（Runtime 重启计数器从 1 重来不粘死）；
服务端显式 plan:null 才清空本地；读取失败可重试。Chat Stop 不改写计划
（pending 保持 pending），继续聊天由新的真实执行更新。
[回执](验收记录/NX-H1_R1a_本地开发回执_2026-09-07.md)。

**NX-R1a 限定薄链——✅ 本地开发/验证完成（2026-09-07，同上）**：
Research-only `collect_paper_evidence`（绑定会话的上传 PDF ≤3 篇 → 证据
evidence_id/locator/excerpt/coverage）→ **证据卡**（来源为上传文件标签、
locator 缺失如实标注、abstract_only 提示补验）→ `write_research_report`
（模型只能引用登记 id，服务端渲染引用附录，伪造 → `EVIDENCE_ID_INVALID`
可修复错误，最多 1 次修正）→ Markdown Artifact 下载。搜索候选（arXiv/Web
元数据）与已读全文证据严格区分；候选无全文提示上传。**整体 Paper Research
（自动全文获取、PaperQA 选型、大规模综述）保持 NEXT**；证据登记为进程内存
属已知限制。

NX-P1/P2：论文/仓库→One Claim/计划→批准→A→冻结→B→指标/报告，明确区别 CURRENT preset。TARGET Subagent 显示真实父子任务，不放静态假卡；DOCX/PPTX 输出不能混为当前 P0。

## 10. 验收与历史附录

按 NX 验证 Mode/非法值/跨模式调用、无批准零执行、effective health/权限、八格式/图片直传、日志/取消、刷新换设备不重复 job、事件去重/删除。区分 mock、本地、线上，构建通过不替业务验收。

[前端完整历史快照](Nexus_AI_前端开发规格与UX落地说明_历史快照_2026-09-05.md)：Appendix A=原 §1–7 初始调查/旧 request/12 工具；B=原 §8 D1–D8 关闭；C=原 §12–14 UX 演进。旧 Q1–Q8 保留为当时问题，不再列“当前待讨论”；Mode、知识接入、Worker、PG 等现行决策以 v1.3 为准。旧页数/工具基数/视觉细节不自动成为当前规范。

## 11. 设计板保真度回合（纯视觉，不改契约）

线上曾反馈“部署后不如设计板好看”。核查结论：**不是缓存或漏部署**——线上 chunk（`NexusPage-DL4bS_wi.js`）可 grep 到 `nx-detail-rail` / `nx-mode-cards` / `nx-start-course` / `已生效` 等全部改版标记，代码确实上线了。真实原因是**实现相对设计板做了简化而未声明**。本回合按设计板 CSS 补齐 7 项，全部落在 `NexusPage.vue`，不改变功能组件类型（仍全部 `SfxButton` + div）：

| # | 落差 | 补齐 |
| --- | --- | --- |
| 1 | 抽屉只有标题行，无 tab 条 | 新增 `.nx-drawer-tabs`（accent 下划线 + `.nx-dt-n` 计数徽标 + `.nx-dt-dot` 未读点）；新增 `selectDetailTabInDrawer()`，抽屉内只切面板，不因重复点击收起（与图标轨行为区分） |
| 2 | 抽屉阴影/圆角偏弱 | `border-radius: 14px 0 0 14px` + `box-shadow: -12px 0 32px rgba(16,26,49,.1)` |
| 3 | 能力状态是灰块列表 | 改白卡：图标 + 名称 + `.nx-cap-hint` 说明小字 + 三色胶囊 `.nx-cap-tag`（ready 绿 / wired 琥珀 / unwired 灰） |
| 4 | 模式卡是纯文字按钮 | 加 `.nx-mc-cur`「当前」胶囊 + 32px `.nx-mc-iconbox` + `.nx-mc-titlebox`（标题 + 「可用工具 N 项」）+ 选中态 3.5% accent 底 |
| 5 | 课程引导条灰色虚线 | 改 accent 淡蓝强调条（`--nexus-accent-soft` 底 + `--nexus-accent-line` 描边）+ 幽灵按钮 |
| 6 | 工具 pill 灰色 | 启动页 `.nx-mc-tools .nx-tool-pill` 改绿，与「已生效」语义一致 |
| 7 | 左栏底部灰底大卡套两行 | 改两张独立白卡：dot/ico + 标题 + 副标题 + 常驻动作词 `.nx-dv-act`（不靠 hover 才暴露可点） |

**边界（不得反过来当缺陷报）**：设计板是固定画幅的精修示意图；真实页面有全局导航、真实长度中文文案、随视口宽度变化，**不会像素级等同**。本页无 media query，窄于约 1100px 时三栏仍按 `--nexus-rail-width` 264px / `--nexus-detail-rail` 48px 固定排布，抽屉为 overlay 覆盖主区——窄屏适配不在本回合范围，也不属 CURRENT 验收项。

---

## 12. 新增功能的前端显示界面（v3.1 增补 · 规格，非实现声明）

### 12.0 接线状态（2026-09-07 实测）

后端路由以 `backend/app/api/v1/endpoints/nexus_proxy.py` 为准；前端以 `frontend/src/api/nexus.js` 的封装与实际调用计数为准。**"已封装 0 调用"是最需要警惕的状态**：接口写好了但没有任何入口，等于功能不存在。

| 功能 | 后端 | 前端封装 | 实际调用 | 界面 |
| --- | --- | --- | --- | --- |
| 会话 runs 列表 / 恢复 | ✅ `GET /runs`（L1417） | `listNexusRuns` | 2 | ✅ 已接（会话内 Console + 工作台） |
| 运行重命名 | ✅ `PATCH /runs/{id}`（L1583） | `renameNexusRun` | 1 | ✅ **2026-09-07 已实现**（工作台头部就地编辑，§12.2） |
| 运行备注 | ✅ `GET/POST /runs/{id}/notes`（L1556/L1530） | `listNexusRunNotes` / `createNexusRunNote` | 2 | ✅ **2026-09-07 已实现**（工作台「备注」tab，§12.7） |
| preset 投影（参数白名单 / 预算 / 指标基线） | ✅ `GET /repro/presets`（L979） | `listNexusReproPresets` | 1 | ✅ **2026-09-07 已实现**（左栏「预设 · 只读 / 可改参数」，§12.8） |
| 审批待办恢复 | ✅ `GET /approvals?session_id&status`（L910） | `listNexusApprovals` | 1 | ✅ **2026-09-07 已实现**（浮窗 v2 多待办，§12.4） |
| 提案：创建 / 读取 / 改参 / 请求审批 | ✅ `/repro/proposals` 四端点（L1025/1038/1051/1068） | 已封装 4 个 | **0** | ❌ 未建（diff 渲染已就绪，参数编辑器未做） |
| 运行详情（display_title / run_number / version / 冻结配置） | ✅ `GET /runs/{id}`（L1458） | `getNexusRunDetail` | **0** | ❌ 未建（列表已带同名字段，暂不单独拉取） |
| 取消授权签发 | ✅ `POST /runs/{id}/cancel-grant`（L1489） | `requestNexusRunCancelGrant` | **0** | ❌ 未建：**没有触发源** |
| Research Ask / Auto | ❌ 未实现（§2.1 仅冻结规格） | 无 | — | ❌ 未建 |

**两条不能做的，说明原因（不是遗漏）**：

1. **cancel-grant 不接** —— 该端点是给"模型请求取消"签发一次性授权用的（LB4：模型意图本身不构成授权）。
   用户自己点取消走的是现有 `POST /repro/jobs/{job_id}/cancel`，**不需要 grant**。
   目前没有"模型请求取消"的服务端事件可达前端，接了就是假入口。
2. **Ask / Auto 不做** —— 后端 `research_execution_mode` 未实现（§2.1 仅冻结规格）。
   按 fail-closed，不允许放一个点了没用的开关。等后端字段落地再接。

**同时更正一处过期事实**：~~`nexus_runs` 无 title 字段~~ —— LB1 已加 `title / run_number / version / parent_run_id / config_snapshot / preset_display_name / paper_title`（`nexus_run_service.py:60-68`、迁移 `83-91`）。本地命名回退（`experimentName()`）只是后端字段不可得时的过渡，不是长期方案。

### 12.1 Research Ask / Auto 选择器（§2.1 的界面细化）

- **位置**：Research 模式 composer 工具栏**左侧第一个控件**，与附件按钮同排；General 整块不渲染（不是隐藏，是不存在）。
- **形态**：与右上「研究对话／实验工作台」同一分段控件语汇（`.nx-seg`），两枚 `[Ask | Auto]`，高 26px；选中项白底墨字 + 序号转 accent。辅助文案为中文，不使用英文"Ask/Auto"单独成义：`研究与写作` / `研究与实验`。
- **提示**：选中项下方一行 11px 灰字——Ask「自主研究与文档输出，不运行实验。」/ Auto「可在确认后自主配置、运行和修复实验。」
- **状态与恢复**：新会话默认 Ask；同一会话的研究对话与询问浮窗**共享同一选择**（单一状态源，不允许浮窗默认 Auto）；刷新后由服务端会话偏好恢复，偏好保存失败只本地缓存并如实提示，不假称"已跨设备保存"。
- **切换不清空**历史/附件/Todo/研究结果/已有 run；不是新开智能体。
- **Ask 收到"帮我运行"**：按钮不消失、不禁用，模型继续做可做的准备工作，并在卡片里给一枚 `切换到 Auto`  tertiary 按钮；不擅自切模式。
- **审批卡联动**：Ask 下确认卡的运行按钮文案改「**切换 Auto 并批准执行**」（一次点击完成切换＋本次批准，不弹第二个确认）。
- **Auto→Ask**：已批准并启动的 run 继续按原授权执行，卡片下方显示「已启动实验继续运行，可在工作台取消」，配一枚 `取消` danger 按钮（仍走 cancel 链）；不追加为新命令，不静默取消。

### 12.2 运行命名与重命名（NX-LB1）

- **显示名优先级**（单一函数，禁止各组件各写一份）：`title`（用户命名）→ `display_title`（服务端 `preset display_name + run_number`）→ 本地回退 `experimentName()`。旧行 `run_number=0` 由迁移回填，前端不自行补序号。
- **序号**：`run_number` 是会话内稳定标识，**前端 sorted index 只能临时显示，不能当标识**（P2 §9.2 明确）。切换器选项文案 `nanogpt 复现 · #2` 中的 `#2` 必须来自 `run_number`。
- **重命名入口**：工作台头部实验名右侧一枚 24px 图标按钮（铅笔）；点击就地变输入框，Enter 提交 / Esc 取消。
- **校验与失败态**：trim 后 1–120 字符；空串提交 = 恢复默认名（按钮文案提示"留空恢复默认名"）；非法 422 原地显示错误不关闭输入框；**409 版本冲突**显示「运行信息已被别处更新，已刷新为最新名称」并拉取最新（不覆盖用户输入前先提示）。
- **诚实提示**：重命名不改变执行 hash 或运行配置——提交区一行小字，避免用户以为改名能改实验。

### 12.3 运行列表 / 切换器（NX-LB1）

- 切换器只列**当前会话已知 runs**；后端已给 cursor/limit/next_cursor，首版不做无限滚动，超过一屏显示「加载更早的运行」。
- **计数**：会话运行计数未知时显示「数量未知」，**禁止把 unavailable 当 0**。
- **stale / observed_at**：Worker 失联的运行在切换器与头部显示「状态未知 · 观测于 HH:MM」，不用旧快照冒充当前事实；不阻塞整个列表渲染。
- **config_status unavailable**：冻结配置不可得时配置区显示「配置未记录」，不倒灌当前 preset 当历史事实。

### 12.4 提案、参数修改与审批浮窗 v2（NX-LB2）

- **待办恢复**：进入会话即拉 `GET /approvals?session_id=…&status=pending`，输入框上方浮窗展示**所有**待办；不能静默替用户选中另一个运行的审批（浮窗顶部必须写明目标运行名 + `#run_number`）。
- **浮窗内容**：目标 / 参数（改动项与父运行或上一版本**结构化 diff**，新增 / 修改 / 删除三色行）/ 环境 / 预算 / 有效期 / plan_hash 短指纹。
- **按钮组**：`批准执行`（primary）· `查看完整方案`（secondary，滚到消息流原卡）· `拒绝`（danger tertiary）。提示行「↓ 在下面输入框提出修改，改完重新确认」。
- **旧票失效**：修改提案后旧批准不可用，浮窗改为「方案已更新，需重新确认」，`批准执行` 变为 primary 但提示重新审批；后端 409 时按服务端文案显示，不复用旧按钮态。
- **指标基线**：参数改动导致不匹配已验证基线时，结果区标 `exploratory`，文案「配置已改，未建立可比较基线；以下为测量值，不代表复现通过」。**禁止沿用 1.88±0.06 判定**。
- 参数只允许白名单字段，schema 来自 `GET /repro/presets`；越界/注入在输入框提交前就地提示。

### 12.5 浮窗上下文引用（NX-LB3）

- 浮窗发送时带 `context.run_ref {run_id, step_id?}` + `client_request_id`（幂等键）；**不发送日志/退出码/指标原文**。
- 引用徽标如实写出带进去了什么：`引用 #2 · 第 4 步 · 日志末 20 行`（服务端只给 20 行就写 20，前端不补造 40）。
- 服务端返回 `observed_at / stale / truncated / actual_lines`，浮窗底部一行小字；`stale` 时加「状态未知，可能不是最新」。
- `409 SESSION_BUSY`：不重试，显示「本会话正在处理另一个请求」，保留用户输入。同一 `client_request_id` 重试返回原状态，不重复调模型。
- 展开/拖动/切视图**不发模型任务、不创建 run**；坐标只存本地。

### 12.6 Agent 操作与取消授权（NX-LB4）

- 模型要取消必须走受限 action grant：前端在用户明确点击 `取消` 后调 `POST /runs/{id}/cancel-grant`（一次性、短有效期），**不由模型参数伪造**；未获授权时模型返回"需确认"，界面显示「Nexus 请求取消运行 #2 · `[确认取消]` `[忽略]`」。
- **歧义必须澄清**：目标不明确或显式 run_id 与当前上下文冲突时，显示选择列表让用户指定；**绝不默认"最新运行"**。
- 取消失败原样映射：超时显示"未知，稍后重查"不显示成功；`cancelling` 不提前转 `cancelled`；终态调用显示"已结束，无需取消"。
- 改方案类工具只产出提案，**任何情况下不触发无审批执行**。

### 12.7 运行备注与产物（NX-LB5）

- 备注面板为工作台右侧「备注」tab：追加式（不提供编辑/删除），每条显示 author_kind（用户 / **Nexus（解释或建议，不改结果）**）+ created_at。
- 输入 ≤4000 字符，超长就地提示；`request_id` 幂等，重复提交不产生第二条。
- 产物区只列**已授权 Artifact 引用**，可下载；未收集/已过期显示「不可用」，**不把 Worker 工作目录清单当下载链接**。全量日志归档 / 指标时序 / 批量下载仍 TARGET——不足时不画曲线、不给假的"下载全部"。

### 12.8 preset 投影（前端未接）

`GET /repro/presets` 已上线但前端未封装。它是"无 preset 也能准备实验"和参数白名单的**唯一数据来源**——参数可改范围、默认值、预算上限、指标与来源、能力限制都只能来自这里，前端**禁止硬编码参数列表**。接入前，§12.4 的参数修改界面不开放。

---

## 13. 按钮设计体系（v3.1 增补）

### 13.1 变体

| 变体 | 用法 | 一屏上限 |
| --- | --- | --- |
| `primary` | 该屏**唯一的**主动作（批准执行、发送、确认取消） | 1 |
| `secondary` | 次动作与可逆操作（查看完整方案、更换、加载更早） | 2–3 |
| `tertiary` | 低强调、行内/面板内（打开工作台、切换到 Auto） | 不限但不做主行动 |
| `danger` | **仅破坏性动作**（取消运行、拒绝提案、移除附件）；红描边 + 红字，不用实心红 | 1 |
| 文字按钮 | 面板密集行（重命名、绑定课程），需 ≥44px 点击区 | — |

### 13.2 尺寸与几何

- `md` 32px（composer 主动作）/ `sm` 28px（行内、面板内）/ `xs` 24px（仅上下文面板密集行）。
- 圆角 4px、描边 1px；**不使用大圆角胶囊做主行动**（胶囊只给分段控件与状态标签，避免"控件都长得像开关"）。
- 高度固定，loading 态**保留原文案宽度**只换指示器，防止按钮跳动。

### 13.3 状态（每个按钮必须全部具备）

`default` / `hover`（背景或描边变化，不只变亮）/ `focus-visible`（2px `--color-focus`，offset 2px）/ `active` / `disabled` / `loading` / `error`（就地文案，不弹 toast 了事）/ `empty`（数据为空时按钮不出现或明确禁用）。

**禁用必须给原因**：`disabled` 一律挂 `title`，例如「Ask 模式不运行实验，切换到 Auto 后可用」「输入为空」「另一个请求正在进行」。只变灰不给原因是设计缺陷。

### 13.4 危险动作三级确认

1. **可逆**（移除附件）：直接执行 + 可撤销提示。
2. **破坏性但可重来**（取消运行）：按钮就地变「确认取消？」，5s 后自动退回；不是弹窗。
3. **不可逆 / 影响他人**：danger 按钮 + 一行后果说明 + 需要用户显式输入确认（当前产品无此类，预留）。

### 13.5 按钮不能表达的三件事（写进评审清单）

1. **按钮可见 ≠ 能力可用** —— 一切以 `effective = manifest ∩ mode ∩ tool surface ∩ health ∩ policy` 为准（§3）。
2. **按钮点击 ≠ 已授权** —— 批准按钮只提交决定，执行权在服务端票据核销（§5）。
3. **按钮禁用 ≠ 原因自明** —— 无 `title` 的禁用态一律退回。

### 13.6 新增功能按钮对照

| 位置 | 动作 | 变体/尺寸 | 备注 |
| --- | --- | --- | --- |
| 审批浮窗 | 批准执行 | primary / sm | 一屏唯一；Ask 下改文案「切换 Auto 并批准执行」 |
| 审批浮窗 | 查看完整方案 | secondary / sm | 滚动到消息流原卡 |
| 审批浮窗 | 拒绝 | danger / sm | 需二次确认（级 2） |
| 工作台头部 | 重命名 | 文字按钮 / xs | 就地编辑，Esc 取消 |
| 工作台头部 | 取消 | danger / sm | 级 2 就地确认；先签 cancel-grant |
| 工作台头部 | 询问 Nexus | tertiary / sm | 打开可拖浮窗 |
| 工作台结果区 | 分析本次结果 | primary / sm | 预填**不发送** |
| 工作台结果区 | 调整方案再运行 | secondary / sm | 走新提案 + 重新审批 |
| 浮窗确认条 | 确认取消 / 忽略 | danger + secondary / xs | 模型无 grant 时才出现 |
| 上下文面板 | 绑定课程 / 更换 | secondary / xs | — |
| 备注面板 | 添加备注 | secondary / xs | ≤4000 字符，request_id 幂等 |
| Research composer | Ask / Auto | 分段控件（非按钮） | 与视图切换器同语汇，不混用 |
