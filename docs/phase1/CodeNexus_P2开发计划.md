# CodeNexus 开发计划：Current MVP → NX 必要主线

> **版本**：2026-09-08 批次规划刷新版；基线 dev-liu，核查 HEAD=e1c6483c（LB1/LB2 部署线 6eb8b361→96a2b30f→fa4bceed→e1c6483c，线上 E2E 31/31）。上一版：2026-09-06 状态刷新版（基线 d54b444a）。
> **设计依据**：[v1.3 Current Architecture + Roadmap](CodeNexus_转型设计与实施方案_v1.3.md)；[前端规格](Nexus_AI_前端开发规格与UX落地说明.md)。
> **2026-09-07 后端规划增补**：依据 [NexusLab v6 设计板](2026-09-07_NexusLab_研究与实验一体化设计板_v6.html) 核查本地 `bb10d313` 的实际接口，新增 §9「研究与实验一体化后端批次」。仅规划，不代表实现或部署完成；v6 的示例值与按钮不作为服务已具备能力的证据。
> **2026-09-08 批次交付与规划刷新**：批次 A/B（NX-LB1/LB2）已提交部署（6eb8b361→96a2b30f→fa4bceed，途中线上 E2E 发现并修复两处编译器缺陷：lr_decay 下限、eval_interval 钳制），完成线上 PG 迁移验证与真实 Worker 端到端验证（31/31）；§9.4–§9.6 转为批次 C/D 冻结规划，待实施。
> **2026-09-08 批次 C/D 本地完成**：NX-LB3/LB4/LB5 已实现＋离线合成测试（未提交未部署），证据见[验收记录](验收记录/NX-LB3_LB4_LB5_验收_2026-09-08.md)；部署与线上 Worker E2E 待明确授权。
> **历史**：原文件名保留以兼容链接。M0–M5 原任务、验收和工具数量完整移至[历史快照](CodeNexus_P2开发计划_历史快照_2026-09-05.md)，不代表当前工具面或未来排期。2026-09-06 刷新依据：git 历史 b34ea2d9/b080e269（首批 P0 提交部署与线上只读验证）、[NX-G1G2G3 验收](验收记录/NX-G1G2G3_验收_2026-09-05.md)、[NX-A1E1 验收](验收记录/NX-A1E1_验收_2026-09-05.md)。

## 1. Current / Next / Target / Optional

CURRENT=有真实验收的限定能力；NEXT=下一批必做；TARGET=最终目标、本批不交付；OPTIONAL=按需评估。CURRENT 不等于依赖实时健康，工作区修改不等于 HEAD 或部署。所有 NX 任务均待实施/验证，无日历承诺。

| 范围                                                               | 状态       | 边界                                                |
| ---------------------------------------------------------------- | -------- | ------------------------------------------------- |
| Web/Course/CS 检索、Markdown/LaTeX Artifact                         | CURRENT  | 既有 M2/M3 验收；DOCX 输入另属 NX-A1，DOCX/PPTX 输出 TARGET   |
| Tool loop、Compact、checkpoint、消息恢复                                | CURRENT  | P1/M1/M5 验收；Compact 全图触发边界保留；不是完整 Harness/跨设备产品历史 |
| nanoGPT preset、基础步骤结果/指标/报告                                      | CURRENT  | P1/M4 验收；轮询 job 与终态步骤结果，不称实时全过程 Console           |
| Legacy Research S3                                               | CURRENT  | M5 验收；活跃教学消费者、数据/迁移保留，不重做已下线迁移                    |
| 服务端执行审批（NX-G2）＋mode 严格化（NX-G1）＋effective capability（NX-G3） | CURRENT  | b34ea2d9 上线、b080e269 线上只读验证；真实审批全链已于 09-06 浏览器验收通过（NX-E2E3 记录） |
| 附件/视觉（NX-A1）、run 恢复（NX-E1）、模型网关                          | CURRENT  | 随 b34ea2d9 上线；PG 方言/OCR 回填/附件 E2E/真实恢复链已于 09-06 浏览器验收通过 |
| **Experiment Console（NX-E2）、作业取消（NX-E3）**                       | CURRENT  | 09-06 上线（9cdbf8a8 线），Worker v0.2.0；浏览器真实链验收含取消/恢复/真实审批；09-07 边界修复批次 F1–F6 全量修复并线上复验（Worker v0.3.0，见[审查记录](NX-E2E3_质量与产品符合性审查_2026-09-07.md)修复回执） |
| **v6 后端批次 A/B（NX-LB1/LB2）**                                | CURRENT  | 09-08 部署（6eb8b361→fa4bceed 线）：运行元数据/稳定命名/分页/重命名/presets 投影，结构化提案/审批恢复/执行冻结/指标基线；线上 PG 迁移＋真实 Worker E2E 31/31；v6 前端联调未接，批次 C/D 后端继续（§9） |
| **v6 后端批次 C/D（NX-LB3/LB4/LB5）**                           | NEXT     | 09-08 本地完成（未提交未部署）：运行引用/有界上下文/单写者门/幂等、查询·取消·备注·提案工具、取消一次性授权、备注/产物关联；离线全绿（见[验收记录](验收记录/NX-LB3_LB4_LB5_验收_2026-09-08.md)），部署＋线上 E2E 待授权 |
| Todo、Paper Research、SandboxProvider、受控 A/B、Session                 | NEXT     | 下表独立验收，不一次翻转全线 ready；批次建议见 §7                   |
| Subagent/Workspace、广泛任意论文/仓库、DOCX/PPTX 输出                        | TARGET   | 门槛到位后另排批次                                         |
| Personal Context、GPU/多云、额外模型选择器                                  | OPTIONAL | 按需评估；图片视觉模型配置仍是 NX-A1 必需项                         |

## 2. Current registered / effective tool surface

| 层次               | 工具                                                                          |
| ---------------- | --------------------------------------------------------------------------- |
| General 产品工具（7）  | web\_search、search\_course\_materials、search\_cs\_knowledge、write\_artifact、read\_attachment、write\_todos（NX-H1 计划）、read\_file（StateBackend 历史读回，不是宿主通用文件） |
| Research 产品工具（12） | 全部 General + search\_arxiv\_papers、plan\_reproduction、run\_reproduction、collect\_paper\_evidence、write\_research\_report（NX-R1a） |
| 两模式内部 Harness    | StateBackend 历史读回等内部能力（read\_file 已计入上方注册面口径）                              |

代码源为 `nexus/src/nexus/tools/__init__.py` 与 `agent.py`。注册不等于可执行：`effective = manifest ∩ mode ∩ tool surface ∩ health/config ∩ user/scope policy`，提交另需 approval。聚合与强审批已随 b34ea2d9 部署上线（2026-09-05）；附件与恢复同批上线，真实链已于 09-06 浏览器验收。工具计数为 /health tool_surface 口径（fa4bceed 线实证：General 7/Research 12，含 NX-H1/R1a 注册）。

## 3. 首批 P0：NX-G1–G3

> **状态（2026-09-06 刷新）**：已随 b34ea2d9 提交部署上线（2026-09-05），线上只读验证见 b080e269
>（/health checks 全 ok、approvals 路由就绪、Research 8/General 5 工具面实证）；
> 本地 94/94＋代理 27/27 证据见[验收记录](验收记录/NX-G1G2G3_验收_2026-09-05.md)。真实 PG 审批表与真实审批全链属交互式验收，待补（§7 清单）。

| 任务                          | 当前差距                                                                                          | 改动入口                                                                                         | 验收                                                                                                                                   |
| --------------------------- | --------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| NX-G1 Mode/身份/模式工具面         | ✅ 本地完成（2026-09-05）：unknown/空串双层 400，前端 4/7 映射＋Research 门；中性 Base 沿用 HEAD | agent.py/main.py、nexus\_proxy.py、nexusAdapter.js/nexusCapabilities.js/NexusPage.vue、相关模式契约测试 | missing/null→General；别名正确；unknown/空串→400 INVALID\_NEXUS\_MODE，模型/SSE 前拒绝；非法类型拒绝；General 不显示/不能调用 Paper/NexusLab；4/7 工具映射一致；保留中性 Base |
| NX-G2 Runtime Hard Approval | ✅ 本地完成（2026-09-05）：一次性票据＋统一核销核心＋审批卡；归属提案时落库                                             | tools/reproduction.py、request\_scope.py、Nexus 持久化；Backend Nexus 代理/内部端点/服务；前端审批状态            | 提案→ApprovalRequired→暂停→本人批准→服务端验证→恢复；绑定 user/session/run/tool/plan hash/预算/有效期；无批准 Worker 零提交；归属先于执行；一次性、幂等、防重复 job                  |
| NX-G3 Effective capability  | ✅ 本地完成（2026-09-05）：health checks＋resolver＋页面 effective 渲染                                                                | Runtime health/代理、nexusCapabilities/nexusAdapter/NexusPage                                   | manifest+mode+注册面+依赖 TTL/health+权限计算；掉线/过期 unknown/degraded；General 永远无 NexusLab；执行端另验证策略和审批                                         |

强审批采用"服务端一次性票据＋统一核销核心"（等价票据方案，已本地实现，不引入可持久化 interrupt 中间件）；不能只增加模型可填的 approved=true。服务端批准取登录身份，票据不交模型自由生成；绑定计划/预算变化即失效，任何聊天/手工/内部/恢复入口共用检查。NX-E1 的最小 owner/run/job 切片已随本批交付（审批记录即执行前归属），不等完整 Session。

批准/提交/返回网络超时需幂等键与对账，重试返回原 job；拒绝/过期/跨用户/篡改/重复消耗不得执行。硬门完成前不扩大执行面，强审批对外承诺保持未完成；需要此承诺的入口先关闭提交或先完成 NX-G2。

## 4. 必要能力交付

| 任务                       | 状态     | 交付与依赖                                                                                            | 验收门                                                                           |
| ------------------------ | ------ | ------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------- |
| NX-A1 附件/视觉              | ✅ 上线（2026-09-05，b34ea2d9）：八格式入口＋解析＋配额＋生命周期；DOC/PPT 无 LibreOffice 如实 failed；图片直传＋OCR 按需；PG 方言/OCR 回填/附件 E2E 待补（§7 清单） | General/Research 八格式共用入口；复用对象存储/ParserProvider/OCR/LibreOffice，补 XLSX；先生命周期/PDF链再其他格式与论文 Profile | 八格式各一合成样例；图片直传不强制 OCR、无视觉诚实降级；页/slide/cell/段落引用；scope/限额/删除/过期/错误明确；不进课程知识域   |
| NX-H1 Plan/Todo          | ✅ 本地开发/验证完成（2026-09-07，[回执](验收记录/NX-H1_R1a_本地开发回执_2026-09-07.md)）；线上部署后待人工复验 | 已安装 TodoListMiddleware 显式集成（不自研 write_todos）；真实 state 投影 `plan` SSE 事件 + 同步响应 plan + `GET /nexus/plan/{sid}` 恢复（权限门同链）；前端 planState 状态机 + 折叠计划卡 | 简单 General 不强制建计划（提示词约束，无分类器）；计划修改、实际工具状态分开；checkpoint 恢复一致；取消不改写条目；跨用户隔离；无静态假进度 |
| NX-R1 Paper Research     | **R1a 限定薄链本地完成**（2026-09-07，同回执）：上传 1–3 篇 PDF 全文→证据（evidence_id/locator/coverage）→比较/综合→服务端渲染引用→Markdown Artifact；候选与证据严格区分、abstract_only 如实、全文不可得提示上传。整体 Paper Research（自动全文获取、PaperQA 选型、大规模综述）保持 NEXT | collect_paper_evidence / write_research_report（Research-only，身份来自请求作用域）；引用服务端渲染，模型只可引用登记 id，最多 1 次修正 | 问题→证据→比较→综合→Citation→Artifact 全链本地 fake/合成验证；真实 LLM 质量验收待用户安排 |
| NX-S1 SandboxProvider    | NEXT   | 现有 Worker 后续适配；SWE-ReX/同类执行层、repo2docker 构建层；统一创建/执行/状态/取消/清理语义                                  | 隔离、网络、凭据、挂载、预算、取消和清理；同 preset 对比；不因安装组件自动获得任意仓库/A-B 安全声明                      |
| NX-P1 Paper-to-plan      | NEXT   | NX-A1/R1；Orchestrator：Parse→One Claim→Repo Locate/Inspect→ReproPlan→Policy→Approval              | 来源/License、repo revision、数据、命令、指标来源/容差、预算可审核；模型计划不绕 NX-G2                     |
| NX-P2 受控 A/B             | NEXT   | NX-S1/P1/G2；A Build/Smoke/有界 Repair/Execute→Freeze→B→Metric/Report，可先用 preset 验证 A/B             | 冻结代码/镜像/依赖/数据/配置/种子/命令/比较标准；不继承 A 可变目录；修复变计划重新批准；B 成功且指标满足才 reproducible=true |
| NX-H2 Subagent/Workspace | TARGET | 先只读子任务；依赖 NX-H1/G2/S1 与事件恢复                                                                      | 父子权限/预算/取消/恢复；文件只工作区，execute 只隔离 Provider；不直接解除 excluded\_tools               |

附件接口族已实现为 `/api/v1/nexus/attachments` 提交/状态/删除/鉴权下载，chat 传 attachment\_ids（≤5，发送时验主＋原子绑定）。短文件预算内全文、长文分块、表格按范围；不把课程入库流水线搬进 Nexus。v1.3 C2 的首版限额/retention 建议需样例调优。

## 5. Experiment Console / Session：NX-E1–E4

| 任务    | 状态   | 改动入口与交付                                                                                                    | 验收                                                                                                |
| ----- | ---- | ---------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| NX-E1 | ✅ 上线（2026-09-05，b34ea2d9）：nexus_runs 注册＋恢复查询＋前端只读恢复；run_id 冲突属他人 409；真实恢复链待补（§7 清单） | nexus/persistence.py/main.py、Backend Nexus 代理/服务、NexusPage：owner/session/turn/run/job 持久化；为 NX-G2 先供最小归属契约 | 刷新/换设备查原 job 并恢复轮询，不重复提交；跨用户拒绝；job 缺失 unknown/interrupted                                         |
| NX-E2 | ✅ 上线（2026-09-06，浏览器真实链验收；**09-07 边界修复**：日志真脱敏/有界块读采集/子进程环境白名单/Metric pending 语义，Worker v0.3.0） | worker.py stage_events/live_log_tail、代理透传+脱敏、NexusPage 会话内 Console | Stage/Command label/Elapsed/Exit code/20 行日志/Metric/Report；运行中可见新日志；服务端时间戳；预构建/无 B 诚实显示；无交互 Shell——全部实证（[验收记录](验收记录/NX-E2E3_验收_2026-09-06.md)、[审查记录回执](NX-E2E3_质量与产品符合性审查_2026-09-07.md)） |
| NX-E3 | ✅ 上线（2026-09-06，同上；**09-07 边界修复**：代理取消如实映射上游错误/spawn 窗口取消重查/前端冷恢复补齐） | 运行中取消→取消中→已取消→进程组回收（exit -9）→幂等→已完成步骤保留——全部实证 |
| NX-E4 | NEXT | 服务端 mode/course/pin/version、最小事件/游标、Worker 快照与重启对账                                                         | 跨设备偏好/过程恢复；去重；无原始完整 Trace/思维；checkpoint 与产品历史分开；删除/保留覆盖关联资源                                       |

当前 Worker 已有阶段/有界日志与 cancel API，\_jobs 仍在内存；前端 local+remote merge 已支持限定运行恢复，完整跨设备会话与 Worker 重启对账仍属 NX-E4。历史 API 不返回 ToolMessage 不证明 checkpoint 未存。旧记录无法还原时显示不可恢复，不凭回答造 Trace。

## 6. 执行顺序与验证

1. ✅ NX-G1/G2/G3、NX-A1、NX-E1 已随 b34ea2d9 上线（2026-09-05，b080e269 线上只读验证）；§7 前置清单五项交互式验收已全部通过（2026-09-06 浏览器真实链，见 [NX-E2E3 验收](验收记录/NX-E2E3_验收_2026-09-06.md)）。
2. ✅ 下一批次 NX-E2+E3 已上线并通过浏览器真实链验收（2026-09-06，Worker v0.2.0）；验收发现并修复 4 个集成缺陷（归属断层/code 键信封冲突/恢复标记误持久化/附件清单未注入），详见验收记录。
3. ✅ NX-E2/E3 边界修复批次（2026-09-07，`5f989495`+`c89ee487`，Worker v0.3.0）：审查记录六项发现（F1 取消失败被包装成功/F2 日志真脱敏/F3 长行采集/F4 冷恢复/F5 spawn 窗口取消/F6 Metric 真实判定）全量修复；测试矩阵 Worker 20＋Nexus 102＋后端 nexus 域 59＋前端契约 89 全绿；浏览器复验通过（含 Metric pending→报告回写 done 全链、冷恢复补齐、取消链）；详见[审查记录修复回执](NX-E2E3_质量与产品符合性审查_2026-09-07.md)。
4. NX-H1/R1a 已于 09-07 部署（0ea84612 线，线上烟雾验证见 bb10d313 回执）；面向 v6 的后端批次 A/B（运行元数据、结构化提案/审批）已于 09-08 部署并完成线上 E2E（31/31），下一批按 §9.4–§9.5 批次 C（上下文与工具操作）执行，随后批次 D＝LB5（§9.6）。NX-S1＋NX-E4、NX-P1/P2 按依赖继续，不能因工作台外壳接好就宣称完整实验平台完成。
5. 回退保留 preset，但不能绕过已启用强审批；关闭新 Provider 时保留状态/报告可读，不自动重放命令。
6. 测试覆盖 Mode、恶意跨模式调用、无批准 Worker 零调用、过期/跨用户/计划篡改/并发重试、health 失联、八格式/视觉、取消、恢复、A/B 与日志脱敏。隔离 fixture/mock 不调真实付费服务；Mock 不能称线上安全验收。
7. 既有两项域测试失败与 Compact 全图边界单独跟进，不能删除断言制造全绿。每任务写 commit/工作区、环境、实际链路、命令/结果和未验证项。

## 7. NX-E2+E3 批次：✅ 已完成上线（2026-09-06）

> 实现＋部署＋浏览器真实链验收全部完成，见[验收记录](验收记录/NX-E2E3_验收_2026-09-06.md)。
> 验收过程发现并修复 4 个集成缺陷（归属登记断层、轮询 code 键信封冲突、
> 恢复标记误持久化、附件清单未注入）——均为自动化测试未能覆盖、只有真实
> 链路才能暴露的问题。§7 前置清单五项交互式验收全部通过。
> 部署线：1338467b（归属/信封修复）→ 9cdbf8a8（恢复补状态）→ 8ce3597f
> （恢复标记）→ b9d0ddda/9bf9e397（附件清单注入＋归属服务可移植化），
> Worker v0.2.0 容器重建，Nexus Runtime 同步重启。

**后续批次建议**：

1. 批次 2＝NX-H1＋NX-R1 薄链：H1 显式复用已安装的 `langchain.agents.middleware.TodoListMiddleware`，补产品事件与恢复投影，不自研替代 `write_todos`（2026-09-07 本地导入核验通过；0.7 移出默认 Harness 不等于删除能力）。本次 R1a 限定已上传 PDF 全文→证据定位→比较/综合→引用 Artifact，候选检索复用现有工具，全文不可得诚实降级；不新增依赖，不以本次薄链替代最终 PaperQA/同类组件选型和完整 Paper Research。具体边界、任务、验收与无人值守约束见 [NX-H1/R1 夜间执行任务书](2026-09-07_NX-H1_R1_夜间执行任务书.md)。
2. 批次 3＝NX-S1 接口化（统一 SandboxProvider port，现有 Worker 适配为首个 PresetSandboxProvider，保持 nanoGPT 链回归；SWE-ReX/repo2docker 许可核验报告）＋NX-E4（服务端 session 权威＋产品事件表＋Worker 重启对账）。
3. 批次 4＝NX-P1/P2（依赖 S1+E3，可先用 nanoGPT preset 验证 A/B 流程）。

## 8. 依赖、自研与授权

通用基础设施成熟开源优先；CodeNexus 的 Course/CS/权限/对象存储现有服务优先。Reproduction Orchestrator / Policy / Verification orchestration 是自研一等业务模块，不贬为几行 glue。

候选逐版本核验 License/隔离/依赖/维护成本；可 library 或 sidecar。当前命名候选：SWE-ReX（执行层）、repo2docker（构建层）、paper-qa/PaperQA2（论文 RAG）——未核验前只评估不依赖。`1a1a11a/2026_paper_reproduce`、`AI9Stars/AutoReproduce` 未确认明确许可前固定 concept-only / no source reuse，不进入可复制代码池。

“无新增依赖/常驻服务”仅描述原 M0–M5 增量，不限制 NX。后续可经评估新增 OSS dependency/service，但安装/升级/部署仍需明确授权，Nexus/Backend 不共享 venv。不提交/push/部署或用真实密钥跑自动测试，除非按 AGENTS.md 授权。

## 9. v6 研究与实验一体化：仅后端缺口与下一开发方案

### 9.1 范围及真实基线

状态：批次 A/B（NX-LB1/LB2）已于 2026-09-08 提交部署（6eb8b361→96a2b30f
→fa4bceed），完成线上 PG 迁移验证与真实 Worker 端到端验证（31/31，途中修复两处编译器缺陷：lr_decay 下限、eval_interval 钳制），证据见[验收记录](验收记录/NX-LB1_LB2_验收_2026-09-08.md)；批次 C＝LB3＋LB4（§9.4/§9.5）、批次 D＝LB5（§9.6）**已本地完成（未提交未部署）**，证据见[验收记录](验收记录/NX-LB3_LB4_LB5_验收_2026-09-08.md)。后端批次覆盖 Backend API/领域服务、Nexus Runtime/工具、必要的 Worker 参数契约及迁移测试；不开发页面、切换器、拖动、sessionStorage 布局记忆。保留同一研究会话、同一 Agent 的设计，不另建“浮窗助手”或科研工作台大脑。

| v6 行为 | 本地代码已有 | 真正缺口 |
| --- | --- | --- |
| 本次运行切换、运行数量 | ✅ LB1：序号/分页/计数/不可变配置投影/部分失联语义已交付（本表"真正缺口"列对应项关闭） | ~~不是缺列表 API；缺稳定名称/序号、分页与可靠计数、不可变配置投影、部分失联语义~~ |
| 审批浮窗 | ✅ LB2：待办恢复＋可版本化修改的提案＋参数差异＋旧提案失效处理已交付 | ~~仅有指定 id 查询；缺按会话恢复待办、可版本化修改的提案、参数差异、旧提案失效处理~~ |
| 运行详情/取消/报告 | `GET /repro/jobs/{job_id}`、`POST /repro/jobs/{job_id}/cancel`、`POST /repro/jobs/{job_id}/report` | 复用已有端点；报告生成不是 GET。缺模型侧运行查询/取消工具，不能把 HTTP API 存在等同于 Agent 会用 |
| 浮窗继承研究会话 | chat/stream 已有 session_id、mode、checkpoint 和附件 scope | 缺受验证的 run/step 引用、服务端有界日志注入、同会话多窗口写入协调 |
| 口述改参数再运行 | ✅ LB2：参数 schema/校验、计划快照、配置→命令确定性映射、指标基线（verified/exploratory）已交付 | ~~缺参数 schema/校验、计划快照、配置→命令确定性映射、与参数匹配的指标基线~~ |
| 实验名、运行备注 | ✅ LB1：`title` 持久化＋`PATCH /runs/{id}`（归属校验＋乐观锁）；备注 API 列批次 D | 运行备注追加式 API＋Agent 备注标记（批次 D）；实验名已随 LB1 交付 |

代码依据：`backend/app/services/nexus_run_service.py`、`backend/app/api/v1/endpoints/nexus_proxy.py`、`nexus/src/nexus/approvals.py`、`nexus/src/nexus/tools/reproduction.py`、`nexus/src/nexus/main.py`、`nexus/src/nexus/tools/__init__.py`。执行前重新核对 HEAD/工作区，不能覆盖现有前端改动。

### 9.2 NX-LB1：运行元数据、稳定命名与配置查询

> ✅ 已提交部署（2026-09-08，批次 A）：fa4bceed 线上实证 presets 投影、会话内稳定序号、重命名乐观锁、分页与 config_status 均走真实 PG。证据见[验收记录](验收记录/NX-LB1_LB2_验收_2026-09-08.md)。以下为冻结规格（已实现）。

**首批交付，自定义实验名一起立项。** 不新建实验项目层；当前一条 run 表示一次批准执行，修改后再运行通过 parent_run_id 关联。

- 扩展 Nexus 域 `nexus_runs`：`title`（可空的用户命名）、`run_number`（会话内稳定序号）、`version`（元数据乐观锁）、`parent_run_id`、`proposal_id/proposal_version`、`config_snapshot`。默认显示名由服务端 `preset display_name + run_number` 生成；paper_title 单独投影作论文信息，不直接强制用长论文名作为实验名。
- 会话内序号由事务分配，以 `(user_id, session_id, run_number)` 唯一约束防并发冲突；分页、重命名、删除其他记录不重排。前端 sorted index 只可临时显示，不能成为稳定标识。
- 新增 `GET /api/v1/nexus/repro/presets`：只返回可见 preset 的 display_name/paper_title、只读环境摘要、参数 schema/defaults、预算上限、指标与来源、能力限制；不返回凭据、内部路径或任意命令入口。Backend 经内部 HTTP 查询 Runtime，不跨 Python 环境 import preset。
- 扩展已有 runs 列表/详情：返回 display_title/title/run_number/version、parent 引用、proposal 引用、冻结配置、status_source/observed_at/stale；列表提供 cursor/limit/next_cursor 和会话运行计数（未知数量单列，不能把 unavailable 当成 0）。旧 items 字段保留。
- 新增 `PATCH /api/v1/nexus/runs/{run_id}`，请求 `{title, expected_version}`：trim 后 1–120 字符，null 恢复默认名；不接受配置/状态/owner 修改。非本人 404，版本冲突 409，非法字段 422。重命名不改变执行 hash 或运行配置。
- 现有逐项等待 Worker 的列表改为有界并发/批量状态读取及整体截止；终态可消费已保存快照。Worker 失联返回 stale/unknown，不能导致整个会话列表无限等待或把旧运行中快照当成当前事实。

验收（✅ 2026-09-08 本地验证通过，见验收记录）：同会话并发两次执行序号不重复；分页序号稳定；重命名跨设备一致；未知历史配置标记 unavailable；跨用户不可读写；Worker 失联不阻塞列表。无需等待完整 NX-E4 才提供这些最小切片。

### 9.3 NX-LB2：结构化实验提案、参数修改与审批恢复

> ✅ 已提交部署（2026-09-08，批次 B）：线上真实 Worker E2E 31/31——提案→审批→执行→冻结命令逐字生效→报告 EXPLORATORY→旧票失效 409 全链实证；途中修复 lr_decay 下限与 eval_interval 钳制两处编译器缺陷。证据见[验收记录](验收记录/NX-LB1_LB2_验收_2026-09-08.md)。以下为冻结规格（已实现）。

这是“在输入框提出修改”能够真实落地的核心，不是改一段展示文本。

**提案模型**（Nexus 自有存储，归 Runtime 业务编排）：proposal_id、owner/session、version、preset_id/version、parent_run_id、objective、parameters、environment_snapshot、repo_revision、data/seed、steps、budget、metric_policy/source、plan_hash、status、created_at。审批引用 proposal_id+version+hash；执行 run 保存批准时的不可变快照。

建议新增接口（统一 `/api/v1/nexus`，Backend 身份代理，Runtime 执行同一领域服务）：

| 接口 | 用途/限制 |
| --- | --- |
| `POST /repro/proposals` | 从已核验 preset 或本人 parent_run_id 建草案；创建不执行；带 client_request_id，重复请求返回原草案 |
| `GET /repro/proposals/{id}` | 返回完整方案、校验结果及与父运行/上一版本的结构化 diff |
| `PATCH /repro/proposals/{id}` | `{expected_version, objective?, parameters?}`；仅白名单参数可改，版本冲突 409；改动成功使旧批准不可用于新版 |
| `POST /repro/proposals/{id}/request-approval` | 固定 expected_version/hash，校验通过后生成/复用该版本审批；不直接执行 |
| 扩展 `GET /approvals?session_id=...&status=pending` | 恢复输入框浮窗，返回所有待办的 proposal/version/hash/目标/环境/预算/有效期；不能静默选错另一运行的审批 |

沿用已有 decide/execute，不能新开"直接启动"旁路。旧 preset 调用与提案路径共用同一核销原语（一票一次、hash 绑定、幂等）与统一执行核心；不复制两套审批引擎。

**参数和环境边界：**先为 nanoGPT 定义经过审核的 typed schema，仅对已支持、限额明确的参数开放修改；字段范围与组合约束在实施时结合 Worker 资源验证后冻结。未知字段/非法组合拒绝，不用字符串替换 shell。服务端由参数确定性生成冻结命令，Worker 只接受可验证版本/参数与计划一致的执行请求，不能接模型任意 command。首版环境为预置环境，版本、可用资源与依赖投影只读；用户要求未支持的环境变更返回 capability gap，不伪装“已配置”。

**审批强约束：**hash 覆盖 repo revision、环境/依赖标识、数据/seed、参数、执行步骤、资源预算和 metric_policy；标题、备注属于非执行元数据不入 hash。修改提案与旧审批失效、批准与执行竞争要有事务/CAS 规则：修改先成功则旧票据拒绝；执行先核销则原运行保持冻结，后续修改必须创建新提案。网络重试不得产生第二个 job；请求结果不确定先对账，不自动重放。

**指标不能沿用错基线：**改变训练步数/数据/模型配置后，不直接沿用 `1.88±0.06`。只有匹配已验证基线的配置才能产生该 PASS/FAIL；否则标记 exploratory/未建立比较标准，仍可输出测量值，但不得称复现通过。不得让模型自填容差来保证 PASS。

验收：同 preset 两版参数 diff 可审阅；越界/注入被拒；旧批准不能执行新配置；重复批准/执行只产生一个 job；修改与核销并发无混用；Worker 实际参数与报告冻结配置一致；修改参数后未知指标基线诚实显示。

### 9.4 NX-LB3：同会话实验上下文及并发协议

> 📋 **批次 C（一）已本地完成（2026-09-08，未提交未部署）**，证据见[验收记录](验收记录/NX-LB3_LB4_LB5_验收_2026-09-08.md)。批次 C＝LB3＋LB4，交付后浮窗即可“继承研究上下文”；以下为实施规格，任务分解见节末。

扩展已有 chat/chat-stream 请求（不是新聊天端点）：

```json
{
  "session_id": "existing-research-session",
  "mode": "research",
  "client_request_id": "unique-per-message",
  "context": {"run_ref": {"run_id": "owned-run", "step_id": "optional-step"}}
}
```

- 只接受客户端明确引用的 run/step 标识；不接受客户端提交的日志、退出码或指标作为执行事实。Backend 根据当前登录用户、session 与 run 归属验证，解析 job_id 后经已有 job/report 服务生成最小白名单上下文。
- 首版预算：最近最多 40 行且最多 8000 字符，并受现有上游更小窗口限制；仅保留当前/指定步骤、阶段、退出码、相关指标及 Artifact 引用。附 observed_at、stale、实际行数、truncated；上游只有 20 行就返回 20 行，不补造“40 行”。复用服务端脱敏，不注入完整历史日志、完整 Trace、环境变量或宿主路径。
- Runtime 使用同一 user/session namespace、同一 checkpoint、同一 Research profile；实验资料为不可信数据，不作为指令。切换 run 只改变本条引用，不切线程或自动重提实验。
- 同一线程一次仅允许一个活动 graph 写入；主对话和浮窗请求共用门。不同 client_request_id 竞争返回 `409 SESSION_BUSY`；同一请求重试不得重复调用模型或工具，返回现有请求状态/可恢复结果。首版不建复杂排队器；断流不等于执行失败，提供有限状态恢复语义。
- plan/tool/result/error 事件携带 session_id/request_id，作业事件再带 run_id/job_id；服务端不得由“当前显示会话”决定归属。checkpoint 读取故障返回明确失败，不能伪装 plan:null。
- 仅展开/拖动浮窗/切换视图不发模型任务、不创建 run；Backend 不存浮窗坐标。Chat Stop 仅停止本次生成，取消实验仍调用独立 cancel 链。

验收：两个窗口共享历史但不并发污染 checkpoint；跨用户、跨会话或不存在 step 引用被拒；恶意日志不能变成工具指令；Worker 不可达仍可解释“状态未知”；刷新/断流/重复发送不重复执行；旧请求事件仍属于原 session。

**任务分解（批次 C 一）**：
1. 请求扩展：Backend 代理与 Runtime 端点同步接收 `client_request_id`（幂等键）与 `context.run_ref {run_id, step_id?}`；旧客户端缺省字段不破坏（改动入口 `nexus_proxy.py`、`main.py`）。
2. 运行上下文投影服务：登录身份＋session＋run 归属验证→解析 job_id→经已有 job/报告服务生成白名单上下文（当前/指定 step、阶段、退出码、指标与 Artifact 引用、≤40 行且 ≤8000 字符有界日志、observed_at/stale/truncated/actual_lines）；复用服务端脱敏（改动入口 `nexus_run_service.py` 或新增 `nexus_run_context_service.py`、`nexus_internal.py`）。
3. Runtime 注入与隔离：白名单投影进入同一 user/session namespace 的 Research profile，实验资料按不可信数据处理；不注入完整历史日志、完整 Trace、环境变量或宿主路径（改动入口 `request_scope.py`、`agent.py`）。
4. 并发/幂等控制：同 (user, session) 线程单写者门；`client_request_id` 重试返回现有状态/可恢复结果，不重复调模型或工具；竞争 `409 SESSION_BUSY`；断流≠失败，提供有限状态恢复；plan/tool/result/error 事件携带 session_id/request_id，作业事件再带 run_id/job_id；checkpoint 读取故障明确失败。
5. 测试与交接：跨用户/跨会话/不存在 step 引用拒绝、注入日志不成工具指令、Worker 失联“状态未知”、重复发送不重复执行、事件归属原 session；OpenAPI/请求响应样例与错误码随批交接前端可消费。

### 9.5 NX-LB4：Agent 操作运行与方案的受限工具

> 📋 **批次 C（二）已本地完成（2026-09-08，未提交未部署）**；与 §9.4 同批实施与验收，交付后浮窗可“操作指定实验”（查询/取消/改方案）。以下为实施规格，任务分解见节末。

当前 HTTP cancel 已存在，但 Runtime 产品工具面没有相应操作工具；仅在提示词说“可以取消”不构成接线。

- 增加 Research-only `get_reproduction_run(run_id)`、`cancel_reproduction_run(run_id)`；身份和当前运行引用来自服务端请求作用域。显式 run_id 与已选上下文冲突、没有目标或目标歧义时拒绝/要求澄清，绝不选“最新运行”猜测。
- 查询复用 LB3 的授权/脱敏投影，取消复用现有 Backend cancel 核心；模型不得直接持有 Worker 凭据或绕开归属校验。
- 取消是破坏性停止动作，需本次用户明确取消意图所对应的服务端受限 action grant，或复用单次确认机制；不能因“正在讨论一个报错”就授权模型任意取消。grant 绑定 user/session/request/run/action/有效期，不能由模型工具参数伪造。模型识别意图本身不作为强授权证明；无凭据返回需确认，前端现有明确取消按钮仍可沿用。
- 增加/扩展提案创建与修改工具，统一调用 LB2 服务；模型只提出参数变更，不决定批准。完成工具调用返回真实 proposal/approval 引用供浮窗展示。
- 取消 HTTP 失败原样映射为失败；cancelling 不能提前转 cancelled；重复取消幂等；终态调用如实返回 already_terminal。

验收：General 看不到且不能调用上述工具；解释日志不会自动取消；合法取消命中指定 job；跨会话引用/伪造 grant 被拒；取消超时不显示成功；改方案绝不触发无审批执行。

**任务分解（批次 C 二）**：
1. Research-only 工具 `get_reproduction_run(run_id)`、`cancel_reproduction_run(run_id)` 注册进工具面与 effective capability；显式 run_id 与已选上下文冲突、无目标或目标歧义时拒绝并要求澄清，绝不“最新运行”猜测（改动入口 `tools/__init__.py`、`tools/reproduction.py`）。
2. 取消授权：取消意图→服务端受限 action grant（绑定 user/session/request/run/action/有效期，一次性核销，不由模型参数伪造）→复用现有 Backend cancel 核心；HTTP 失败原样映射，cancelling 不提前转 cancelled，重复取消幂等，终态如实 already_terminal。
3. 提案工具：创建/修改统一调 LB2 服务，返回真实 proposal/approval 引用供浮窗展示；模型只提出参数变更，不决定批准（改动入口 `approvals.py`、`tools/reproduction.py`）。
4. 测试：General 不可见不可调、解释日志不自动取消、合法取消命中指定 job、跨会话引用/伪造 grant 拒绝、取消超时不显示成功、改方案不触发无审批执行。

### 9.6 NX-LB5：运行备注与产物可核对性（后续小批次）

> 📋 **批次 D 已本地完成（2026-09-08，未提交未部署）**；交付“保存解释、查看和下载结果”的后端能力。以下为实施规格，任务分解见节末。

- v6 出现“写进本次运行备注”，当前没有相应 API。拟增 `GET/POST /runs/{run_id}/notes`，使用追加式 note_id、author_kind、request_id、created_at、content，最多 4000 字符；幂等、owner/session 校验。Agent 备注标记为解释/建议，不修改原日志、指标或 PASS/FAIL。必要时注册同权限的 note 工具。
- 扩展 run detail 的 artifacts 为已授权 Artifact 引用/可用下载能力，不能把 Worker 工作目录文件清单直接当成可下载链接。未收集或已过期的文件明确不可用。
- 全量日志归档/下载、指标时序、批量下载、资料库归档动作分别列 TARGET，现有环形日志与终值不足时不伪造数据；若后续实施，复用对象存储、retention/owner 规则，不新建平行存储。

**任务分解（批次 D）**：
1. `GET/POST /runs/{run_id}/notes`：追加式 note（note_id、author_kind、request_id 幂等、created_at、content ≤4000 字符）；owner/session 校验；Agent 备注标记为解释/建议，不修改原日志、指标或 PASS/FAIL 结论（改动入口 `nexus_run_service.py`、`nexus_proxy.py`、`nexus_internal.py`）。
2. 必要时注册同权限 note 工具；author_kind 区分用户与 Agent 备注。
3. run detail 的 artifacts 扩展为已授权 Artifact 引用/可用下载能力；未收集或已过期如实不可用，不把 Worker 工作目录清单当下载链接。
4. 全量日志归档/下载、指标时序、批量下载、资料库归档仍列 TARGET，另行排期；随后继续 NX-S1/E4/P1/P2。

### 9.7 后端实施顺序、模块和验收交接

1. **准备/收尾** ✅：H1/R1a 已于 09-07 部署（0ea84612 线），批次 A/B 已基于该基线完成离线测试与线上验收；批次 C/D 实施前仍须重新核对质量审查遗留项，未关闭的不宣称完成。
2. **批次 A＝LB1** ✅ 已提交部署（2026-09-08，6eb8b361→fa4bceed 线上验证）：preset 投影→显式数据迁移→运行名称/稳定序号/配置快照→列表详情扩展。给前端可消费契约，首版即可接固定切换器和运行标题。证据见[验收记录](验收记录/NX-LB1_LB2_验收_2026-09-08.md)。
3. **批次 B＝LB2** ✅ 已提交部署（2026-09-08，同上）：提案版本化→参数 schema/编译→审批待办恢复/失效→执行冻结→指标基线校验；线上真实 Worker E2E 31/31（提案→审批→执行→冻结命令逐字→报告 EXPLORATORY→旧票失效 409），途中修复 lr_decay 下限与 eval_interval 钳制。同上验收记录。
4. **批次 C＝LB3＋LB4** ✅ 本地完成（2026-09-08，未提交未部署）：运行引用→有界上下文→同线程并发/幂等→查询/取消/提案工具（§9.4/§9.5 任务分解）；以同一研究会话完整后端链验收。证据见[验收记录](验收记录/NX-LB3_LB4_LB5_验收_2026-09-08.md)。
5. **批次 D＝LB5** ✅ 本地完成（2026-09-08，未提交未部署）：备注和真实 Artifact 关联（§9.6 任务分解）；全量日志、时序数据另排。随后继续 NX-S1/E4/P1/P2，本次预置环境参数化不代表通用环境构建/A-B 已完成。

改动入口：Backend `nexus_proxy.py`/`nexus_internal.py`/`nexus_run_service.py` 负责外部授权、引用解析、运行元数据；Runtime `main.py`/`request_scope.py`/`approvals.py`/`tools/reproduction.py` 负责会话、提案、票据与工具；必要新增职责单一的提案服务与运行上下文服务。Worker 仅在 LB2 参数契约需要时最小扩展，保持原 preset 与资源/网络边界。测试放对应现有 nexus 域，不创建新通用框架。

数据只进 Nexus 自有域，Artifact 文件复用现有媒体对象存储。新增字段/表采用显式、可重入、带回退说明的 Nexus 域迁移步骤；仅改 CREATE TABLE IF NOT EXISTS 不能升级线上旧表，禁止启动时隐式更改 schema。旧运行配置无法恢复时保留 unknown，不从当前 preset 倒灌成历史事实。老客户端兼容原查询形状；新写入接口不接受未声明字段。

统一验收矩阵：owner/session/Research 模式、状态失联、参数注入、版本竞争、审批重放、取消目标/授权、日志脱敏、断流重试、迁移前后与旧客户端兼容。先离线合成测试、再明确授权环境的实际接口/Worker 验证；不调真实付费模型做自动测试。每批交接 OpenAPI/请求响应样例、错误码、迁移/回退步骤、测试证据和未验证项。安装依赖、提交推送及部署仍按 AGENTS.md 单独授权。

## 10. 历史附录

[M0–M5 完整历史快照](CodeNexus_P2开发计划_历史快照_2026-09-05.md)保留原任务与 §十四验收；[验收记录目录](验收记录/)保留原证据。本次不改历史结果，M1 四工具数字不再出现在当前快照。
