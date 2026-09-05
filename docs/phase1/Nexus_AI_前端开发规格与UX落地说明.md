# Nexus AI 前端开发规格与 UX（v3.0 Current / Roadmap）

> 2026-09-05 清理版。现行依据：[v1.3 架构](CodeNexus_转型设计与实施方案_v1.3.md)、[NX 开发计划](CodeNexus_P2开发计划.md)。视觉/滚动/按钮/过渡以根目录 design.md 为准。
> 基线 dev-liu / HEAD d2c694a0，存在未提交工作区修正，见架构 B2。本次为规格更新，未实现新增 UI 或做线上验收。

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

## 5. Approval UX（NX-G2，服务端硬门未实施）

当前抽屉只属 UI Gate；不能声称强制批准已完成。NEXT 流程：提案→ApprovalRequired 持久化/暂停→本人批准或拒绝→服务端验证→恢复执行。卡片显示 repo/preset/plan、来源/License、预算、有效期与范围。

确认调用专用批准接口提交引用，不用再次发送“我同意”的聊天文本授权。服务端绑定 owner/session/run/tool/plan hash/预算/有效期并一次性消耗；计划变化重新批准，票据不让模型生成。重复点击、网络重试、断线恢复不得重复 job；拒绝/过期/无权限给明确状态。批准前不显示实验开始。

## 6. 附件与视觉（NX-A1）

共用 PDF/DOCX/JPG/PNG/XLSX/PPTX/PPT/DOC 上传，论文只是处理 Profile。文件卡显示上传/排队/解析/可用/部分/失败/过期/删除、重试/移除和可读范围；上传不等于模型可用。

图片缩略图、视觉可用性与 OCR 状态分开；视觉模型直传优先，无需等 OCR，不支持视觉时明确辅助模型/文字降级。文档引用页/slide/段落，Excel 引用 sheet/cell；长文按块，禁止静默截断。前端传 attachment_ids，由服务端校验 owner/session/retention；私有对象，不自动入课程 KB/LearningEvidence/Graph。删除上下文保留由服务端处理，UI 不承诺只删对象即抹净历史。

## 7. Experiment Console（NX-E2 / E3）

CURRENT 已有命令步骤、退出码、耗时、指标和报告；主要终态步骤结果，不是连续实时阶段/日志。NEXT 沿会话实验卡展开只读详情：

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

NX-H1：简单 General 不强制 Todo，复杂 General 按需，Research 长任务真实计划事件和修改/取消/恢复。NX-R1：候选、全文可用性、证据/比较/Citation 可见；当前列表只称 Paper Search。

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
