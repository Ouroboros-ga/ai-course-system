> **历史快照（2026-09-05，v1.3 清理前）**：仅供追溯，不作为当前实现、工具面或开发指令。现行入口：[v1.3 架构](CodeNexus_转型设计与实施方案_v1.3.md)、[开发计划](CodeNexus_P2开发计划.md)、[前端规格](Nexus_AI_前端开发规格与UX落地说明.md)。下文旧默认模式、审批、License、分支和状态描述可能已被纠正。

# CodeNexus P2 开发计划（P1 收尾后的前后端实施路线）

> **日期**：2026-09-04
> **定位**：[CodeNexus转型落地计划.md](CodeNexus转型落地计划.md) §六（P1-W Repro Worker + P1-C 会话持久化）收尾之后的前后端开发主线。
> **词汇约定**：本文的"P2"指落地计划 P1 之后的主线阶段；与设计文档 v1.2 第四部分的 P2（GPU Compute / 多云）不同，后者归入本文 §十一 后续主线与可选增强。里程碑记为 **M0-M5**，避免与下线节奏 S0-S3、功能范围 P0/P1/P2 混淆。
> **依据**：[CodeNexus\_转型设计与实施方案\_v1.2.md](CodeNexus_转型设计与实施方案_v1.2.md)（产品边界与工程原则 §12-§20、Phase 12 演示链）、[Nexus\_AI\_前端开发规格与UX落地说明.md](Nexus_AI_前端开发规格与UX落地说明.md)（前端契约与缺陷清单 D1-D8、问题 Q1-Q8）。
> **部署目标**：新机 103.36.223.177（域名 zsitai.xyz）；旧机待退租。服务面：backend(8000) / nexus-runtime(8300) / repro-worker(8400) / postgres(5432) / searxng(8888) / judge0 / paddleocr。
> **状态**：随实施进度更新；✅ 完成 / 🔄 进行中 / ⏸️ 待启动。
> **当前进度（2026-09-05 讨论纠偏汇总）**：**M0-M5 完成的是已验收 MVP 范围**。最终产品仍需 Harness Planning/Todo/Subagent、八格式附件与图片直传、Paper Research、Paper-to-Reproduction、Sandbox A/B、Experiment Console 和服务端 Session/Execution History。以上纳入 §十一必要建设主线；特定开源组件可以 no-go，产品目标不能因此被删除。保留 nanoGPT preset 稳定演示，不宣称完整论文研究/复现平台已完成。

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

| 演示链环节                        | 现状                                                                                     | 缺口                                                                      |
| ---------------------------- | -------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| 进入 Nexus AI → 普通模式           | 前端 Mode UI 完备；M1 双 Profile 已上线                                                         | `mode` 已成为服务端硬约束；剩余是持续观察工具面与异常路径                                        |
| CS / Course RAG + Web        | `course_materials=ready`、`cs_knowledge=ready`                                          | 课程与 CS 检索已接通；剩余是持续检索质量与冷启动延迟优化                                          |
| 生成 Artifact                  | M3 已上线：write\_artifact、对象存储、元数据、列表/下载、前端产物卡均已实证                                        | 删除端点未做；file\_upload 仍未接入                                                |
| 切换 Research → Paper Research | 当前只有 Paper Search（arXiv 元数据检索），且没有 Paper PDF Intake                                    | **Paper Research 尚未完成**：缺 PDF 导入、全文阅读、证据收集、方法比较、综合回答和可核查 Citation；见 §十一 |
| Quick Reproduction           | 已完成受控预设驱动 MVP：Worker 已部署；nanoGPT 后端端到端 succeeded 5/5，val loss 1.8857；前端可查询 job、展示阶段与结果 | 尚未扩展为 Paper-to-Reproduction Pipeline（论文解析、仓库定位、环境构建、修复、A/B 清洁验证）        |
| Reproduction Report          | M4 ✅：报告由 Worker 结果确定性生成并 artifact 化，可下载、可复算、可核验                                        | 完整论文复现报告仍需等待 Paper Research 与 Clean Verification 能力接入                   |

**运行时已知缺陷对账**（前端规格 §8，2026-09-04 复核）：

| 编号 | 缺陷                                                                                             | 状态                                                                                                         | 归属             |
| -- | ---------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- | -------------- |
| D1 | 默认 Deep Agent 挂载 `execute`/文件工具，无沙箱无审批，且 Runtime 已公网可达（经 zsitai.xyz 反代，web\_search 结果可被用于提示注入） | ✅ 已修（2026-09-04，M0-B1；severity 勘误见前端规格 §8：StateBackend 落 LangGraph state 非宿主 cwd，`execute` 调用即错，但暴露面修复仍必要） | **M0（安全 P0）**  |
| D2 | `mode` 与 `context.course_id` 在 proxy 与 runtime 两层被丢弃                                           | ✅ 已修（M1）                                                                                                   | —              |
| D3 | `.env.example` 变量名与 `env_prefix="NEXUS_"` 不一致                                                  | ✅ 已修（M0）                                                                                                   | —              |
| D4 | `tool_result` 600 字符硬截断导致 JSON 残缺                                                              | ✅ 已修（M1）                                                                                                   | —              |
| D5 | 无 SSE `error` 事件，流中断前端停在"进行中"                                                                  | ✅ 已修（M1）                                                                                                   | —              |
| D6 | SYSTEM\_PROMPT 要求 todo，运行时无 todo 工具                                                            | ✅ 已修（M1，移除不一致规则）                                                                                           | —              |
| D7 | `done.token_count` 统计字符数                                                                       | 未修                                                                                                         | P2+（前端不展示，不阻塞） |
| D8 | 会话不持久化                                                                                         | ✅ 已解（P1-C1：真实 systemctl restart 后恢复会话与历史）                                                                  | —              |

**关键机制核实**（2026-09-04 实测 deepagents 0.7.12 源码，决定修法）：

- `HarnessProfile.excluded_tools` + `_ToolExclusionMiddleware`：模型请求侧过滤工具 + 工具调用侧拒绝执行（双层防御，原生能力，零自研）；

- `deepagents/middleware/permissions.py` + `_fs_interrupt.py`：原生审批门（interrupt\_on 等价物，后续扩展用）；

- 即设计文档 §4 的"General Profile / Research Profile"有现成实现载体，`nexus/src/nexus/agent.py` 当前未传 profile，这正是 D1 的根因。

***

## 二、总体原则

1. **保留 MVP、继续产品建设**：M0→M5 证明受控演示链，不等于原 Phase 12 全部目标；今天确认的必要能力按 §十一推进，不因超出旧演示范围而降为永久可选。
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
| **M3** | Artifact 真实化 | `write_artifact` 工具 + 存储（复用媒体/文档域）+ 下载 + 前端产物卡                                 | 3-4 天 | ✅ 完成（2026-09-05） |
| **M4** | 复现体验闭环       | job 进度查询 + 阶段状态 + 复现报告 artifact 化 + 前端复现状态卡                                    | 2-3 天 | ✅ 完成（2026-09-05） |
| **M5** | 下线与可靠性       | S3 执行（按落地计划 §五）、Harness 压力套件、文档同步                                              | 2-3 天 | ✅ 完成（2026-09-05） |

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

| 任务      | 内容                    | 输出                                                                                   | 验收                                                                  | 依赖         |
| ------- | --------------------- | ------------------------------------------------------------------------------------ | ------------------------------------------------------------------- | ---------- |
| M0-F1 ✅ | **P1-C3 前端会话切换**      | rail 会话列表真实模式读 sessions API；本地 localStorage 会话与服务器会话合并显示；点击切换 `session_id` 并读取 PG 历史 | 后端已实证重启恢复与历史投影；前端 API 链路实测通过（`M1_验收_2026-09-05.md`），浏览器手工点击建议演示前过一遍 | M0-B3      |
| M0-F2 ✅ | `nexuslab_repro` 状态重估 | 后端执行能力与 M3 Artifact 已通过；前端 `ready` 仍等待 M4 job 查询、指标和报告展示接通后翻转                        | 真实演示可看到 queued→完成、指标与报告下载                                           | M0-V1 + M4 |

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

| 任务      | 内容             | 输出                                                                                                                                                                                                                                                          | 验收                                                                          | 依赖    |
| ------- | -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- | ----- |
| M2-B1 ✅ | Backend 内部检索端点 | 新增服务令牌保护的内部端点：课程资料检索（复用现有 course 检索/材料能力——具体复用 `course_build` 材料接口与 Course Retrieval 端口中的哪一个，实施时按代码核定，不预虚构路径，设计文档 §18）+ CS 知识库检索（复用 `discipline-knowledge` 只读服务）。身份：请求头携带 `X-Nexus-User-Id`，端点内以该用户身份走 `course_access_service` 校验课程权限，**不绕过 Course Access** | 单测：无权限课程 403；service token 错误 401；有权限返回结构化 items（source/title/section/权威来源） | 无     |
| M2-B2 ✅ | Nexus 检索工具     | `search_course_materials(query)`（course\_id 由代理层从请求 `context` 固定注入，**工具内不信任模型传参**）与 `search_cs_knowledge(query)`；两工具均先做课程/角色自校验（AGENTS.md §5.1.2）；返回结构化 items，标注"课程资料（经核实）"或"CS 知识库（权威来源）"与"补充参考"的边界                                                        | 模拟 HTTP 单测；研究模式一个提问可同时触发课程 + CS + Web 三源                                    | M2-B1 |
| M2-B3 ✅ | 合流策略（红线）       | prompt 指引模型按相关性取舍证据，**不硬编码** **`course_score *= N`**；课程材料不相关时不得强行进入最终 context（设计文档 §5 红线）                                                                                                                                                                   | 评审：非相关课程材料不出现在回答引用中                                                         | M2-B2 |

### 6.2 前端

| <br />  | 任务               | 内容                                                                                             | 验收                 | 依赖           |
| :------ | ---------------- | ---------------------------------------------------------------------------------------------- | ------------------ | ------------ |
| M2-F1 ✅ | 两能力翻 `ready`     | `course_materials` → `ready`；`cs_knowledge` → `ready`（integration 注明 CS 当前为关键词检索、非向量；数据规模如实展示） | 界面自动随三态翻转变，无其他前端改动 | M2-B2 真实复测通过 |
| M2-F2 ✅ | 信息源面板消费结构化 items | 右栏信息源展示 items 的 source/title/section（citation 链接）；与 M1-B4 的结构化 tool\_result 对接                 | 来源面板条目可核查          | M1-B4        |

***

## 七、M3：Artifact 真实化

对应设计文档 Phase 4：不要模型输出"以下是 Word 文档内容"，要真实文件。

### 7.0 实现路径（2026-09-05 按代码核定细化）

**数据域划分**（AGENTS.md §4.1.11/§4.1.7）：

- 文件字节 → 既有对象存储（`object_storage.py`，同一存储根），object\_key 前缀
  `nexus-artifacts/u{user_id}/{artifact_id}.{md|tex}`；metadata 只存 object\_key；

- 元数据 → `nexus_checkpoints.nexus_artifacts`（PG-only 域表，ai\_course\_app
  可读写；涉表断言由线上验收覆盖，不为 SQLite 测试引擎做方言分支）。

**M3-B1 ✅（代码完成）write\_artifact 工具 + 内部写端点**：

- Runtime `tools/artifact.py`：`write_artifact(type, title, content)`，type 白名单
  `{markdown, latex}`、title≤120、content≤512KB → Backend
  `POST /api/v1/nexus-internal/artifacts`（service token + X-Nexus-User-Id，
  M2 同款三重校验）；未配置/失败 → `ARTIFACT_UNAVAILABLE`（fail-closed，
  "不得声称文件已生成"）；

- Backend 写端点：入参同源校验 → `storage.put` → 元数据入库 → 返回 artifact\_id；

- M1-B4 结构化：`_ITEM_FIELD_BY_TOOL` 增 `write_artifact → artifact`（单条目），
  前端 tool\_result items 直出产物卡。

**M3-B2 ✅（代码完成，偏离原文已记录）列表与下载**：

- **偏离**：计划原文为 "Runtime GET /artifacts + download + Backend 反代"；
  核定后改为 **Backend 原生路由直读** **`nexus_artifacts`**——同库不同连接
  （P1 属主转移后 ai\_course\_app 可读写），文件字节不过 Runtime 进程，
  列表/下载复用 Backend JWT + require\_nexus\_use + owner 校验；

- `GET /api/v1/nexus/artifacts`（裸 JSON，与其他 nexus 路由一致）+
  `GET /api/v1/nexus/artifacts/{id}/download`（FileResponse，mime/filename 按
  type/title；非 owner **404**——列表不可见即不存在，防枚举探测；
  "链接含 token"= Authorization JWT）；

- 删除端点 P0 不做（retention 另行评估）。

**M3-B3 ⏸️→ no-go（P0）DOCX**：核定 `python-docx>=1.1.0` 在依赖内但仅用于
**解析**（document\_service.\_parse\_docx / document\_intelligence provider），
**无 markdown→docx 生成器**；自研渲染器（标题/列表/代码块/表格/内联样式
映射 + 测试）超出"薄 Adapter"成本线 → **归 后续主线与可选增强**（候选项注明支持
子集：h1-h4/段落/ul/ol/代码块/粗斜体/表格）。LaTeX P0 直接支持（同一文本管道）。

| 任务       | 内容                  | 输出                                                                   | 验收                             | 依赖    |
| -------- | ------------------- | -------------------------------------------------------------------- | ------------------------------ | ----- |
| M3-B1 ✅  | `write_artifact` 工具 | 见 §7.0：Runtime 工具 + 内部写端点 + 元数据表（PG-only）+ 结构化 items                 | mock 单测全绿；真实链路线上写入已验收；元数据不落业务库 | 无     |
| M3-B2 ✅  | 读取与下载               | Backend 原生路由（偏离记录见 §14.4）：本人列表 + owner 下载（404 防 enumerate）           | 跨用户 404 实证（线上）；JWT 下载头         | M3-B1 |
| M3-B3 ⏸️ | DOCX go/no-go       | **P0 no-go**（依据见 §7.0；python-docx 仅解析、无生成器），归 P2+                    | 决策记录入本文档进度区                    | M3-B1 |
| M3-F1 ✅  | 前端产物卡               | 消息流产物卡（图标+标题+大小+下载 SfxButton）；本机资料 real 模式接服务器列表（逐项下载）；demo 模式保持本地统计 | 演示链"生成 Artifact"环节真实可交付文件      | M3-B2 |

***

## 八、M4：复现体验闭环

对应设计文档 Phase 7 的前端呈现层与 Phase 10 交互要求（reproduction stages、report link）。

| 任务      | 内容              | 输出                                                                                                                                                            | 验收                             | 依赖    |
| ------- | --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------ | ----- |
| M4-B1 ✅ | job 状态查询代理      | `GET /api/v1/nexus/repro/jobs/{id}`：Backend 反代 Worker `GET /jobs/{id}`，鉴权 = job 发起人（发起时记录 user\_id）                                                           | 非发起人 403；返回 status/logs/metric | M0-V1 |
| M4-B2 ✅ | 阶段状态流           | `run_reproduction` 提交后在 `tool_result` 返回 job\_id + 初始状态；后续进度由前端轮询 M4-B1（SSE 不做长任务推送，避免连接占用）；阶段粒度 = Worker 现有执行切片                                              | UI 可见排队 → 构建 → 运行 → 完成/失败全过程   | M4-B1 |
| M4-B3 ✅ | 复现报告 artifact 化 | Worker 产物 `report.md`/`report.json` 经 `write_artifact` 入库；报告标注来源仓库与 License（AGENTS.md §4.1.10）；**PASS/FAIL 由 deterministic metric comparison 给出，不经 LLM 主观判断** | 报告含论文指标 vs 实测指标、容差、结论、日志与环境信息  | M3-B1 |
| M4-F1 ✅ | 前端复现状态卡         | 阶段流水（排队/构建/运行/完成）+ 轮询节流 + 失败语义显式；只展示操作状态（"正在构建环境"），**不暴露模型内部 Chain-of-Thought**（设计文档 Phase 10 红线）                                                             | 演示链末端完整闭环                      | M4-B2 |
| M4-F2 ✅ | 报告卡             | 复用 M3-F1 artifact 卡 + 指标对比高亮                                                                                                                                  | 报告可下载可核查                       | M4-B3 |

***

## 九、M5：S3 下线与可靠性

| 任务            | 内容                         | 验收                                                                                                                                                                                             | 依赖                                                   | <br /> |
| ------------- | -------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------- | :----- |
| S3-B1/B2/B3 ✅ | 按落地计划 §五执行（事实修正见 §14.9）    | 落地计划 §5.3 清单全勾（修正后）                                                                                                                                                                            | S2 稳定（已满足）                                           | <br /> |
| M5-B2 ✅       | Harness 压力套件（设计文档 Phase 9） | 覆盖：多 Tool 长任务、Tool 500、Context overflow（Compact 触发语义+生产接线分层锁定，全图触发留已知边界）、Runtime restart 后 resume、Cancel（M1-B6 引用）、Malformed Tool、Worker timeout —— 全部产生明确状态，**禁静默成功 / LLM 编造结果 / 未执行却写 PASS** | 全绿且失败语义可断言（`nexus/tests/test_harness_stress.py` 7/7） | M0-M4  |
| M5-D ✅        | 文档同步                       | 落地计划状态栏、前端规格 §8 缺陷清单逐条翻转（D1/D2/D3/D4/D5/D6/D8 标注修复提交）、`DOCUMENTATION_INDEX.md`、本文档进度列；AGENTS.md 部署地址变更按 §十二确认后独立处理                                                                             | 文档与代码一致（AGENTS.md §7.2）                              | M5-B2  |

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
Paper Search ───────────────── ✅ arXiv 元数据级已有
Paper Research ─────────────── ⏭️ 下一阶段主线：全文证据、比较、综合与 Citation
  ↓
选择一篇论文 ──────────────── ✅ plan_reproduction（nanoGPT 主选）
  ↓
Quick Reproduction ────────── ✅ Worker 已部署；M0-V1 复测
  ↓
预设环境 / 真实运行 ────────── ✅ M4（Verified Preset Reproduction Runner）
  ↓
Clean Verification ─────────── P2+（A/B 双环境，见 §十一；当前不作为 reproducible=true 依据）
  ↓
Reproduction Report ────────── ✅ M4（报告 artifact 化）
```

***

## 十一、后续必要建设主线与可选增强（2026-09-05 统一修订）

### 11.1 当日纠偏总账与实施依赖

本节与转型方案 §27–31 共同定义后续范围。NX 编号为新增待办，不改写历史 M0–M5 验收；当前均未完成，也不据此翻转能力标记。个人长期记忆、多云/GPU、模型选择器和额外格式输出属于可选增强；下列目标为必要主线，组件 go/no-go 只决定实现选型。

| 任务       | 产品目标与纠偏                                                                      | 依赖与交付门槛                                                                                                     |
| -------- | ---------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| NX-A1    | General/Research 共用 PDF、DOCX、JPG、PNG、XLSX、PPTX、PPT、DOC 附件；图片优先视觉直传、OCR 按需    | 复用私有对象存储和 Backend 底层 Provider，补 XLSX/旧 Office 适配；按 owner/session 授权、引用定位和保留删除验收；不写课程知识域                     |
| NX-H1    | 恢复复杂任务 Plan/Todo/Observe/Re-plan；简单 General 不启用，复杂 General 按需，Research 长任务启用 | 显式接入 Todo 中间件；计划修改与实际工具状态分开，补 checkpoint、产品事件、前端投影和取消/恢复                                                    |
| NX-H2    | 受限 Subagent 与会话工作区；文件读写/搜索/执行按能力逐步开放                                         | 先做只读子任务、独立白名单和父子任务生命周期；文件工具经工作区隔离，execute 经 SandboxProvider；不得直接解除现有禁用表                                     |
| NX-R1    | Paper Search 升级为 Research Question→候选论文→全文→证据→方法比较→综合→Citation               | NX-A1 的论文入口与 NX-H1；优先评估 PaperQA/同类，薄适配；选型失败换方案，能力保持未完成，不能用元数据搜索充数                                           |
| NX-S1    | Reproduction Orchestrator→SandboxProvider→成熟运行时                              | 保留 preset Worker 作为待适配旧实现；SWE-ReX/同类评估执行层，repo2docker 评估环境构建层，二者不是同层替代品；不直接扩展任意 URL/命令                      |
| NX-P1    | Paper-to-Reproduction：解析论文、抽取一个 Claim、定位/检查仓库、生成受约束 ReproPlan                | NX-A1/R1；来源、License、数据/指标/容差和资源预算可审核，模型生成计划不等于获准执行                                                          |
| NX-P2    | 环境 A 构建→Smoke→有界 Repair→Execute→Freeze→干净环境 B→Metric→Report                  | NX-S1/P1；优先用已有 preset 验证 A/B 再扩大范围；冻结代码、依赖、数据/配置、种子、命令与比较标准，修复有次数/时间预算；只有 B 成功且确定性指标满足才声明 reproducible=true |
| NX-E1–E4 | Experiment Console 与服务端 Session/Execution History                            | 具体任务见下；先 run/job 关联与恢复查询，再实时 Console、Cancel，最后完整元数据/事件恢复和 Worker 重启对账                                       |

**推进顺序**：附件生命周期和 NX-E1 作为入口/恢复基础；随后附件格式接线、NX-H1 与 Console；Paper Research 和 SandboxProvider 选型可同步推进；受限 Subagent、论文计划、A/B 验证按依赖接入。全部继续保留 preset-only 演示回退路径。排期需基于任务实测，不虚报日期或整体完成比例。

**职责分工**：成熟组件承担通用解析、Agent runtime、shell/容器执行与环境构建；Nexus 保留身份权限、任务编排、来源/License 策略、资源关联、确定性指标和报告薄适配。复用开源不意味着外包全部业务治理，也不保证自动获得 A/B 或安全边界。

### 11.2 Experiment Console / Session 交付明细

**2026-09-05 补充**：八格式会话附件为已确认产品范围；JPG/PNG 优先直传支持视觉的模型，OCR 按需辅助，不能作为强制前置（转型方案 §30）。按用户要求，Experiment Console 与 Session 升级正式纳入后续开发规划（§31），不再仅作讨论项。这些必要产品升级与下表其他可选候选项分开管理，不属于现有 M4/M5 的已完成声明，尚未承诺日历排期。

**Experiment Console / Session 交付任务（均待启动）**：

| 任务    | 交付范围与主要改动入口                                                                                                                                                                      | 依赖                         | 验收标准                                                             |
| ----- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------- | ---------------------------------------------------------------- |
| NX-E1 | Nexus 域持久化 session/turn/run/job 关联；`nexus/src/nexus/persistence.py`、`main.py`、`backend/app/api/v1/endpoints/nexus_proxy.py` 与 `frontend/src/app/pages/nexus/NexusPage.vue` 接恢复查询 | 先统一 run/job 标识及 owner 契约   | 刷新/新设备可找到原 job 并恢复查询；不重复提交；跨用户拒绝；Worker 丢失 job 时明确未知/中断          |
| NX-E2 | `deploy/repro-worker/worker.py` 增量阶段/有界日志，代理脱敏，NexusPage 展示只读 Console                                                                                                            | NX-E1；采集部分可同步开发            | 运行中看到阶段、命令标签、耗时、退出码和最近 20 行日志；指标/报告可见；预构建与未实现 B 阶段诚实显示           |
| NX-E3 | Worker 用户取消接口、代理鉴权、前端取消状态；精确回收 job 的进程组/容器                                                                                                                                       | NX-E1；可与 NX-E2 同期推进        | 排队/运行取消均幂等；确认回收后显示 cancelled；完成竞争处理明确；不影响其他任务，聊天 Stop 不冒充 Cancel |
| NX-E4 | 服务端 mode/course/pin/version 与最小事件历史、游标回放；Worker 持久化快照与重启对账                                                                                                                       | NX-E1 的标识契约，消费 NX-E2/E3 状态 | 换设备恢复偏好和过程；重连事件去重；不保存完整原始 Trace；重启诚实恢复/中断；过期删除覆盖事件与关联资源          |

以上任务只更新规划，未执行实现、迁移、依赖安装或部署；验收通过后分别记录证据，不能一次性翻转所有状态。

| 已纳入规划项                      | 交付范围                                                            | 前置与边界                                                                   |
| --------------------------- | --------------------------------------------------------------- | ----------------------------------------------------------------------- |
| Experiment Console          | 阶段、命令标签、服务端耗时、退出码、20 行日志尾、指标与报告；Cancel 单独验收                     | Worker 增量输出和代理脱敏先接线；不开放交互 shell；无环境 B 就不显示 Verifying 完成；聊天 Stop 不等于实验取消 |
| Session / Execution History | 服务端保存 mode/course/pin 与 run-job 关联，刷新恢复查询；再补游标事件回放和 Worker 重启对账 | 本地只作缓存；checkpoint 与产品事件分开；只存最小结构化过程，无完整 Trace/思维；恢复不能重新提交实验             |

| 能力/选型明细（必要性以 §11.1 为准）                      | 内容                                                                                                                    | 前置 go/no-go 标准                                                                            |
| ------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| Paper Research 完整化（优先）                      | `paper_research(question)`：多论文全文证据收集 + 方法比较 + 综合 + Citation                                                           | 优先评估 PaperQA（Apache-2.0）或同类成熟项目；完成 License/依赖/全文获取/引用质量验证后再接入；不满足则明确 no-go，不宣称已完成         |
| Personal Context                            | 用户长期偏好记忆（设计文档 Phase 6；Mem0 / deepagents memory / 最小偏好表三选）                                                             | 接入成本高则推迟，不阻塞主链                                                                            |
| Clean Verification                          | A/B 双环境（开发环境修复 + 冻结环境验证），`reproducible=true` 只由 B 环境判定（设计文档 Phase 8）                                                  | 简单可靠的 freeze 方案；不为完美可复现规范拖死 Demo                                                          |
| Sandbox Runtime（优先于任意仓库）                    | 将当前 preset Worker 演进为 Container A/B 的独立实验沙箱；补 Workspace、镜像/依赖锁、网络策略、审批、配额、取消与清理、审计                                    | 未完成前继续维持 preset-only；不得开放任意 GitHub URL 或 LLM 任意 command；安全验收通过后再 go/no-go                 |
| Reproduction Orchestrator + SandboxProvider | 保留现有 Preset Repro Worker 作为稳定实现；新增统一 SandboxProvider 契约，优先评估 SWE-ReX / repo2docker / OpenHands Runtime，减少自研通用 runtime | 完成 License、隔离、网络/凭据、取消清理、A/B 验证和 nanoGPT 回归对比；未通过则不迁移、不扩大仓库范围                             |
| 会话附件 + Research Paper Import（必要主线，待实施）      | General/Research 共享 PDF、DOCX、JPG、PNG、XLSX、PPTX、PPT、DOC 上传；复用 Backend 底层解析与对象存储，补 XLSX 适配，论文用增强 Profile；设计见转型方案 §30    | 按 PDF 闭环→其余七格式→论文增强验收；含权限、引用定位、限额、过期/删除与失败状态；不进课程知识域。附件 ready 与 Paper Research ready 分开判定 |
| 模型选择器恢复                                     | Runtime `/models` + 请求级 `model` 字段（前端规格 §12.5 记录的恢复前提）                                                                | 有真实多模型需求                                                                                  |
| D7 token 口径                                 | 接真实 tokenizer                                                                                                         | 有计费/限额 UI 需求                                                                              |
| Repro Worker 并发队列                           | 当前串行（max\_total=1）即满足演示                                                                                               | 多用户并发复现成为真实需求                                                                             |
| CS 知识库向量化                                   | `discipline-knowledge` 关键词检索 → 向量检索                                                                                   | M2 落地后按检索质量决定                                                                             |

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

### 14.4 2026-09-05 M3 代码完成记录

- **M3**：B1/B2/F1 已完成并进入线上验收记录（`write_artifact` 工具、内部写端点、Backend
  原生列表/下载路由、前端产物卡与本机资料真实列表）。

- **偏离记录（M3-B2）**：计划原文 "Runtime GET /artifacts + download +
  Backend 反代" → 实现为 **Backend 原生路由直读 nexus\_artifacts**（同库
  不同连接），理由：文件字节不过 Runtime 进程、Runtime 保持零存储依赖、
  鉴权链复用既有 JWT + require\_nexus\_use。计划原文的"签名 URL"以 JWT
  Authorization 头实现（同为"下载链接含 token"约束）。

- **DOCX 判定（M3-B3）**：P0 **no-go**（python-docx 在依赖内但仅用于解析、
  无 markdown→docx 生成器，自研渲染器超"薄 Adapter"成本线），归 P2+
  候选池；LaTeX P0 直接支持（同一文本管道）。

### 14.5 2026-09-05 M3 部署与线上验收记录

- **M3**：全部完成并部署生效（提交 `878906d0` + 热修 `d869424a`，release
  `878906d0`）。线上实证：写入链（对象存储 + `nexus_checkpoints.nexus_artifacts`
  真实建表落库）、下载链（owner 200 内容一致 / 他人 404 / 他人列表空）、
  端到端（模型自主 CS+课程双源检索 → write\_artifact 落盘 4477 字节学习笔记，
  内容含合流红线的诚实说明）。验收记录：
  `docs/phase1/验收记录/M3_验收_2026-09-05.md`。

- 教训记录：服务层删除型重构后的全局常量遗漏（`_TABLE`）导致首次部署写端点
  500——已热修并推送；后续此类文件应整段复核而非 regex 零散替换。

### 14.7 2026-09-05 M4 代码完成记录（已由 14.8 验收）

- **M4**：B1/B2/B3/F1/F2 代码完成。交付：`GET /nexus/repro/jobs/{id}`（发起人
  鉴权 + 日志裁剪 300 字符）、`POST /nexus/repro/jobs/{id}/report`（代理
  Runtime 确定性报告）、Runtime `repro_report.py`（纯函数判定：预设期望指标
  val\_loss 1.88±0.06，来源官方 README CPU 配置声明）、`run_reproduction`
  提交后经内部端点登记归属（best-effort，失败如实标注）、前端受控轮询
  （5s × 上限 200）+ 阶段流水卡 + 判定徽章 + 报告复用 M3 产物下载链；
  `nexuslab_repro` 随本批翻 `ready`（Clean Verification 仍为 P2+）。

- **待线上验收门**（§14.6）：nanoGPT"提交→查询→完成→指标比较→报告下载"
  完整链 + 失败/越权/超时语义线上复核；验收通过后 M4 才记为完成。

### 14.8 2026-09-05 M4 部署后验收（验收门达成）

- **M4**：全部完成并部署生效（提交 `aa77ba41`，release `aa77ba41`）。验收门
  **达成**：nanoGPT 完整链线上闭环——提交（job `c3e71851e513`）→ 查询
  （发起人 200，越权 404 双向）→ 完成（5 步真实训练，seed 命中）→ 确定性
  指标判定（**val\_loss 1.8857 ∈ 1.88±0.06 → PASS**，LLM 零参与）→ 报告
  双 Artifact 落库并下载（md 2576B + json 3397B）。验收记录：
  `docs/phase1/验收记录/M4_验收_2026-09-05.md`。

- 语义覆盖：409 未完成（单测）、404 防枚举（线上双向）、轮询上限、归属
  登记失败诚实标注（单测）。`nexuslab_repro` 翻 `ready`（Clean Verification
  仍为 P2+）。M0-F2 同步完成。

### 14.9 2026-09-05 M5 代码完成记录（已由 14.10 验收）

- **S3-B1/B2/B3**：代码完成。删除 `endpoints/research_agent.py`、
  `platform/agents/research/` 全目录、`providers/research/` 的
  `paper_search.py`/`workspace.py`/`access.py`、main.py 路由注册与
  `bootstrap_research_agent`、旧 research 测试 10 文件；
  **保留**（活消费者，AGENTS.md §4.2.3）：
  `providers/research/{question_bank,question_generation,web_research}.py`
  （TeachingAgent 工具链）、`endpoints/web_research.py` +
  `web_research_service.py`（tasks 任务链）；
  deprecated 中间件保留（410 短路继续）。

- **事实修正**（相对转型落地计划 §五）：
  ① `services/research_service.py` 不存在（幽灵文件，未删任何东西）；
  ② Backend `providers/research/paper_search.py` **无需迁移**——nexus 已有
  独立降级链实现（packages 无交叉 import），直接删除；
  ③ 计划"删 `platform/agents/research/` 除 paper\_search 外"中的路径假设错误
  （paper\_search 不在该目录）——按现实全删该目录。

- **S3-B3**：`research_models.py` 表模型 + Alembic 迁移保留，未新增 down 迁移。

- **M5-B2**：`nexus/tests/test_harness_stress.py` 7 场景全绿（多 Tool 长任务 /
  Tool 500 → error 事件 / Compact 触发语义+生产接线分层锁定 / restart resume /
  Cancel 引用 M1-B6 / 缺参 tool\_call 诚实 error / Worker 超时 fail-closed）。
  已知边界：Compact **全图触发实测**未命中（deepagents before\_model 与
  profile 联动，fake 模型注 profile 后仍不触发），留 P2+ 与上游核实。

- **既有遗留（非 S3 造成，worktree** **`aa77ba41`** **对照实证）**：
  ① b433bae3 avatar 移除遗留的死测试（404 接口不存在）——已删除
  `test_avatar.py`/`test_p0_3_avatar_upload_security.py`/
  `test_avatar_cue_release.py`/`test_r2c_tts_batch_task.py`，
  翻转两条路由契约断言为"已下线"；
  ② 仍失败 2 项待单独跟进：`test_alembic_migration`（course\_access 修复脚本
  权限集断言）、`test_p0_2_async_tasks`（handlers 注册断言）——course-access
  与任务域，超出 M5 范围，不删不改，如实记录。

- **M5-D**：前端规格 §8 缺陷逐条翻转（D1/D2/D3/D4/D5/D6/D8 标注修复提交 +
  验收记录链接）、§11 基数刷新；落地计划 §九随部署后更新。

### 14.10 2026-09-05 M5 部署后验收（全线收官）

- **M5**：全部完成并部署生效（提交 `8d868f76`，release `f1eb9b27`；
  AGENTS.md 地址变更单独提交 `f1eb9b27`——按 §十二，经用户确认后执行）。
  线上实证：research-agent 路由 410 保留、nexus health（persistence=postgres、
  双模式工具面）、真实对话工具调用正常。验收记录：
  `docs/phase1/验收记录/M5_验收_2026-09-05.md`。

- **P2 转型主线全部完成**：M0 ✅ → M1 ✅ → M2 ✅ → M3 ✅ → M4 ✅ → M5 ✅。
  剩余：后续主线与可选增强（§十一及转型方案 §27，按 go/no-go 标准逐项评估）、浏览器手工点击
  全链（建议演示前过一遍）、2 项既有测试失败单独跟进。

- 语义覆盖：409 未完成（单测）、404 防枚举（线上双向）、轮询上限、归属
  登记失败诚实标注（单测）。`nexuslab_repro` 翻 `ready`（Clean Verification
  仍为 P2+）。M0-F2 同步完成。

### 14.6 2026-09-05 M4 启动基线（历史记录，已由 14.8 验收）

- **M4 状态**：已进入执行阶段，M3 已提供可复用的 Artifact 写入、列表和下载能力。

- **M4-B1 第一交付**：新增并验收 `GET /api/v1/nexus/repro/jobs/{id}`，由 Backend
  代理 Worker 状态查询，按发起人鉴权；不得通过 job id 枚举他人任务。

- **M4-B2 第二交付**：`run_reproduction` 返回 job id 后，前端以受控轮询展示
  queued → building → running → succeeded/failed；只展示操作状态和安全日志摘要。

- **M4-B3 第三交付**：Worker 返回的论文指标、实测指标、容差、环境和日志经
  deterministic metric comparison 判定 PASS/FAIL，再生成 `report.md`/`report.json`
  Artifact；LLM 不参与最终判定。

- **M4-F1/F2**：复现状态卡和报告卡复用 M3 产物下载链；在完整链路验收前，
  `nexuslab_repro` 能力状态保持为非 `ready`。

- **M4 验收门**：必须至少完成一次线上 nanoGPT 任务的“提交→查询→完成→指标比较→报告下载”，
  并补充失败、越权和超时语义测试，之后才能进入 M5。

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

