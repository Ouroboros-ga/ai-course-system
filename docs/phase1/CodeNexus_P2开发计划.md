# CodeNexus 开发计划：Current MVP → NX 必要主线

> **版本**：2026-09-05 v1.3 对齐清理版；基线 dev-liu，核查 HEAD=d2c694a0，有未提交工作区差异。
> **设计依据**：[v1.3 Current Architecture + Roadmap](CodeNexus_转型设计与实施方案_v1.3.md)；[前端规格](Nexus_AI_前端开发规格与UX落地说明.md)。
> **历史**：原文件名保留以兼容链接。M0–M5 原任务、验收和工具数量完整移至[历史快照](CodeNexus_P2开发计划_历史快照_2026-09-05.md)，不代表当前工具面或未来排期。本次为文档更新，不是功能上线。

## 1. Current / Next / Target / Optional

CURRENT=有真实验收的限定能力；NEXT=下一批必做；TARGET=最终目标、本批不交付；OPTIONAL=按需评估。CURRENT 不等于依赖实时健康，工作区修改不等于 HEAD 或部署。所有 NX 任务均待实施/验证，无日历承诺。

| 范围                                                               | 状态       | 边界                                                |
| ---------------------------------------------------------------- | -------- | ------------------------------------------------- |
| Web/Course/CS 检索、Markdown/LaTeX Artifact                         | CURRENT  | 既有 M2/M3 验收；DOCX 输入另属 NX-A1，DOCX/PPTX 输出 TARGET   |
| Tool loop、Compact、checkpoint、消息恢复                                | CURRENT  | P1/M1/M5 验收；Compact 全图触发边界保留；不是完整 Harness/跨设备产品历史 |
| nanoGPT preset、基础步骤结果/指标/报告                                      | CURRENT  | P1/M4 验收；轮询 job 与终态步骤结果，不称实时全过程 Console           |
| Legacy Research S3                                               | CURRENT  | M5 验收；活跃教学消费者、数据/迁移保留，不重做已下线迁移                    |
| 服务端执行审批                                                          | NEXT/P0  | UI gate 不算；当前 run\_reproduction 可直接提交 Worker      |
| 附件/视觉、Todo、Paper Research、SandboxProvider、受控 A/B、Console、Session | NEXT     | 下表独立验收，不一次翻转全线 ready                              |
| Subagent/Workspace、广泛任意论文/仓库、DOCX/PPTX 输出                        | TARGET   | 门槛到位后另排批次                                         |
| Personal Context、GPU/多云、额外模型选择器                                  | OPTIONAL | 按需评估；图片视觉模型配置仍是 NX-A1 必需项                         |

## 2. Current registered / effective tool surface

| 层次               | 工具                                                                          |
| ---------------- | --------------------------------------------------------------------------- |
| General 产品工具（4）  | web\_search、search\_course\_materials、search\_cs\_knowledge、write\_artifact |
| Research 产品工具（7） | 全部 General + search\_arxiv\_papers、plan\_reproduction、run\_reproduction     |
| 两模式内部 Harness    | read\_file（StateBackend 历史读回，不是宿主通用文件）                                      |

代码源为 `nexus/src/nexus/tools/__init__.py` 与 `agent.py`，前端四工具映射已过时。注册不等于可执行：`effective = manifest ∩ mode ∩ tool surface ∩ health/config ∩ user/scope policy`，提交另需 approval。当前聚合与强审批未完成。

## 3. 首批 P0：NX-G1–G3

| 任务                          | 当前差距                                                                                          | 改动入口                                                                                         | 验收                                                                                                                                   |
| --------------------------- | --------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| NX-G1 Mode/身份/模式工具面         | HEAD 缺失/未知→Research；工作区已回落 General、Base 中性、NexusLab Research-only，但 unknown 未 400，前端 tools 仍旧 | agent.py/main.py、nexus\_proxy.py、nexusAdapter.js/nexusCapabilities.js/NexusPage.vue、相关模式契约测试 | missing/null→General；别名正确；unknown/空串→400 INVALID\_NEXUS\_MODE，模型/SSE 前拒绝；非法类型拒绝；General 不显示/不能调用 Paper/NexusLab；4/7 工具映射一致；保留中性 Base |
| NX-G2 Runtime Hard Approval | UI 确认不阻断模型；只有 preset/Worker 校验，提交后 best-effort 归属                                             | tools/reproduction.py、request\_scope.py、Nexus 持久化；Backend Nexus 代理/内部端点/服务；前端审批状态            | 提案→ApprovalRequired→暂停→本人批准→服务端验证→恢复；绑定 user/session/run/tool/plan hash/预算/有效期；无批准 Worker 零提交；归属先于执行；一次性、幂等、防重复 job                  |
| NX-G3 Effective capability  | 静态 ready 为主；Worker URL 存在不等于健康                                                                | Runtime health/代理、nexusCapabilities/nexusAdapter/NexusPage                                   | manifest+mode+注册面+依赖 TTL/health+权限计算；掉线/过期 unknown/degraded；General 永远无 NexusLab；执行端另验证策略和审批                                         |

强审批优先评估可持久化 interrupt/permission 或等价一次性票据；不能只增加模型可填的 approved=true。服务端批准取登录身份，票据不交模型自由生成；绑定计划/预算变化即失效，任何聊天/手工/内部/恢复入口共用检查。依赖 NX-E1 的最小 owner/run/job 切片，可先交付此基础，不等完整 Session。

批准/提交/返回网络超时需幂等键与对账，重试返回原 job；拒绝/过期/跨用户/篡改/重复消耗不得执行。硬门完成前不扩大执行面，强审批对外承诺保持未完成；需要此承诺的入口先关闭提交或先完成 NX-G2。

## 4. 必要能力交付

| 任务                       | 状态     | 交付与依赖                                                                                            | 验收门                                                                           |
| ------------------------ | ------ | ------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------- |
| NX-A1 附件/视觉              | NEXT   | General/Research 八格式共用入口；复用对象存储/ParserProvider/OCR/LibreOffice，补 XLSX；先生命周期/PDF链再其他格式与论文 Profile | 八格式各一合成样例；图片直传不强制 OCR、无视觉诚实降级；页/slide/cell/段落引用；scope/限额/删除/过期/错误明确；不进课程知识域   |
| NX-H1 Plan/Todo          | NEXT   | 显式 Todo middleware；简单 General 不强制，复杂 General 按需，Research 长任务启用；消费产品事件                            | 计划修改、实际工具状态分开；checkpoint/事件/UI 取消恢复一致，无静态假进度                                  |
| NX-R1 Paper Research     | NEXT   | NX-A1 论文全文与 NX-H1；PaperQA/同类薄 Adapter 或隔离 sidecar                                                | 问题→候选→全文→证据→比较→综合→Citation；全文不可得诚实降级，no-go 换组件不删目标                            |
| NX-S1 SandboxProvider    | NEXT   | 现有 Worker 后续适配；SWE-ReX/同类执行层、repo2docker 构建层；统一创建/执行/状态/取消/清理语义                                  | 隔离、网络、凭据、挂载、预算、取消和清理；同 preset 对比；不因安装组件自动获得任意仓库/A-B 安全声明                      |
| NX-P1 Paper-to-plan      | NEXT   | NX-A1/R1；Orchestrator：Parse→One Claim→Repo Locate/Inspect→ReproPlan→Policy→Approval              | 来源/License、repo revision、数据、命令、指标来源/容差、预算可审核；模型计划不绕 NX-G2                     |
| NX-P2 受控 A/B             | NEXT   | NX-S1/P1/G2；A Build/Smoke/有界 Repair/Execute→Freeze→B→Metric/Report，可先用 preset 验证 A/B             | 冻结代码/镜像/依赖/数据/配置/种子/命令/比较标准；不继承 A 可变目录；修复变计划重新批准；B 成功且指标满足才 reproducible=true |
| NX-H2 Subagent/Workspace | TARGET | 先只读子任务；依赖 NX-H1/G2/S1 与事件恢复                                                                      | 父子权限/预算/取消/恢复；文件只工作区，execute 只隔离 Provider；不直接解除 excluded\_tools               |

附件接口族规划为 `/api/v1/nexus/attachments` 提交/状态/删除/鉴权下载，chat 传 attachment\_ids（尚未实现）。短文件预算内全文、长文分块、表格按范围；不把课程入库流水线搬进 Nexus。v1.3 C2 的首版限额/retention 建议需样例调优。

## 5. Experiment Console / Session：NX-E1–E4

| 任务    | 状态   | 改动入口与交付                                                                                                    | 验收                                                                                                |
| ----- | ---- | ---------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| NX-E1 | NEXT | nexus/persistence.py/main.py、Backend Nexus 代理/服务、NexusPage：owner/session/turn/run/job 持久化；为 NX-G2 先供最小归属契约 | 刷新/换设备查原 job 并恢复轮询，不重复提交；跨用户拒绝；job 缺失 unknown/interrupted                                         |
| NX-E2 | NEXT | worker.py 增量 Stage/有界日志、代理脱敏、前端只读 Console                                                                  | Stage/Command label/Elapsed/Exit code/20 行日志/Metric/Report；运行中可见新日志；服务端时间戳；预构建/无 B 诚实显示；无交互 Shell |
| NX-E3 | NEXT | Worker cancel、代理鉴权、前端 cancelling/cancelled                                                                 | 排队/运行幂等取消，进程组/容器回收确认才 cancelled；完成竞争正确；不影响其他 job，聊天 Stop 不充当 Cancel                               |
| NX-E4 | NEXT | 服务端 mode/course/pin/version、最小事件/游标、Worker 快照与重启对账                                                         | 跨设备偏好/过程恢复；去重；无原始完整 Trace/思维；checkpoint 与产品历史分开；删除/保留覆盖关联资源                                       |

当前 Worker 无实时连续 Console/cancel API，\_jobs 在内存；前端 local+remote merge 无完整运行恢复。历史 API 不返回 ToolMessage 不证明 checkpoint 未存。旧记录无法还原时显示不可恢复，不凭回答造 Trace。

## 6. 执行顺序与验证

1. NX-G1/G2/G3 先行，有副作用的新增执行以审批硬门为先；保留工作区既有修正，验证后才能申请提交/上线。
2. NX-A1 + NX-E1 打输入/归属基础；NX-H1 与 NX-E2 用同一 run/event 契约；NX-E3 单独完成取消闭环。
3. NX-R1 与 NX-S1 可同期选型；NX-P1/P2 按依赖接入。NX-E4 完成事件历史与重启对账，TARGET 另排批次。
4. 回退保留 preset，但不能绕过已启用强审批；关闭新 Provider 时保留状态/报告可读，不自动重放命令。
5. 测试覆盖 Mode、恶意跨模式调用、无批准 Worker 零调用、过期/跨用户/计划篡改/并发重试、health 失联、八格式/视觉、取消、恢复、A/B 与日志脱敏。隔离 fixture/mock 不调真实付费服务；Mock 不能称线上安全验收。
6. 既有两项域测试失败与 Compact 全图边界单独跟进，不能删除断言制造全绿。每任务写 commit/工作区、环境、实际链路、命令/结果和未验证项。

## 7. 依赖、自研与授权

通用基础设施成熟开源优先；CodeNexus 的 Course/CS/权限/对象存储现有服务优先。Reproduction Orchestrator / Policy / Verification orchestration 是自研一等业务模块，不贬为几行 glue。

候选逐版本核验 License/隔离/依赖/维护成本；可 library 或 sidecar。`1a1a11a/2026_paper_reproduce`、`AI9Stars/AutoReproduce` 未确认明确许可前固定 concept-only / no source reuse，不进入可复制代码池。

“无新增依赖/常驻服务”仅描述原 M0–M5 增量，不限制 NX。后续可经评估新增 OSS dependency/service，但安装/升级/部署仍需明确授权，Nexus/Backend 不共享 venv。不提交/push/部署或用真实密钥跑自动测试，除非按 AGENTS.md 授权。

## 8. 历史附录

[M0–M5 完整历史快照](CodeNexus_P2开发计划_历史快照_2026-09-05.md)保留原任务与 §十四验收；[验收记录目录](验收记录/)保留原证据。本次不改历史结果，M1 四工具数字不再出现在当前快照。
