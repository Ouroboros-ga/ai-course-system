# CodeNexus P2 开发计划（P1 收尾后的前后端实施路线）

> **日期**：2026-09-04
> **定位**：[CodeNexus转型落地计划.md](CodeNexus转型落地计划.md) §六（P1-W Repro Worker + P1-C 会话持久化）收尾之后的前后端开发主线。
> **词汇约定**：本文的"P2"指落地计划 P1 之后的主线阶段；与设计文档 v1.2 第四部分的 P2（GPU Compute / 多云）不同，后者归入本文 §十一 P2+ 候选池。里程碑记为 **M0-M5**，避免与下线节奏 S0-S3、功能范围 P0/P1/P2 混淆。
> **依据**：[CodeNexus\_转型设计与实施方案\_v1.2.md](CodeNexus_转型设计与实施方案_v1.2.md)（产品边界与工程原则 §12-§20、Phase 12 演示链）、[Nexus\_AI\_前端开发规格与UX落地说明.md](Nexus_AI_前端开发规格与UX落地说明.md)（前端契约与缺陷清单 D1-D8、问题 Q1-Q8）。
> **部署目标**：新机 103.36.223.177（域名 zsitai.xyz）；旧机待退租。服务面：backend(8000) / nexus-runtime(8300) / repro-worker(8400) / postgres(5432) / searxng(8888) / judge0 / paddleocr。
> **状态**：随实施进度更新；✅ 完成 / 🔄 进行中 / ⏸️ 待启动。
> **当前进度（2026-09-05 二次修订）**：**M0 全部完成**（D1 工具收敛已部署生效、
> D3 `.env.example` 对齐、P1-C1/C2/C3 与 nanoGPT 复测均有线上实证）；**M1 全部
> 完成**（mode/context 两层透传、双 Profile 工具白名单、SSE error、结构化
> tool\_result、todo 规则移除、Stop 核实；线上验收记录见
> `docs/phase1/验收记录/M1_验收_2026-09-05.md`）。下一主线是
> M2（Course/CS RAG 知识接入），随后依次完成 Artifact、复现结果展示和最终演示链。

***

## 一、当前快照（2026-09-05 后端实证修订）

**已就绪（不再展开）**：

- Harness：deepagents 0.7.12 + SummarizationMiddleware（Compact）+ AsyncPostgresSaver（独立 schema `nexus_checkpoints`，P1-C1 完成）；真实 systemctl restart 后会话列表 6 条、历史 2 轮可恢复；

- 双端 SSE：Backend 反代（`/api/v1/nexus/{health,chat,chat/stream}`，双令牌边界、`X-Accel-Buffering: no`）+ 前端 fetch/ReadableStream 消费（契约测试 89/89）；

- 权限门控：`platform.nexus.use`（迁移 0068，默认全量授权 + 可按用户撤销 + 授权管理入口）；

- 工具四件套：`web_search`（SearXNG 主 + DDG 降级）/ `search_arxiv_papers` / `plan_reproduction` / `run_reproduction`（fail-closed）；

- Repro Worker：容器部署完成（torch 镜像、iptables 出站白名单、License 三源校验、单测 7/7）；nanoGPT 端到端 succeeded 5/5，val loss 1.8857，900s 硬截止已实证；

- 前端：三栏工作区 v2.2（演示/真实双数据源、能力三态单一真相源 `nexusCapabilities.js`、Approval Gate、图标轨 + 抽屉）。

**对照设计文档 Phase 12 比赛演示链的缺口**（本计划的全部内容来源）：

| 演示链环节                        | 现状                                                     | 缺口                                                                        |
| ---------------------------- | ------------------------------------------------------ | ------------------------------------------------------------------------- |
| 进入 Nexus AI → 普通模式           | 前端 Mode UI 完备                                          | `mode` 字段被两层 pydantic 静默丢弃（D2）；General 模式可调 Research 工具与 `execute`（Q7/D1） |
| CS / Course RAG + Web        | `course_materials=wired`、`cs_knowledge=unwired`        | 无课程检索工具、无 CS 检索工具、`context.course_id` 不入链路                                |
| 生成 Artifact                  | 前端仅演示数据                                                | Runtime 无 artifact 工具、无存储、无下载                                             |
| 切换 Research → Paper Research | arXiv 元数据检索已通                                          | 全文/证据级 paper research 未评估（paper-qa，见 §十一）                                 |
| Quick Reproduction           | Worker 已部署；nanoGPT 后端端到端 succeeded 5/5，val loss 1.8857 | 前端仍未展示 job 阶段、指标和报告；需补结果查询与 artifact 展示                                   |
| Reproduction Report          | —                                                      | 报告非 artifact、无下载链路、前端无展示                                                  |

**运行时已知缺陷对账**（前端规格 §8，2026-09-04 复核）：

| 编号 | 缺陷                                                                                             | 状态                                                                                                         | 归属             |
| -- | ---------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- | -------------- |
| D1 | 默认 Deep Agent 挂载 `execute`/文件工具，无沙箱无审批，且 Runtime 已公网可达（经 zsitai.xyz 反代，web\_search 结果可被用于提示注入） | ✅ 已修（2026-09-04，M0-B1；severity 勘误见前端规格 §8：StateBackend 落 LangGraph state 非宿主 cwd，`execute` 调用即错，但暴露面修复仍必要） | **M0（安全 P0）**  |
| D2 | `mode` 与 `context.course_id` 在 proxy 与 runtime 两层被丢弃                                           | 未修                                                                                                         | M1             |
| D3 | `.env.example` 变量名与 `env_prefix="NEXUS_"` 不一致                                                  | 未修                                                                                                         | M0             |
| D4 | `tool_result` 600 字符硬截断导致 JSON 残缺                                                              | 未修                                                                                                         | M1             |
| D5 | 无 SSE `error` 事件，流中断前端停在"进行中"                                                                  | 未修                                                                                                         | M1             |
| D6 | SYSTEM\_PROMPT 要求 todo，运行时无 todo 工具                                                            | 未修                                                                                                         | M1             |
| D7 | `done.token_count` 统计字符数                                                                       | 未修                                                                                                         | P2+（前端不展示，不阻塞） |
| D8 | 会话不持久化                                                                                         | ✅ 已解（P1-C1：真实 systemctl restart 后恢复会话与历史）                                                                  | —              |

**关键机制核实**（2026-09-04 实测 deepagents 0.7.12 源码，决定修法）：

- `HarnessProfile.excluded_tools` + `_ToolExclusionMiddleware`：模型请求侧过滤工具 + 工具调用侧拒绝执行（双层防御，原生能力，零自研）；

- `deepagents/middleware/permissions.py` + `_fs_interrupt.py`：原生审批门（interrupt\_on 等价物，后续扩展用）；

- 即设计文档 §4 的"General Profile / Research Profile"有现成实现载体，`nexus/src/nexus/agent.py` 当前未传 profile，这正是 D1 的根因。

***

## 二、总体原则

1. **演示链优先**：M0→M4 的顺序即设计文档 Phase 12 演示链的补全顺序；与演示链无关的优化一律进 §十一 P2+ 候选池。
2. **里程碑驱动**：沿用落地计划口径，不用日历日期；每里程碑有验收、可回退（代码 revert，表结构不动）。
3. **最少自研**（设计文档 §12-§16）：模式切换 = 两个 HarnessProfile；工具收敛 = `excluded_tools`；审批 = permissions 中间件。不自研 Agent Runtime 能力。
4. **诚实性**：前端能力三态只在真实复测通过后翻转（`nexusCapabilities.js` 是唯一开关）；每里程碑验收记录归档至 `docs/phase1/验收记录/`。
5. **数据分域**（AGENTS.md §4.1.11）：checkpoint/todo/artifact 元数据进 Nexus 域；artifact 文件复用既有媒体/文档域（object\_key），不新建平行存储；业务数据不复制进 Runtime。
6. **权限边界**（AGENTS.md §4.1.6）：Runtime 侧课程检索以用户身份经 `course_access_service` 校验，不绕过 Course Access；内部端点用服务令牌 + 用户身份双重校验。

***

## 三、里程碑总览

| 里程碑    | 主题           | 核心交付                                                                           | 预估    | 状态               |
| ------ | ------------ | ------------------------------------------------------------------------------ | ----- | ---------------- |
| **M0** | 安全加固 + P1 收尾 | D1 工具收敛、P1-C1/C2/C3 会话持久化/列表/隔离、nanoGPT 端到端复测                                  | 2-3 天 | ✅ 完成（2026-09-05） |
| **M1** | 模式真实化        | `mode`/`context` 透传、双 Profile 工具白名单、SSE error 事件、tool\_result 结构化、todo 修正、Stop | 3-4 天 | ✅ 完成（2026-09-05） |
| **M2** | 知识接入         | 课程资料检索工具 + CS 知识库工具 + 引用元数据；两能力翻 `ready`                                       | 4-5 天 | ✅ 完成（2026-09-05） |
| **M3** | Artifact 真实化 | `write_artifact` 工具 + 存储（复用媒体/文档域）+ 下载 + 前端产物卡                                 | 3-4 天 | ⏭️ 下一主线          |
| **M4** | 复现体验闭环       | job 进度查询 + 阶段状态 + 复现报告 artifact 化 + 前端复现状态卡                                    | 2-3 天 | ⏸️               |
| **M5** | 下线与可靠性       | S3 执行（按落地计划 §五）、Harness 压力套件、文档同步                                              | 2-3 天 | ⏸️               |

合计约 3 周量级。**M0/M1 必须先于任何对外演示完成**（分别是安全底线与诚实性底线）；M2-M4 补全 Phase 12 演示链；M5 收尾。

***

## 四、M0：安全加固与 P1 收尾

### 4.1 后端

| 任务      | 内容                 | 输出                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | 验收                                             | 依赖          | <br /> |
| ------- | ------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- | ----------- | :----- |
| M0-B1 ✅ | **D1 工具收敛（安全 P0）** | 已实施（2026-09-04，本地验收通过）：三层防御——① `FilesystemMiddleware(tools=["read_file"])` 同名替换默认实例（危险工具结构性不创建，`read_file` 保留供 Compact 读回）；② `HarnessProfile(excluded_tools)` 注册 provider 键 `openai`（模型侧过滤 + 调用侧拒绝）；③ `GeneralPurposeSubagentProfile(enabled=False)` 移除 GP 子代理与 `task`。验收：`tests/test_agent_tools.py` 5/5（注册表 = read\_file+四产品工具、模型可见面同、敌意 tool\_call 全拒、排除层兜底直测）；全量 34/34；`/health` 增 `tool_surface` 字段（uvicorn 冒烟实测 5 工具）。**✅ 已部署生效（2026-09-05，health 按模式上报双工具面）** | 见左                                             | 见左          | 无      |
| M0-B2 ✅ | D3 修正              | `.env.example` 全部变量对齐 `env_prefix="NEXUS_"`（如 `NEXUS_DEEPSEEK_API_KEY`）；补 `NEXUS_REPRO_WORKER_TOKEN`/`NEXUS_API_KEY` 占位                                                                                                                                                                                                                                                                                                                                              | 单测断言 example 中每个非空变量名可被 `Settings` 识别（3 条契约测试） | 无           | <br /> |
| M0-B3 ✅ | **P1-C2 会话列表 API** | Runtime：`GET /api/v1/nexus/sessions` 按用户过滤并返回标题；已实证跨用户隔离（stu102 看不到 stu101 会话与历史）。                                                                                                                                                                                                                                                                                                                                                                                   | 会话列表、标题、隔离契约通过                                 | M0-B1（同批部署） | <br /> |
| M0-V1 ✅ | **nanoGPT 真实复现复测** | 新机 Worker 真实重放：端到端 succeeded 5/5，val loss 1.8857，License 三源 fail-closed，900s 硬截止。                                                                                                                                                                                                                                                                                                                                                                                    | 真实结果与日志已归档；前端能力状态暂不因后端完成自动翻转，等待展示链路            | 无           | <br /> |

### 4.2 前端

| 任务       | 内容                    | 输出                                                                                   | 验收                                                                  | 依赖         |
| -------- | --------------------- | ------------------------------------------------------------------------------------ | ------------------------------------------------------------------- | ---------- |
| M0-F1 ✅  | **P1-C3 前端会话切换**      | rail 会话列表真实模式读 sessions API；本地 localStorage 会话与服务器会话合并显示；点击切换 `session_id` 并读取 PG 历史 | 后端已实证重启恢复与历史投影；前端 API 链路实测通过（`M1_验收_2026-09-05.md`），浏览器手工点击建议演示前过一遍 | M0-B3      |
| M0-F2 ⏸️ | `nexuslab_repro` 状态重估 | 后端执行能力已通过，但前端 `ready` 只能在 job 查询、指标和报告展示接通后翻转；在此之前保持 `wired`/`unwired` 的诚实状态         | 真实演示可看到 queued→完成、指标与报告下载                                           | M0-V1 + M4 |

**M0 回退**：前后端各自 revert 单提交；threads 表新增列为兼容演进，无需回滚迁移。

***

## 五、M1：模式真实化与服务端工具白名单

对应设计文档 Phase 2 验收原文："General 看不到 Research-only Tool；Research 可以正常使用 Research-only Tool"，以及前端规格 Q7（mode 语义强度 = 硬约束）。

### 5.1 后端（Nexus Runtime + Backend 反代）

| 任务      | 内容                  | 输出                                                                                                                                                                                                        | 验收                                                                                                            | 依赖    |
| ------- | ------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- | ----- |
| M1-B1 ✅ | D2 字段透传             | 两层 `ChatRequest`（`nexus_proxy.py` + `main.py`）各加 `mode: str \| None`、`context: dict \| None`；proxy 的 `model_dump()` 已自动透传，无需改转发逻辑                                                                         | 契约测试：`POST /chat` 带 `mode`/`context`，Runtime 侧收到的 body 含两字段                                                   | 无     |
| M1-B2 ✅ | **双 Profile 工具白名单** | 构建两个 DeepAgent 实例共享同一 PostgresSaver 与 thread 命名空间：`general` profile = 排除全部文件/执行工具 **+ research-only 三工具**（arxiv/plan\_repro/run\_repro）；`research` profile = 仅排除文件/执行工具。请求按 `mode` 选实例；`_agent` 单例改为按模式索引 | General 请求中模型调用 `search_arxiv_papers` 被拒；Research 正常；同 session 切模式后上下文连续（不换会话）；research prompt 仅轻微差异（设计文档 §4） | M1-B1 |
| M1-B3 ✅ | D5 SSE error 事件     | `_agent_stream` 包 `try/except`，异常产出 `event: error` + 稳定错误码；`done`/`error` 互斥；Agent 抛异常不再裸断流                                                                                                               | 单测注入失败工具，断言流尾为 error 事件且含错误码                                                                                  | 无     |
| M1-B4 ✅ | D4 tool\_result 结构化 | `tool_result` 事件增结构化 `items` 字段（列表，按 item 边界截断），`content` 保留为兜底；删除裸 `[:600]` JSON 腰斩                                                                                                                      | 前端 `sessionSources` 的 `unparsable` 计数归零（前端哨兵已就位，无需前端改动）                                                       | 无     |
| M1-B5 ✅ | D6 todo 一致性         | 核实 deepagents 0.7.12 todo middleware 可注册性：可注册则挂载并让前端"执行过程"消费真实勾选事件；不可行则删除 SYSTEM\_PROMPT 规则 4（诚实性优先，不虚构进度）                                                                                                | prompt 与工具面一致；前端不展示任何未经事件确认的进度                                                                                | 无     |
| M1-B6 ✅ | Stop/Cancel 语义      | 客户端断开 → StreamingResponse generator 取消 → `astream` 任务取消（uvicorn 原生行为）；中途取消不产出假 `done`；checkpointer 状态保持到中断点可续                                                                                             | `curl --no-buffer` 断开后服务端无悬挂任务日志；续聊不重复回答                                                                      | 无     |

### 5.2 前端

| 任务      | 内容                     | 验收                                                                    | 依赖    |
| ------- | ---------------------- | --------------------------------------------------------------------- | ----- |
| M1-F1 ✅ | error 事件渲染分支           | 失败轮显示稳定错误码 + 重试入口，不再停在"进行中"                                           | M1-B3 |
| M1-F2 ✅ | Stop 按钮                | `AbortController` 中断 fetch 流；UI 转入"已停止"态；停止后可继续追问                     | M1-B6 |
| M1-F3 ✅ | Mode pills 与服务端白名单同源校验 | 契约测试断言 `NEXUS_MODE_CONFIG.tools` 与 Runtime 两 profile 的实际工具面一致（防前后端漂移） | M1-B2 |

**M1 回退**：Runtime 单提交 revert；proxy 字段透传为纯增量。

***

## 六、M2：知识接入（Course RAG + CS 知识库）

对应设计文档 Phase 3。目标模式：`Nexus Tool → Existing Backend Capability → Structured Result`，不复制知识、不重建 KB、不把数据库搬进 Runtime。

### 6.1 后端

| 任务       | 内容             | 输出                                                                                                                                                                                                                                                          | 验收                                                                          | 依赖    |
| -------- | -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- | ----- |
| M2-B1 ⏸️ | Backend 内部检索端点 | 新增服务令牌保护的内部端点：课程资料检索（复用现有 course 检索/材料能力——具体复用 `course_build` 材料接口与 Course Retrieval 端口中的哪一个，实施时按代码核定，不预虚构路径，设计文档 §18）+ CS 知识库检索（复用 `discipline-knowledge` 只读服务）。身份：请求头携带 `X-Nexus-User-Id`，端点内以该用户身份走 `course_access_service` 校验课程权限，**不绕过 Course Access** | 单测：无权限课程 403；service token 错误 401；有权限返回结构化 items（source/title/section/权威来源） | 无     |
| M2-B2 ⏸️ | Nexus 检索工具     | `search_course_materials(query)`（course\_id 由代理层从请求 `context` 固定注入，**工具内不信任模型传参**）与 `search_cs_knowledge(query)`；两工具均先做课程/角色自校验（AGENTS.md §5.1.2）；返回结构化 items，标注"课程资料（经核实）"或"CS 知识库（权威来源）"与"补充参考"的边界                                                        | 模拟 HTTP 单测；研究模式一个提问可同时触发课程 + CS + Web 三源                                    | M2-B1 |
| M2-B3 ⏸️ | 合流策略（红线）       | prompt 指引模型按相关性取舍证据，**不硬编码** **`course_score *= N`**；课程材料不相关时不得强行进入最终 context（设计文档 §5 红线）                                                                                                                                                                   | 评审：非相关课程材料不出现在回答引用中                                                         | M2-B2 |

### 6.2 前端

| <br />   | 任务               | 内容                                                                                             | 验收                 | 依赖           |
| :------- | ---------------- | ---------------------------------------------------------------------------------------------- | ------------------ | ------------ |
| M2-F1 ⏸️ | 两能力翻 `ready`     | `course_materials` → `ready`；`cs_knowledge` → `ready`（integration 注明 CS 当前为关键词检索、非向量；数据规模如实展示） | 界面自动随三态翻转变，无其他前端改动 | M2-B2 真实复测通过 |
| M2-F2 ⏸️ | 信息源面板消费结构化 items | 右栏信息源展示 items 的 source/title/section（citation 链接）；与 M1-B4 的结构化 tool\_result 对接                 | 来源面板条目可核查          | M1-B4        |

***

## 七、M3：Artifact 真实化

对应设计文档 Phase 4：不要模型输出"以下是 Word 文档内容"，要真实文件。

| 任务       | 内容                  | 输出                                                                                                                                                                                                   | 验收                              | 依赖    |
| -------- | ------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------- | ----- |
| M3-B1 ⏸️ | `write_artifact` 工具 | `write_artifact(type, title, content)`，P0 支持 `markdown` / `latex`（同为文本对象）；内容经 Backend 写入既有媒体/文档域（object\_key，**复用现有域，不新建平行存储**）；artifact 元数据（artifact\_id/type/title/location/created\_at）入 Nexus 域表 | 单测 mock 存储；真实链路产出可下载文件；元数据不落业务库 | 无     |
| M3-B2 ⏸️ | 读取与下载               | Runtime `GET /api/v1/nexus/artifacts`（当前用户列表）+ `GET .../artifacts/{id}/download`（签名 URL）；Backend 反代 + `require_nexus_use` + 本人校验                                                                     | 跨用户访问 403；下载链接含 token（硬约束）      | M3-B1 |
| M3-B3 ⏸️ | DOCX go/no-go       | 评估复用 Backend 既有文档生成能力做 docx 适配：存在且接入成本 ≤ 薄 Adapter 则做，否则记 no-go 归 P2+                                                                                                                                | 决策记录入本文档进度区                     | M3-B1 |
| M3-F1 ⏸️ | 前端产物卡               | 消息流内 artifact 卡片（类型图标 + 标题 + 下载）；左栏"本机资料"的产物行接服务器列表（真实模式）；`file_upload` 能力按新契约重估（若上传接入成本高则维持 `unwired`）                                                                                              | 演示链"生成 Artifact"环节真实可交付文件       | M3-B2 |

***

## 八、M4：复现体验闭环

对应设计文档 Phase 7 的前端呈现层与 Phase 10 交互要求（reproduction stages、report link）。

| 任务       | 内容              | 输出                                                                                                                                                            | 验收                             | 依赖    |
| -------- | --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------ | ----- |
| M4-B1 ⏸️ | job 状态查询代理      | `GET /api/v1/nexus/repro/jobs/{id}`：Backend 反代 Worker `GET /jobs/{id}`，鉴权 = job 发起人（发起时记录 user\_id）                                                           | 非发起人 403；返回 status/logs/metric | M0-V1 |
| M4-B2 ⏸️ | 阶段状态流           | `run_reproduction` 提交后在 `tool_result` 返回 job\_id + 初始状态；后续进度由前端轮询 M4-B1（SSE 不做长任务推送，避免连接占用）；阶段粒度 = Worker 现有执行切片                                              | UI 可见排队 → 构建 → 运行 → 完成/失败全过程   | M4-B1 |
| M4-B3 ⏸️ | 复现报告 artifact 化 | Worker 产物 `report.md`/`report.json` 经 `write_artifact` 入库；报告标注来源仓库与 License（AGENTS.md §4.1.10）；**PASS/FAIL 由 deterministic metric comparison 给出，不经 LLM 主观判断** | 报告含论文指标 vs 实测指标、容差、结论、日志与环境信息  | M3-B1 |
| M4-F1 ⏸️ | 前端复现状态卡         | 阶段流水（排队/构建/运行/完成）+ 轮询节流 + 失败语义显式；只展示操作状态（"正在构建环境"），**不暴露模型内部 Chain-of-Thought**（设计文档 Phase 10 红线）                                                             | 演示链末端完整闭环                      | M4-B2 |
| M4-F2 ⏸️ | 报告卡             | 复用 M3-F1 artifact 卡 + 指标对比高亮                                                                                                                                  | 报告可下载可核查                       | M4-B3 |

***

## 九、M5：S3 下线与可靠性

| 任务       | 内容                         | 验收                                                                                                                                                                | 依赖                      | <br />     |
| -------- | -------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------- | :--------- |
| <br />   | S3-B1/B2/B3 ⏸️             | 按落地计划 §五原文执行：删 `/research` 路由注册与 service、`paper_search.py` 迁入 `nexus/src/nexus/providers/`、`research_*` 表保留不 drop                                                 | 落地计划 §5.3 清单全勾          | S2 稳定（已满足） |
| M5-B2 ⏸️ | Harness 压力套件（设计文档 Phase 9） | 覆盖：多 Tool 长任务、Tool 500、Context overflow（Compact 触发实测）、Runtime restart 后 resume、Cancel、Malformed Tool、Worker timeout —— 全部产生明确状态，**禁静默成功 / LLM 编造结果 / 未执行却写 PASS** | 全绿且失败语义可断言              | M0-M4      |
| M5-D ⏸️  | 文档同步                       | 落地计划状态栏、前端规格 §8 缺陷清单翻转为已修（逐条标注修复提交）、`DOCUMENTATION_INDEX.md`、本文档进度列；**AGENTS.md 部署地址（47.99.97.154 → zsitai.xyz / 103.36.223.177）属权威规则文件，改动前向用户确认**                | 文档与代码一致（AGENTS.md §7.2） | M5-B2      |

***

## 十、比赛演示链核对表（Phase 12 → 里程碑映射）

```
进入 Nexus AI ────────────── ✅ 已有（S1）
  ↓
普通模式 ──────────────────── M1（服务端 mode 硬约束）
  ↓
CS / Course RAG + Web ─────── M2（两工具 + 引用元数据）
  ↓
生成 Artifact ─────────────── M3
  ↓
切换 Nexus Research ────────── M1（Profile 切换）
  ↓
Paper Research ────────────── ✅ 元数据级已有；全文级归 P2+ 评估
  ↓
选择一篇论文 ──────────────── ✅ plan_reproduction（nanoGPT 主选）
  ↓
Quick Reproduction ────────── ✅ Worker 已部署；M0-V1 复测
  ↓
环境构建 / 真实运行 ────────── M4（进度可见）
  ↓
Clean Verification ─────────── P2+（A/B 双环境，见 §十一）
  ↓
Reproduction Report ────────── M4（报告 artifact 化）
```

***

## 十一、P2+ 候选池（不排期、不阻塞演示链）

| 候选                               | 内容                                                                   | 前置 go/no-go 标准                                                                                                 |
| -------------------------------- | -------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| Paper Research 全文化（paper-qa 或同类） | `paper_research(question)`：多论文证据收集 + 综合 + 引用（设计文档 Phase 5）           | License 兼容；依赖与 Nexus venv 不冲突（或以独立服务形态接入，参照 Repro Worker 模式）；集成成本 ≤ 薄 Adapter。不满足则保持现状（元数据级检索），**不硬接 PaperQA** |
| Personal Context                 | 用户长期偏好记忆（设计文档 Phase 6；Mem0 / deepagents memory / 最小偏好表三选）            | 接入成本高则推迟，不阻塞主链                                                                                                 |
| Clean Verification               | A/B 双环境（开发环境修复 + 冻结环境验证），`reproducible=true` 只由 B 环境判定（设计文档 Phase 8） | 简单可靠的 freeze 方案；不为完美可复现规范拖死 Demo                                                                               |
| 模型选择器恢复                          | Runtime `/models` + 请求级 `model` 字段（前端规格 §12.5 记录的恢复前提）               | 有真实多模型需求                                                                                                       |
| D7 token 口径                      | 接真实 tokenizer                                                        | 有计费/限额 UI 需求                                                                                                   |
| Repro Worker 并发队列                | 当前串行（max\_total=1）即满足演示                                              | 多用户并发复现成为真实需求                                                                                                  |
| CS 知识库向量化                        | `discipline-knowledge` 关键词检索 → 向量检索                                  | M2 落地后按检索质量决定                                                                                                  |

***

## 十二、依赖与授权

1. **部署授权**：每里程碑本地验收后部署新机（103.36.223.177）仍需用户明确授权（AGENTS.md §3.1 规则不变）；部署面沿用迁移后的 systemd + nginx + docker compose。
2. **外部依赖**：DeepSeek Key、SearXNG、PostgreSQL 16、Repro Worker 均已在位；**本计划无新增外部付费依赖、无新增常驻服务**（M2 内部端点在既有 Backend 内）。
3. **密钥纪律**：新增服务令牌（Backend ↔ Runtime 出站方向）只存服务器 env，不入库不入仓。

***

## 十三、风险与应对

| 风险                                                   | 影响                         | 概率 | 应对                                                      |
| ---------------------------------------------------- | -------------------------- | -- | ------------------------------------------------------- |
| deepagents profile 与现有 `create_deep_agent` 调用形态不完全匹配 | M1-B2 返工                   | 低  | `excluded_tools` 双层机制已实测存在；极端情况降级为构建期双实例（本计划即按双实例设计）    |
| M2 内部检索端点扩大攻击面                                       | 越权读取课程资料                   | 中  | service token + 用户身份双重校验；端点只读；工具内再做 course/role 自校验（双层） |
| Artifact 复用媒体/文档域的改造量超预期                             | M3 延期                      | 中  | P0 只做 markdown/latex 纯文本对象；DOCX 走 go/no-go（M3-B3）       |
| 演示模式与真实模式双轨漂移                                        | 界面承诺与真实能力不符                | 低  | `nexusAdapter.js` 单一取数入口 + 契约测试锁定；真实模式演示前跑完整回归          |
| Worker 阶段不可观测                                        | M4 状态卡退化为两态                | 低  | P0 用轮询；阶段粒度 = Worker 现有日志切片，不新增推送机制                     |
| nanoGPT 复测失败（迁移后环境差异）                                | `nexuslab_repro` 不能翻 ready | 低  | 保留真实错误日志修复后重测；前端状态保持 `unwired`（诚实性优先）                   |

***

## 十四、进度追踪约定

### 14.1 2026-09-05 后端实证修订

以下结果视为已完成基线，不再作为待启动任务重复排期：

- **P1-W W1-W5**：nanoGPT 端到端 `succeeded 5/5`，val loss `1.8857`（接近预期）；License 三源校验 fail-closed；900 秒硬截止生效。

- **P1-C1**：真实 `systemctl restart` 后会话列表恢复 6 条、历史恢复 2 轮。

- **P1-C2**：会话标题由首条消息截断生成；`stu102` 看不到 `stu101` 的会话和历史。

- **P1-C3**：契约 `89/89` 与 build 通过；历史投影为 `[(user,14),(assistant,81),(user,10),(assistant,94)]`。

因此，后续执行重点从“验证后端是否存在”转为“把已验收后端能力接入真实 Nexus 前端体验”，优先顺序固定为：

1. 收尾 M0：`.env.example`、真实会话列表/切换与历史恢复。
2. 执行 M1：让 `mode`、`context.course_id` 成为 Runtime 硬约束，并补 SSE 错误、取消和工具结果结构化。
3. 执行 M2：先接 Course RAG，再接 CS Knowledge RAG，最后做三源相关性合流验收。
4. 执行 M3：先实现 Markdown Artifact，再评估 LaTeX/DOCX；文件下载和跨用户隔离必须同时完成。
5. 执行 M4：接通复现 job 查询、指标、报告和前端状态卡；在此之前 `nexuslab_repro` 不翻为 `ready`。
6. 执行 M5：完成真实演示链、可靠性套件和 Legacy S3 下线评审。

### 14.2 2026-09-05 M0/M1 完成记录

- **M0**：全部完成并部署生效。D1 工具收敛线上工具面 = 双模式健康上报；
  D3 `.env.example` 契约测试 3 条；P1-C 全项与 nanoGPT 复测见
  `验收记录/P1_验收_2026-09-05.md` 与 `验收记录/服务器迁移_2026-09-04.md`。

- **M1**：全部完成并部署生效（提交 `f10cb569`，部署 release `e49e9a61`）。
  线上实证：双 Profile 工具面（general=read\_file+web\_search / research=
  read\_file+四产品工具）、同 session 跨模式上下文连续（general 提问后
  research 追问正确引用上一轮并调 arXiv+web 双工具）、真实 web\_search 的
  tool\_result 携带结构化 items（8 条，content 2510 字符完整合法 JSON）、
  SSE error 互斥契约（单测注入）。验收记录：
  `docs/phase1/验收记录/M1_验收_2026-09-05.md`。

- 已知边界：error 事件未做线上人工触发（不为验收故意打挂生产链路，以单测
  为准）；浏览器手工点击（会话切换/Stop/error 展示）建议演示前过一遍。

### 14.3 2026-09-05 M2 完成记录

- **M2**：全部完成并部署生效（提交 `cfda63ef`，release `cfda63ef`，
  新增服务器配置 `NEXUS_INTERNAL_TOKEN`）。线上实证：内部端点四态
  （503/401/403/200，200 路径返回真实课程证据与 CS 权威条目）、
  stu101 无权限端到端诚实拒绝（`COURSE_ACCESS_DENIED`，模型零编造）、
  CS 检索成功路径（模型正确引用《算法导论》来源）。验收记录：
  `docs/phase1/验收记录/M2_验收_2026-09-05.md`。

- 环境事实：唯一课程真实 id=15；course\_memberships 仅 user 9/1（stu101/102
  演示账号未入课）——演示"课程资料成功检索"需用已入课账号。

- 每完成一个里程碑：更新本文档 §三 状态列与任务表标记、落地计划 §九 进度追踪、`DOCUMENTATION_INDEX.md`；

- 验收记录归档至 `docs/phase1/验收记录/M{N}_{日期}.md`，含操作步骤、预期、实际、日志/截图、判定；

- 失败保留完整错误日志，不假造成功（AGENTS.md §4.3）。

***

## 附录：关键改动面（按仓库位置）

| 位置                                              | 里程碑         | 改动性质                                                                           |
| ----------------------------------------------- | ----------- | ------------------------------------------------------------------------------ |
| `nexus/src/nexus/agent.py`                      | M0/M1       | profile/excluded\_tools、双实例构建                                                  |
| `nexus/src/nexus/main.py`                       | M0/M1/M3/M4 | sessions 端点、ChatRequest 字段、error 事件、结构化 tool\_result、artifacts 端点、repro job 端点 |
| `nexus/src/nexus/tools/`                        | M2/M3       | 新增 course/cs 检索工具、write\_artifact                                              |
| `nexus/src/nexus/persistence.py`                | M0          | threads 表增列（title/mode）                                                        |
| `backend/app/api/v1/endpoints/nexus_proxy.py`   | M0/M1/M3/M4 | 反代新端点、ChatRequest 字段                                                           |
| `backend/app/api/v1/endpoints/`（内部检索端点）         | M2          | 新增 service-token 端点                                                            |
| `frontend/src/api/nexusCapabilities.js`         | M0/M2       | 能力状态翻转（唯一开关）                                                                   |
| `frontend/src/api/nexusAdapter.js` / `nexus.js` | M0/M1/M3/M4 | 真实模式数据源扩展                                                                      |
| `frontend/src/app/pages/nexus/NexusPage.vue`    | M0/M1/M4    | 会话列表、error 分支、Stop、复现状态卡（均不改变三栏组件类型）                                           |

