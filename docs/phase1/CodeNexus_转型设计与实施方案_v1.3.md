# CodeNexus Current Architecture + Roadmap v1.3

> **日期**：2026-09-05。替代 v1.2 的现行设计地位；本次为文档结构清理，不是功能发布。
> **开发基线**：`dev-liu`；本次读取 HEAD=`d2c694a0`。工作区有未提交修改，不能把工作区行为当作 HEAD 或线上行为。后续执行前重新读取 branch/HEAD/status；`feature/xh202620` 仅为历史设计基准，禁止据此切回旧分支。
> **依据顺序**：AGENTS.md → 代码/路由/可运行证据 → 本文冻结设计 → 开发计划与前端规格。三者不一致时登记缺口，不伪称已实现。
> **执行入口**：[P2 / NX 开发计划](CodeNexus_P2开发计划.md)；[前端规格](Nexus_AI_前端开发规格与UX落地说明.md)。

## A. 产品冻结

### A1. 产品与 Mode

- TeachingAgent：课程内教学、练习与代码挑战，复用 Course Access、Judge0 和既有学习证据链。
- Nexus AI：课程外通用复杂任务助手；默认 General。Research 是同一 Harness 上由用户主动启用的 Profile，增加论文与 NexusLab 能力，不是第二套 Agent Runtime。
- NexusLab **仅 Research**：General 不显示 NexusLab 工具 pill/能力 Chip/执行入口，也不得调用对应工具。绑定课程不会自动提升 Mode。
- Nexus Runtime 独立 Python 环境、lockfile 和进程；通过 HTTP/SSE 访问 Backend，不共享依赖树。

冻结的请求语义（目标；与当前代码差异见 B2）：

| 输入 mode | 规范化结果 |
| --- | --- |
| 缺字段 / null | general |
| general / nexus_general | general |
| research / nexus_research | research，表示本次显式选择 |
| 其他字符串，包括空字符串 | HTTP 400，`INVALID_NEXUS_MODE` |

已知名称可 trim/lowercase 后匹配，空白不视为缺字段；非法类型按请求校验拒绝。Backend 入口与 Runtime 一致，必须在启动模型/SSE 前拒绝错误。续聊 Research 也显式传值；持久化会话偏好不覆写缺省 General 的安全语义。

Base Prompt 仅定义通用 Nexus 身份与共同规则；General 定义通用任务能力，Research 附加学术证据/论文/实验规则。不能以科研智能体作为所有模式的基础身份。

### A2. 统一规划状态

| 标记 | 定义 |
| --- | --- |
| CURRENT | 有真实验收记录支持的阶段能力，明确范围、版本和已知缺口；不等于此刻远端所有依赖在线 |
| NEXT | 已确定的下一批必做能力；未实施，不承诺日历日期 |
| TARGET | 确定的最终目标，本批不交付，不能因暂缓永久删除 |
| OPTIONAL | 按真实需要评估，不承诺实现 |

这四种是路线图状态，不替代产品运行时的可用/降级/未知/待审批状态。工作区修正单列“本地未提交”，没有上线验收不能升级为 CURRENT。

### A3. 执行审批是 Hard Workflow

`run_reproduction` 及后续危险/昂贵操作必须有服务端强制审批。UI 抽屉只是展示和提交用户决定；Prompt、“用户已同意”文本、Research Mode、Worker 服务令牌或 preset 白名单都不等于用户批准这次执行。

目标流程：LLM 提案 → `ApprovalRequired` 持久化 → 暂停执行 → 本人批准/拒绝 → 服务端验证 → 恢复对应操作。优先复用可持久化 interrupt/permission 机制，或等价的一次性审批票据，不能只加前端确认。

审批至少绑定 owner、session、run、tool、preset/plan hash、资源预算、expires_at、状态；身份取服务端登录态，不接受模型伪造。批准接口重新鉴权，票据不可跨人/会话/工具使用；计划、命令、预算变化使批准失效。票据由请求上下文/服务端状态注入，不作为模型可随意生成的凭证。批准消耗与 job 创建使用幂等请求/对账；网络重试返回原 job，不重复启动实验。

无批准、过期、拒绝、篡改、服务不可用时不提交 Worker。所有入口（聊天工具、手工执行、内部代理、恢复）执行同一检查；Worker 只接受受信执行通道。批准前先持久化任务归属，不能依赖提交后的 best-effort 登记。取消/拒绝不耗用后续执行资源。

**当前硬门未实现**（B2），因此不能宣称“模型无法绕过 UI”。在 NX-G2 完成前，不扩大仓库或执行工具面；需要强审批承诺的对外执行应关闭提交能力或先落硬门。只读计划/查询不受影响。

### A4. Effective capability

`effective capability = manifest ∩ current mode ∩ actual tool surface ∩ dependency health/config ∩ user/scope policy`；执行还必须满足当前 run 的 approval。

- `nexusCapabilities.js` 只声明产品能力/预期 Mode，不是依赖在线或执行授权的唯一真相源。
- 有配置不等于健康：当前 `repro_worker_configured` 只是 URL 配置事实，不证明 Worker 活着；健康未知、过期或探测失败时显示 unknown/degraded，不沿用永久 Ready。
- 课程绑定不等于有权限，接口执行仍逐次检查；用户无权限不应把全局工具误标为故障。
- health 不返回密钥或原始敏感日志；带检查时间与有效期。执行端重新检查，不把 UI 按钮禁用作为边界。
- manifest、模式菜单、工具 pills 与 Backend/Runtime 契约使用同一模式映射；未批准应显示等待确认，不能用“工具注册了”表示现在能执行。

## B. 当前已实现与待修正代码

### B1. CURRENT 的范围

既有验收记录表明：独立多工具 Runtime、Checkpoint/Compact、General/Research 工具分组、Web/Course/CS 检索、Markdown/LaTeX Artifact、消息恢复、预设复现/确定性报告、Legacy Research S3 下线已形成 MVP。依据为[验收记录目录](验收记录/)中的 P1、M1–M5 与迁移记录，本次未重新执行线上验收或付费服务测试。

| 能力 | 状态 | 真实边界 |
| --- | --- | --- |
| Web / Course RAG / CS RAG | CURRENT | Course Access 逐次鉴权；权限不足诚实拒绝，外网资料为补充参考 |
| Markdown / LaTeX Artifact | CURRENT | 写入、列表、下载；DOCX 输入支持规划不等于 DOCX 输出完成 |
| 多工具 / Compact / checkpoint | CURRENT | 多工具、长上下文、可恢复 Runtime；不称完整复杂任务 Harness，Compact 全图触发仍有已知验证边界 |
| 消息历史 | CURRENT | 只投影 user/最终 assistant；不足以恢复全套产品运行历史 |
| Preset reproduction | CURRENT | Verified Preset Reproduction Runner；只有 nanoGPT 已验收，指标取 README CPU 配置基线，不宣称完整 GPT-2 论文指标复现 |
| 基础实验卡与报告 | CURRENT | 轮询 job 状态/终态步骤结果、退出码、耗时与指标，不是连续实时 Stage/Log Console |
| Legacy Research 下线 | CURRENT | S3 已完成；保留活跃业务消费者、数据模型和迁移；不重新迁移已独立的 paper_search |
| 用户执行审批 | NEXT / P0 缺口 | 只有 UI 确认，不是 Runtime 强制门 |

### B2. HEAD / 工作区事实（2026-09-05 本地读取）

| 检查项 | HEAD d2c694a0 | 当前未提交工作区 | 下一动作 |
| --- | --- | --- | --- |
| normalize_mode / 默认 agent | 缺失或未知回 Research | 缺失或未知回 General | NX-G1：缺失 General、未知 400；请求入口一致验收 |
| Base Prompt | 科研身份作为 Base | 中性 Base + 独立 Profile | NX-G1：保留改动并验证；未证明已上线 |
| nexuslab_repro modes | General + Research | Research-only | NX-G1：验证 UI 全入口及 Runtime 拒绝，不只检查 manifest |
| 前端 NEXUS_MODE_CONFIG.tools | 早期四工具映射 | 仍是早期映射 | NX-G1/G3 更新，不能把旧 pills 当作真实工具面 |
| run_reproduction 审批 | 无每次用户批准检查 | 仍无；检查 preset、提交 Worker 后登记归属 | NX-G2：Hard Workflow + 审批/提交幂等 |
| effective capability | 静态声明为主 | 静态声明为主；可执行 helper 未接完整 Mode/health/approval | NX-G3：动态状态与服务端校验 |

证据文件：`nexus/src/nexus/agent.py`、`main.py`、`tools/__init__.py`、`tools/reproduction.py`；`frontend/src/api/nexusCapabilities.js`、`nexusAdapter.js`；`backend/app/api/v1/endpoints/nexus_proxy.py`。这些工作区修正不得写成 HEAD/远端完成。

### B3. Current registered tool surface

| 工具 | General | Research |
| --- | --- | --- |
| read_file（内部 Harness，读 StateBackend 历史） | 是 | 是 |
| web_search | 是 | 是 |
| search_course_materials | 是 | 是 |
| search_cs_knowledge | 是 | 是 |
| write_artifact | 是 | 是 |
| search_arxiv_papers | 否 | 是 |
| plan_reproduction | 否 | 是 |
| run_reproduction | 否 | 是，但用户审批硬门仍待补 |

共 7 产品工具，General=4、Research=7；另各有内部 read_file。表为注册面，不保证所有依赖健康或审批已满足。历史 M0/M1 数量只代表当时快照。当前 write/edit/glob/grep/execute/task 禁用，Todo 未产品化。

### B4. Runtime / Sandbox / Session 边界

当前 Worker 容器中以 bash subprocess 执行 preset；当前部署策略限制 CPU/内存/PID/网络与总截止，不能等同于逐任务 A/B 沙箱。维持已核验仓库/命令、串行和无生产凭据；不得直接开放任意 GitHub URL + LLM command。License 和资源限制不替代用户批准。

Worker `_run_step` 用 communicate 等待输出，步骤结果主要终态写回；代理 log_tail 裁剪 300 字符，前端未映射日志尾。无用户 cancel API，聊天 Stop 不等于取消 Worker。`_jobs` 仍在内存。

Session 前端为 local + remote merge，mode/course/pin 主要本地，remote-only 会话默认 General/无课程/未置顶，工具事件投影为空。同浏览器刷新可能保留缓存，换设备/清缓存更明显缺失。历史 API 过滤 ToolMessage **不证明 checkpoint 未保存工具消息**；产品历史须独立于 checkpoint 的压缩/保留语义。

## C. 最终目标架构

本节是目标，不是当前实现声明。三条链共享身份、对象存储和 Nexus 产品状态，课程业务域不被复制。

### C1. Harness 与科研

通用复杂任务：Plan → Todo → Tool loop → Observe → Re-plan → 可控子任务 → 长任务取消/恢复。

Todo 为 NEXT：简单 General 不强制，复杂 General 按需，Research 长任务启用；显式 middleware + checkpoint + 产品事件 + 前端投影一起交付。Subagent/Workspace 为 TARGET：独立白名单、父子任务取消/恢复、文件隔离和审批到位才逐步开放。

Paper Research（NEXT）：Research Question → 候选论文 → 合法获取全文 → 阅读/证据定位 → 方法比较 → 综合 → 可核查 Citation。优先评估 PaperQA 或同类 scientific RAG；当前 arXiv 元数据查询只称 Paper Search。

### C2. 附件与多模态（NEXT）

General/Research 共用会话附件：PDF、DOCX、JPG、PNG、XLSX、PPTX、PPT、DOC。Paper Import 是论文 Profile，不再另建上传系统。

| 输入 | 复用路线 | 模型消费与定位 |
| --- | --- | --- |
| PDF | Backend PDF Provider；复杂论文评估 Docling；扫描页 OCR | 正文/表格/页码/坐标，低质量显式 warning |
| DOCX | PythonDocx Provider；必要时生成 PDF 版面 | 标题/段落/表格；页码仅在转换版本有依据时提供 |
| JPG/PNG | 视觉模型直传优先，OCR 按需 | 原图/受控派生图 + 问题；文字检索/坐标才用 OCR；不把 OCR 冒充看图 |
| XLSX | openpyxl 专用薄适配 | sheet/单元格范围、类型、公式与缓存值；不执行公式，提示缓存缺失/陈旧 |
| PPTX | NativePptx Provider | 幻灯片号/文字/备注/表格；图片按需增强 |
| DOC/PPT | LibreOffice 转 PDF，再 PDF/OCR | 保存原件与转换关联，注明转换页码及排版/备注损失 |

Backend 已有底层 Provider/OCR HTTP/LibreOffice，Docling 已声明依赖，但现有课程主链不能仅凭依赖名称认作 Docling。planner 无 XLSX 专用分支需补齐。复用 ParserProvider，不调用绑定 course/material/evidence 的 DocumentParseService，不伪造 course_id。MarkItDown 为轻量文本转换备选，不必另上全格式平台。

私有对象存储以 object_key 保存原件/转换件/解析件；Nexus 域管理 owner/session/任务/引用/索引。只通过 HTTP 访问 Backend。短文在预算内全文，长文按块检索，Excel 按 sheet/range；保留原文定位，不只存摘要。内容视为资料，不提升为指令，不写课程 KB、LearningEvidence、Course Graph。

图片校验 MIME/解码/像素后，以实际端点支持的多模态块传受控字节或短期授权 URL；“OpenAI 兼容”不证明视觉可用。无视觉能力时用已配置获准的视觉辅助或明确 OCR 文字降级；OCR 失败不阻塞正常视觉路径。不抓用户任意 URL，不公开对象桶，不泄露凭据。

首版建议预算：每次 5 文件、单个 20 MiB、合计 50 MiB；文档 200 页/张、图片 20MP、工作簿 10 万非空单元格、解析 180 秒。另限制 ZIP 膨胀/条目数、内存、磁盘与并发，样例实测后调优。解析用隔离进程/容器，禁宏/外链更新，网络默认禁用，OCR 仅受控服务通道；headless 不等于沙箱。

状态 uploading/queued/parsing/ready/partial/failed/expired/deleted，图片视觉/OCR 分开。预会话文件先绑定用户，再原子绑定会话；所有读取/下载逐次验证归属。未绑定 24h、已绑定 7d 为首版建议；删除立即撤销读取，异步清理对象/索引，防迟到任务写回。同步 checkpoint 已注入片段保留策略，不能承诺只删文件便清空历史。

### C3. Paper-to-Reproduction 与开源复用

CURRENT：nanoGPT Verified Preset Runner。NEXT：论文/PDF + Repo → Parse → One Claim → Repo Locate/Inspect → 受约束 ReproPlan → 批准 → 环境 A 构建 → Smoke → 有界 Repair → Execute → Freeze → 干净环境 B → Deterministic Metric → Report。

Reproduction Orchestrator 是 CodeNexus 一等业务模块，负责计划、策略、预算、审批、运行/验证编排与报告；它通过 SandboxProvider 调用成熟执行层。SWE-ReX/OpenHands Runtime/同类为执行层候选，repo2docker 为环境构建层候选，不是同层互斥替代品。现有 Worker 保留并后续适配为 PresetSandboxProvider，不能写成已存在该适配。

A 允许受限修复，B 从冻结规格重建且不继承 A 的可变目录；冻结 repo commit、镜像/依赖、数据摘要、配置、种子、命令、指标/容差和来源。修复有次数/时间预算，计划实质变化重新审批。只有 B 成功且确定性指标满足才置 reproducible=true；进程成功、metric PASS/FAIL、清洁验证结论分开。指标不可得应不可判定，不交 LLM 伪造。A/B 为 NEXT 的受控范围；支持任意论文/仓库属 TARGET，不在本批承诺。

### C4. Experiment Console（NEXT）

会话内只读实验详情：Stage、Command label、Elapsed、Exit code、最近 20 行日志（可调 10–30）、Metric、Report、Cancel。无 stdin/任意命令编辑/交互终端。

Preparing→Building→Running→Metric→Verifying→Completed 从真实事件产生；预构建显示复用/跳过，没 B 时 Verifying 显示未实施/不适用。Worker 增量读取并维护有界日志，限制字节/长行；代理脱敏/过滤控制符，UI 纯文本转义。时间戳来自服务端，运行时 exit=null，断线显示状态未知。2–5 秒轮询足够，不必先上 WebSocket。

Cancel 独立作业 API，发起人鉴权，幂等，终止准确的进程组/容器并回收；确认前 cancelling，竞争自然完成时保持真实终态，不影响其他任务。不得把聊天 Stop 当 Cancel。

### C5. Session / Execution History（NEXT）

服务端保存 mode/course/pin/title/version 与 session/turn/run/job/attachment/artifact 关联，localStorage 只作用户隔离缓存和折叠等设备偏好。服务端版本解决并发；本地迁移不能覆盖较新状态，旧工具卡不导入为真实审计。

产品事件最小化：event_id/run_id/seq/type/time/status 与白名单摘要、错误码、耗时、证据/产物引用。无完整 Prompt、模型思维、原始 Tool 参数/输出。快照 + 游标事件，去重后恢复轮询；不重新提交实验来恢复。跨设备重新验证课程/资源权限；旧版本无关联则显示过程不可恢复。

LangGraph checkpoint 管执行续跑，产品事件管用户可见历史，二者不是同一 API。Worker 作业需持久化快照/实例对账，重启不确定则 interrupted/unknown，不凭内存丢失自动重跑。事件与作业提交/通知采用幂等、重试和对账。元数据/事件/日志/对象/checkpoint 统一删除与保留政策。

## D. 后续必要主线

| 状态 | 任务 | 顺序 |
| --- | --- | --- |
| NEXT / P0 | NX-G1 默认 Mode、Research-only、Base Prompt 与完整工具映射 | 首批修正并验证提交/部署版本 |
| NEXT / P0 | NX-G2 服务端执行审批、提交幂等与归属 | 先于任何新增自动执行能力 |
| NEXT / P0 | NX-G3 effective capability | 先于依赖健康/Ready 对外承诺 |
| NEXT | NX-A1 八格式附件/图片直传；NX-E1 run/job 恢复基础 | 入口与状态基础 |
| NEXT | NX-H1 Todo；NX-R1 Paper Research | 依赖真实输入与产品事件 |
| NEXT | NX-S1 SandboxProvider；NX-P1 论文计划；NX-P2 受控 A/B | 先评估隔离/构建，后受控执行/验证 |
| NEXT | NX-E2 Console、NX-E3 Cancel、NX-E4 服务端 Session/事件 | 先关联恢复，再日志/取消，后完整事件与重启对账 |
| TARGET | NX-H2 Subagent/Workspace；DOCX/PPTX 输出；更广论文/仓库 | 门槛到位后排新批次，当前文件/execute 继续关闭 |
| OPTIONAL | Personal Context、GPU/多云、额外模型选择器 | 有需求再评估；视觉能力配置本身属于 NX-A1 必需项 |

NEXT 不表示同时开工或均已准备好上线，依赖/验收见开发计划。CURRENT Markdown/LaTeX 输出不扩写成 DOCX P0；输入 DOCX 解析仍是 NEXT。

## E. 工程原则

1. **通用基础设施成熟开源优先**：Harness、checkpoint、解析、OCR、shell/runtime、镜像构建不重复自研。评估许可、依赖、隔离、取消、持久化与维护成本。
2. **CodeNexus 业务域现有能力优先**：Course RAG、CS KB、权限、媒体对象存储、学习证据使用既有服务，不另造平行系统。复杂课程入库流程不能因为复用解析而一起搬入 Nexus。
3. **自研边界明确**：Reproduction Orchestrator / Policy / Verification orchestration、审批/任务关联、确定性指标与业务 Adapter 是合理一等模块；不是所有自研都该删，也不把完整领域编排贬为几行 glue。
4. 组件 no-go 只决定换方案，不删除 NEXT/TARGET 产品目标。保住 preset 回退路径；现有 Worker 在强审批未完成前不能宣传成安全完成版。
5. `1a1a11a/2026_paper_reproduce`、`AI9Stars/AutoReproduce` 不列入可复用代码池：未确认明确许可前固定为 **concept-only / no source reuse**，仅参考论文/README 概念，不复制代码/脚本/权重。这是复用政策，非本轮对其最新 License 的网络审计。其他候选也要逐版本核验许可。
6. 业务库、Nexus 状态和媒体对象分域；不把学生数据或密钥放进文档、fixture、日志。未知仓库只能进专用隔离执行层，不进 Backend/Judge0。
7. 新依赖/常驻服务可按 NX 需要评估，安装和部署仍须明确授权。不把历史 M0–M5 的依赖范围限制套到所有未来主线。
8. 完成声明必须写具体版本、环境和证据。UI 状态不证明服务端安全；注册工具不证明获准执行；计划/预设成功不证明完整论文复现。

## F. 历史决策附录与迁移

- [v1.2 清理前完整快照](CodeNexus_转型设计与实施方案_v1.2_历史快照_2026-09-05.md)：原 §1–31 与 Phase 1–12，全部仅追溯。旧分支、DOCX P0、Legacy 保留、无许可代码参考池不再指导实现。
- [P2 历史快照](CodeNexus_P2开发计划_历史快照_2026-09-05.md)：保留 M0–M5 原任务和验收账；工具数量为当时快照。当前表见 B3。
- [前端历史快照](Nexus_AI_前端开发规格与UX落地说明_历史快照_2026-09-05.md)：Appendix A=§1–7 初始调查，B=§8 D1–D8 关闭记录，C=§12–14 UX 演进；不再放进当前规范正文。
- 原 v1.2 路径保留为迁移入口；旧章节链接应导航到现行文档对应 A–F 内容，不继续追加 §32。
