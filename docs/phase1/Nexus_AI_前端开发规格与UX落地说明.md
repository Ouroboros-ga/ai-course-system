# CodeNexus Nexus AI 前端开发规格与 UX 落地说明

> **版本**：v2.2 (2026-09-04)
> **阶段**：S1 双轨期 · **纯前端先行**——UI/交互/数据结构已就绪，能力全部以演示数据驱动，**未接入真实后端推理**
> **原则**：`AGENTS.md` §4.3 结果诚实性。未接通的能力在界面上必须显式标注为「未接入」，绝不用静态装饰冒充已实现。
> **依据**：`CodeNexus_Nexus_AI_前端_UX_UI_详细设计规格_视觉风格开放版.md`（参考，非规范）、`design.md`（视觉权威）、`page-design.md` §4.1（三栏布局权威）、`AGENTS.md`

---

## 1. 本阶段边界（先讲清楚什么没做）

| 已做 | 未做 |
|---|---|
| 三栏工作区完整骨架与全部交互状态 | 真实 LLM 推理（前端不发起 `/chat/stream` 以外的调用） |
| 演示数据 + 本地持久化，可完整走查体验 | 会话落库（运行时仍是 `InMemorySaver`） |
| 能力接线状态单一数据源 + 界面诚实标注 | CS 知识库检索、课程资料注入、实验复现执行 |
| 字段级后端接线契约（第 7 节） | 后端 `/chat/stream` 接收 `mode` / `context.course_id` |

**一句话**：前端是一个"壳子"，但壳子上每个开关都标了真假。后端接进来时改的是**数据**，不是**界面**。

---

## 2. 交付清单（实测数据，非估算）

| 文件 | 行数 | 职责 |
|---|---:|---|
| `frontend/src/app/pages/nexus/NexusPage.vue` | 3967 | Nexus 三栏工作区主页面（v2.2 后含图标轨/抽屉/启动页预设卡，见 §13.4） |
| `frontend/src/api/nexusAdapter.js` | 421 | 演示/真实双数据源适配层（唯一的取数入口） |
| `frontend/src/api/nexus.js` | 140 | 真实模式 HTTP/SSE 客户端 |
| `frontend/src/api/nexusCapabilities.js` | 114 | **能力接线状态单一数据源**（后端接线的唯一开关） |
| `docs/phase1/Nexus_AI_前端开发规格与UX落地说明.md` | 本文档 | 开发规格与交接契约 |

**验证结果（2026-09-03 实测）**

```
# 契约测试
node --test src/api/__tests__/apiContracts.test.cjs
# tests 87 / pass 87 / fail 0

# 构建
npx vite build --emptyOutDir=false
✓ built in 12.52s
dist/assets/NexusPage-CQFWtO_r.js   50.09 kB
dist/assets/NexusPage-CeYa7gHr.css  19.29 kB

# Nexus Runtime 单测
cd nexus && .venv/Scripts/python.exe -m pytest -q
18 passed in 5.20s
```

> ⚠️ **构建注意**：`npm run build` 会被沙箱的批量删除保护拦截（清空 `dist/` 时 247 个文件超过阈值 50），报 `SAFE_DELETE_BULK_CONFIRM_REQUIRED`。**不是代码错误**，用 `npx vite build --emptyOutDir=false` 绕过。

**路由**：`frontend/src/app/router.js:90` → `/app/nexus`（`component: () => import('./pages/nexus/NexusPage.vue')`）
> `frontend/src/router/index.js` 是未挂载的旧文件，无 nexus 条目，改路由时不要改错文件。

---

## 3. 架构定位与信息结构

Nexus AI 是 CodeNexus 转型后位于**平台一级导航**的全局复杂任务智能体：

- **TeachingAgent**：课程内，负责单点答疑、代码挑战与知识点引导（course-scoped，工作流固定）
- **Nexus AI**：`/app/nexus` 全局入口，负责多步复杂任务拆解、论文检索与比较、实验复现规划

### 3.1 三栏结构（严守 `page-design.md` §4.1）

三层嵌套滚动模型（`height: 100%` + 内部 `min-height: 0; overflow-y: auto`），**禁止触发全页滚动**。

- **左侧 Local Rail**（`.nx-rail`，`--nexus-rail-width: 264px` / 折叠 `--nexus-rail-collapsed: 56px`，折叠态按 `page-design.md` §3.4 持久化到设备）
  新建会话（⌘K / Ctrl+K）、会话搜索、时间分组（置顶 / 今天 / 过去 7 天）、重命名、删除二次确认
- **中央主工作区**（`.nx-main`）
  Mode 下拉、数据源模式切换、Context Chips 状态行、Markdown 消息流 + 过程折叠卡片、自适应 Composer
- **右侧 Detail Panel**（`.nx-detail-panel`，`--nexus-detail-width: 340px`）
  上下文绑定情况、执行轨迹流（Activity Stream）、信息源状态

### 3.2 视觉令牌

沿用 `design.md` Academic Ink 主色（`--color-brand: #14213D`，`--surface-page: #F7F5EF`），Nexus 强调色**隔离**为独立令牌，不污染全局品牌色：

```
--nexus-accent: #007AF4
--nexus-accent-strong: #0563C4
--nexus-accent-soft: #E8F2FE
--nexus-accent-line: #A1D0FF
```

---

## 4. 设计决策固化

### 决策 A：Mode 映射真实工具白名单（而非换肤）

| Mode | 工具白名单 |
|---|---|
| `nexus_general` | `web_search` |
| `nexus_research` | `web_search` / `search_arxiv_papers` / `plan_reproduction` / `run_reproduction` |

下拉菜单显式展示「可用工具」。已与运行时实测对齐——`nexus/src/nexus/tools/__init__.py:5` 的 `NEXUS_TOOLS` 正是这 4 个。

### 决策 B：过程轨道「折叠成一行摘要 + 右栏展开」

正文默认清爽，工具调用折叠为 `[执行过程（调用 N 个工具）▾]`；完整事件流同步打入右侧 Activity Panel（时间戳 + 调用名）。既保留可解释性，又不打断 Markdown 主答复的阅读连续性。

### 决策 C：实验复现强制前置确认（Approval Gate）

`plan_reproduction` 完成后不静默执行，渲染复现卡片 + 「确认并开始复现」→ 弹出环境与 License 确认抽屉（`AGENTS.md` §4.1.10 未知仓库红线）。

> **本次已修正**：原实现点击确认后只是把文本塞回 Composer 重新发送（假执行）。现改为先查能力状态，未接通时渲染 `REPRO_WORKER_UNAVAILABLE` 卡片并明写「本次不会在任何环境里运行任何代码」。

### 决策 D：学习页入口 = 带上下文跳转 CTA

放弃在学习页内嵌聊天 Drawer（避免与助教面板 dock 冲突）。`AgentPanelHeader.vue` 右侧放 `[Nexus 深入 ↗]`，带入当前 `courseId` / `contextNode` 跳转 `/app/nexus`。

### 决策 E（新增）：能力三态模型 + 界面诚实标注

**所有装饰性 Chip 必须由状态驱动，禁止硬编码激活态。** 见第 5 节。

---

## 5. 能力三态模型 —— 后端接线的唯一开关

`frontend/src/api/nexusCapabilities.js` 是全前端**唯一**声明"某能力是否已接通"的地方。界面所有 Chip、徽标、计数、可执行性判断都从这里读，不允许在模板里写字面量。

### 5.1 三态语义

| 状态 | 含义 | 界面表现 |
|---|---|---|
| `ready` | 已接通，数据真实 | 实心 Chip，正常显示计数 |
| `wired` | 数据源存在，但**未注入回答链路** | 虚线边框 Chip + 「已接入未注入」提示 |
| `unwired` | 能力本身不存在 | 弱化虚线 Chip + **「未接入」徽标**，不显示任何计数 |

### 5.2 当前状态表（实测，2026-09-03）

| 能力 ID | 状态 | 依据 |
|---|---|---|
| `web_search` | `ready` | `nexus/src/nexus/tools/web_search.py` 已实现（SearXNG + DDG 降级） |
| `arxiv_papers` | `ready` | `nexus/src/nexus/tools/paper_search.py` 已实现 |
| `course_materials` | `wired` | 数据源存在（`course_build` 接口），但 `ChatRequest` 无 `context.course_id`，模型拿不到 |
| `cs_knowledge` | `unwired` | 所有生产向量检索均为 course-scoped（`lancedb_provider.py:50` schema `course-lancedb/1.0`），无 CS-scoped 路径 |
| `nexuslab_repro` | `unwired` | `reproduction.py:141` fail-closed 返回 `REPRO_WORKER_UNAVAILABLE`（Worker 未部署） |

### 5.3 后端接线时怎么改

**只改这一个文件的 `state` 字段**，界面自动跟着变。例如 CS 检索接通后：

```js
cs_knowledge: { state: CAPABILITY_STATE.READY, ... }
```

无需动 `NexusPage.vue` 任何一行。这是"留好接口"的落点。

---

## 6. 双数据源契约

`nexusAdapter.js` 是唯一取数入口，页面永远不直接调 `nexus.js`。

### 6.1 三种 `source`

```js
{ source: 'real',          ... }  // 真实接口返回
{ source: 'demo',          ... }  // 演示数据，界面顶部常驻「前端演示模式」提示
{ source: 'unavailable', error, ... }  // 真实接口失败，数值一律 null
```

**fail-closed 硬约束**：真实模式下接口失败时**禁止**回退到演示数字。原实现里 `|| 42381` 这种兜底会在后端挂掉时静默显示假数据，已全部改为 `?? null` + `source: 'unavailable'`，界面显示「—」而非编造的计数。

### 6.2 演示模式的流式仿真

`streamDemoMessage` 按真实 SSE 帧序发射：`tool_call` → `tool_result` → `token`（逐字）→ `done`，含真实 LaTeX、代码块、arXiv 论文卡片。事件形状与真实链路**完全一致**，后端接进来时前端无感知。

### 6.3 请求体契约（接线预留）

```js
POST /api/v1/nexus/chat/stream
{
  "message": "...",
  "session_id": "...",
  "mode": "nexus_research",        // 已发送，运行时当前未接收
  "context": { "course_id": 42 }   // 已发送，运行时当前未接收
}
```

前端已按此格式发送。**运行时一旦在两层 pydantic 模型加上这两个字段，前端零改动。**

---

## 7. 已核实的运行时事实（实测，不是读文档推的）

### 7.1 依赖隔离 —— 此前的一个担忧不成立

| 环境 | 版本（实测） |
|---|---|
| `nexus/.venv` | deepagents 0.7.12 / langgraph 1.2.11 / langchain-core 1.6.1 / langchain 1.3.18 |
| `backend/pyproject.toml` | `langgraph>=0.6,<0.7`，无 langchain-core |

两个环境物理隔离（独立 venv / 独立 pyproject / 独立进程），**依赖冲突不存在**。这是转型方案里设计得对的地方，重构时保住。

### 7.2 调用链路（已完整核实）

```
浏览器 ──JWT──> 后端 /api/v1/nexus/*  ──内部令牌──> Nexus Runtime :8300
                (nexus_proxy.py)                    (nexus/src/nexus/main.py)
```

- 后端代理注册于 `backend/app/main.py:376`，prefix `/api/v1/nexus`，与前端 `NEXUS_BASE + '/nexus/chat/stream'` 完全对齐
- 凭据交换：`nexus_proxy.py:64-82` **不转发用户 JWT**，改用 `X-Nexus-User-Id` / `X-Nexus-User-Role` 头 + 内部服务令牌 `NEXUS_RUNTIME_API_KEY`。**边界设计正确，保住。**
- 代理设置 `X-Accel-Buffering: no`（`nexus_proxy.py:260`），避免 Nginx 把 SSE 攒成一整块

### 7.3 运行时实际挂载的工具（内省实测）

```
delete, edit_file, execute, glob, grep, ls,
plan_reproduction, read_file, run_reproduction,
search_arxiv_papers, task, web_search, write_file
```

注意：**运行时工具比 `NEXUS_TOOLS` 多出 9 个**——deepagents 默认中间件挂载了全套文件系统工具与 `execute`（shell 执行）。

---

## 8. 已知缺陷清单

> **先撤回一条误判**：此前记录的「非流式 `/chat` 传 `stream_mode="updates"` 字符串会触发 ValueError」**经实测不成立**。`Pregel.astream` 文档串（langgraph 1.2.11）明确：`stream_mode` 为 list 且 `subgraphs=False` 时产出 `(mode, data)` 二元组，`main.py:68` 解包正确；`main.py:128` 字符串模式产出 dict，`.items()` 遍历也正确。此条作废，勿据此改代码。

### D1 · [P0] 默认 Deep Agent 带 shell 执行与文件写删，且无沙箱、无审批门 —— ✅ 已修复（2026-09-04，M0-B1）

**位置**：`nexus/src/nexus/agent.py:49-54`

`create_deep_agent` 未传 `backend` / `permissions` / `interrupt_on`，默认后端根落在**进程 cwd**（开发时为 `nexus/` 源码目录本身），默认挂载 `execute` + `write_file` + `delete`。

> **2026-09-04 严重度勘误**：实测 deepagents 0.7.12 默认 backend 为 `StateBackend`，文件读写落在 **LangGraph state 的 `files` 通道**（随 checkpoint 持久化），**不落宿主文件系统**；`execute` 因 StateBackend 未实现 SandboxBackendProtocol，调用时只返回错误消息、不真正执行 shell。故原记录"模型可直接改运行时源码"对当前版本不成立。但工具面暴露（12 个模型可见工具中 8 个非产品工具）与提示注入后的 context/state 污染风险属实，修复仍然必要。

**冲突**：`AGENTS.md` §4.1.1「不把学生代码放入主应用进程执行；代码执行经过独立沙箱服务（Judge0）」。Nexus Runtime 跑在应用侧进程，模型可直接改运行时源码。

**修法**（三选一，需决策）：
1. 整体禁用：`middleware` 里排除文件系统/`execute`，只留 `NEXUS_TOOLS`
2. 重定向到 Judge0：自定义 backend，把 `execute` 代理到已部署的 Judge0（注意 `deploy/docker-compose.yml` 未挂 docker.sock，且 Judge0 已移除 privileged）
3. 加审批门：`interrupt_on={"execute": True, "write_file": True, "delete": True}` + 后端 session 作用域隔离

> **已实施（修法 1 + 纵深，见 [CodeNexus_P2开发计划.md](CodeNexus_P2开发计划.md) M0-B1）**，三层防御：
> ① `FilesystemMiddleware(tools=["read_file"])` 同名替换默认全量实例——`write_file`/`edit_file`/`delete`/`ls`/`glob`/`grep`/`execute` 在 `__init__` 即不创建（结构性移除）；`read_file` 保留是因 SummarizationMiddleware 将压缩历史 offload 到 StateBackend，模型需读回。
> ② `HarnessProfile(excluded_tools=…)` 注册在 provider 键 `"openai"`——模型请求侧过滤 + 工具调用侧拒绝（`_ToolExclusionMiddleware` 双层机制），兜底上游默认工具集演进。
> ③ `GeneralPurposeSubagentProfile(enabled=False)` 结构性移除 GP 子代理与 `task` 工具（子代理栈会重新挂载文件工具）。
> 验收：`nexus/tests/test_agent_tools.py` 5 项全绿（执行器注册表 = `read_file` + 4 产品工具、模型可见面同、敌意 tool_call 全拒、结构性移除失效时排除层兜底）；`/health` 新增 `tool_surface` 巡检字段（uvicorn 实测返回 5 工具）。全量 34/34 passed。

**测试**：构造 `build_agent()` 后断言 `tools_by_name` 不含 `execute` / `delete`；或断言 `execute` 调用被拦截并返回明确错误码。

### D2 · [P1] `mode` 与 `context.course_id` 在两层模型被静默丢弃

**位置**：`backend/app/api/v1/endpoints/nexus_proxy.py:53-57` 与 `nexus/src/nexus/main.py:41-43`

两个 pydantic 模型都只定义 `message` / `session_id`，`extra` 为默认 `ignore`。

**实测**：
```
ChatRequest.model_validate({'message':'hi','session_id':'s',
                            'mode':'nexus_research','context':{'course_id':42}})
→ {'message': 'hi', 'session_id': 's'}      # 字段被吃掉
```

**后果**：Mode 切换在服务端无意义（模型仍能调 `execute`），课程资料永远注入不进来。

**修法**：两个模型各加字段，代理层 `payload.model_dump()` 已自动透传，无需改转发逻辑：
```python
mode: str | None = None
context: dict | None = None
```

**测试**：`POST /api/v1/nexus/chat` 带 `mode`/`context`，断言 Runtime 侧收到的 body 含这两个字段。

### D3 · [P1] `.env.example` 变量名与 `env_prefix` 不一致

**位置**：`nexus/.env.example:3` 写 `DEEPSEEK_API_KEY=`，`nexus/src/nexus/config.py:7` 是 `env_prefix="NEXUS_"`

照抄模板会读到空值 → `build_agent()` 抛 `LLM_NOT_CONFIGURED` → `/health` 正常但所有对话 503。排查成本很高。

**修法**：改成 `NEXUS_DEEPSEEK_API_KEY=`。

**测试**：断言 `.env.example` 中每个非空变量名都能被 `Settings` 识别。

### D4 · [P1] `tool_result` 600 字符硬截断导致 JSON 残缺

**位置**：`nexus/src/nexus/main.py:54-60`

`_summarize_tool_content` 直接 `[:600]`，web_search 的结构化 JSON 被切碎，前端无法还原来源列表。

**前端已加哨兵**：`sessionSources` 统计 `unparsable` 次数，>0 时在来源面板显式提示，不假装解析成功。**后端修好后这个计数自然归零，前端无需改动。**

**修法**：优先发结构化字段（`data.items`）而非序列化后截断；或至少截断完整 item 边界。

### D5 · [P1] 无 SSE `error` 事件，流中断时前端收不到终止信号

**位置**：`nexus/src/nexus/main.py:63-96`

`_agent_stream` 只产出 `token` / `tool_call` / `tool_result` / `done`。Agent 中途抛异常时连接直接断，**没有 `done` 也没有错误事件** → 前端会停在"进行中"。

**修法**：包一层 `try/except`，异常时产出 `event: error` + 稳定错误码，前端据此渲染失败态。前端需同步增加 `error` 分支（当前仅处理流异常终止）。

### D6 · [P1] SYSTEM_PROMPT 要求 todo，但运行时没有 todo 工具

**位置**：`nexus/src/nexus/agent.py:27`（规则 4「多步骤任务先建立 todo，逐步执行并勾选进度」）

**实测**：deepagents 0.7.12 全包检索，`write_todos` / `TodoListMiddleware` 仅出现在 2 个 harness profile 文件中，默认工具注册表（第 7.3 节）**无 todo 工具**。

**后果**：Prompt 要求一个不存在的工具，模型可能虚构进度文本——这直接违反 `AGENTS.md` §4.3 结果诚实性。

**修法**：注册 `TodoListMiddleware`（若版本支持）或删除规则 4；前端「执行过程」不展示任何未经事件确认的进度。

### D7 · [P2] `done.token_count` 统计的是字符数不是 token 数

**位置**：`nexus/src/nexus/main.py:74, 96`（`token_count += len(content)`）

若后续做计费/限额 UI，这个数会严重偏大。当前前端**不展示**该字段，暂不阻塞。

### D8 · [P2] 会话不持久化

**位置**：`nexus/src/nexus/agent.py:53`（`InMemorySaver`）

运行时重启会话全丢，与前端 localStorage 持久化不一致 → 切到真实模式后用户会看到"历史消失"。

**修法**：`PostgresSaver` + 会话列表接口；或明确接受"真实模式不保留历史"并在界面标注。

---

## 9. 值得保住的设计（重构时别拆）

1. **代理层双令牌交换**（`nexus_proxy.py:64-82`）：不转发用户 JWT，用 `X-Nexus-User-*` 透传身份 + 内部服务令牌。边界干净。
2. **建流失败时读完错误体按 JSON 透传**（`nexus_proxy.py:237-243`）：上游 503 时返回确定错误码，而不是一个空 SSE 流。前端能给出准确恢复提示。
3. **`run_reproduction` fail-closed**（`reproduction.py:141`）：Worker 未配置时返回 `REPRO_WORKER_UNAVAILABLE`，绝不假造执行结果。完全符合 `AGENTS.md`。
4. **独立 venv 隔离依赖**（第 7.1 节）：用一个环境边界解决了 langgraph 版本冲突，比在依赖上打补丁干净得多。
5. **`X-Accel-Buffering: no`**（`nexus_proxy.py:260`）：SSE 必需的部署细节，容易漏。

---

## 10. 仍待讨论的问题

| # | 问题 | 需要你提供的信息 |
|---|---|---|
| Q1 | **Nexus 是全局入口，但权限层没有全局维度**：`PlatformPermission` 仅 6 项无 Nexus 项，`CourseAccessContext.course_id` 非空。谁能用 Nexus？学生能用吗？要不要配额？ | 目标用户范围；是否需要新增 `platform.nexus.use` 权限项；配额策略 |
| Q2 | **会话归属**：Nexus 会话是用户全局的，还是归属某个课程？右侧绑定课程上下文时，会话列表按哪个维度过滤？ | 会话模型定义；全局会话与课程会话是否需要隔离存储 |
| Q3 | **CS 知识库要不要接**：`discipline_knowledge` 端点是只读检索，能否作为 Nexus 的 RAG 数据源？还是本阶段明确保持 `unwired`？ | 该端点的数据规模/更新频率；是否允许进入回答链路 |
| Q4 | **`execute` 工具怎么处理**（对应 D1/P0）？整体禁用 / 重定向 Judge0 / 加审批门？这决定 NexusLab 复现的实现路径 | 对"Agent 在服务器上执行命令"的接受边界；Judge0 复用方案是否可行 |
| Q5 | **复现 Worker 是否真的要建**？保守方案是长期保持 `REPRO_WORKER_UNAVAILABLE`，只做"复现计划"不做"复现执行" | 是否接受"只规划不执行"；若执行，Worker 部署形态与资源限额 |
| Q6 | **会话持久化**（对应 D8）：上 PostgresSaver 还是接受重启即丢？前端 localStorage 与后端会话列表谁做主？ | 持久化优先级；是否允许真实模式下历史不跨设备 |
| Q7 | **Mode 要不要在服务端强制约束工具白名单**（对应 D2）？当前 mode 根本没传到 Runtime，模型在 General 模式下也能调 `execute` | Mode 的语义强度：是"建议"还是"硬约束" |
| Q8 | **`token_count` 口径**（对应 D7）：是否要接真实 tokenizer？影响后续计费/限额 UI | 是否有计费或限额计划 |

---

## 11. 回归命令

```bash
# 前端契约测试（87 项）
cd frontend && node --test src/api/__tests__/apiContracts.test.cjs

# 前端构建
cd frontend && npx vite build --emptyOutDir=false

# Nexus Runtime 单测（18 项）
cd nexus && .venv/Scripts/python.exe -m pytest -q
```

改动 `nexusCapabilities.js` 的 `state` 字段后，必须重跑契约测试与构建。

---

## 12. 可用性与视觉重构（2026-09-03 第二轮，已落地）

> 背景：第一轮实现完成并经演示后，按「使用便捷性 + 功能相关性」评审结论重构
> `NexusPage.vue`（组件类型不变：三栏壳、SfxButton / SfxDrawer、能力三态机制全部保留）。

### 12.1 已拍板并落地的三个决策

| 决策 | 落地位置 |
|---|---|
| 数据源切换收敛到侧栏底部状态区（唯一入口，点击弹 演示/真实 菜单）；顶部改为一条互斥状态条（演示说明 / 真实模式健康错误） | `NexusPage.vue` rail foot `.nx-ds-*`、`.nx-status-strip` |
| 首屏 Chips 只保留 ready 能力 + 课程绑定；wired/unwired 收进「◇ N 项待接入」popover（含状态标签与提示，诚实性不变） | `.nx-chip.is-ready` / `.nx-chip.is-pending` + `.nx-popover` |
| 右栏大数字统计块废除，改为「能力状态」列表（● 已接通 / ◌ 数据就绪·未注入 / ◌ 未建立），与 Chips 同读 `nexusCapabilities.js` 单一真相源 | 右栏 Context pane `.nx-cap-*` |

### 12.2 同步落地的可用性修复

- **移除三个无行为死控件**：header「添加上下文」、Composer `@`、Composer 回形针——它们此前只 set 一个从未渲染的 popover ref。文件上传在 `nexusCapabilities.js` 新增 `file_upload`（unwired）如实进入「待接入」popover，Composer 不再渲染假上传按钮。
- **修复 `isToolExpanded` 未定义**：模板使用但脚本从未定义，展开「执行过程」卡即运行时报错。已补齐（并顺手修复模板类名与样式块错位：`nx-session-action-sfx`/`nx-rail-toggle-sfx`/`nx-dtab-sfx`/`nx-tool-sfx-btn` 等原来无样式生效）。
- **运行状态行**：流式期间常驻 `◌ 正在… mm:ss`（mono 计时），满足规格 §54.3；完成后收敛为「执行过程 · N 次工具调用 · 12.4s」折叠摘要。
- **会话项两行化**（标题 + 模式·时间）+ More 菜单（置顶/重命名/导出 Markdown/删除两段式确认）——`togglePinSession` 此前是无入口死代码；导出为纯客户端 Markdown（数据本就仅存本机，操作真实可兑现）。
- **信息源 tab 计数角标**；发送后自动切「执行轨迹」tab。
- **其他**：新建会话按钮 ⌘K 提示改 tooltip（修复文字重叠）；重命名图标 FileCode→Pencil；补「更早」分组（此前 computed 有、模板无）；浮层点击外部关闭 + Escape 关闭；自绘可点元素统一 `:focus-visible` 焦点环；课程卡「更换」按钮独立成行（修复挤压）。

### 12.3 视觉方向（token 纪律）

- **#007AF4 收敛到 3 个职责**：Mode 标识（logo mark + 模式菜单激活项）、live 进行中（流式头像/运行状态行/计时点）、外链。其余蓝色（session 激活图标、空态徽标、tab 下划线、hover 边框）退回墨蓝/石墨。
- **Signature「实验记录轨」**：过程层统一 `surface-cool` 底 + 状态点 + mono `HH:MM:SS` + 左侧细竖线，贯穿消息流过程卡、右栏执行轨迹、复现状态卡、能力状态列表。
- **Workspace header 双细线**（2px 墨蓝 + 1px 灰，arXiv 论文头惯例）+ 空态 mono 眉标（NEXUS / NEXUS RESEARCH）。
- **字号全部回归令牌**（caption 12px 为下限，清除原 10px/11px 硬编码）；补齐 `.nx-markdown-body` 的 `:deep()` 表格/代码块/引用块样式。
- 文案去 dev 腔：演示条改为「由浏览器本地模拟，不会发送到服务器；会话仅保存在本机」；「精准 RAG」→「回答会参考这门课的资料」；空态标题改动词句。

### 12.4 本轮验证

- 契约测试 `node --test src/api/__tests__/apiContracts.test.cjs`：**87/87 通过**（含 NexusPage SfxButton 规范、无原生 button、工具过程可见、真实错误码等专项）。
- `pnpm run build`：通过（chunk >1000kB 警告为既有问题，非本轮引入）。

### 12.5 第三轮微调（2026-09-03，同日）

- Mode 切换按钮去掉左侧 logo-mark（与全局主导航品牌标重复）。
- ~~**右栏回应区改为桌面常驻**，移除收起/展开开关（产品决定：过程与来源必须始终可见）；窄屏仍按断点隐藏。~~
  **已被 §13 推翻（2026-09-04 家良拍板）**：改为 48px 图标轨（常驻入口 + 计数徽标）+ 320px overlay 抽屉（按需全景，开合按设备持久化）。理由见 §13.2-1。
- Composer 悬浮化：外层 `.nx-composer-box` 背景透明、去分隔线，白色卡片（`radius-lg` + `shadow-sm`）浮于消息区下缘。
- 澄清记录：模型选择器为**有意砍掉**（运行时单模型 `NEXUS_LLM_MODEL`，无请求级 model 参数，切换不生效；"Nexus 4.0" 命名有自研误导风险），现为 Composer 左下只读引擎标识；恢复真选择器的前提是 Runtime 提供 `/models` + 请求级 model 字段。权限控制**未删**：按 §18.4 共识不做每工具权限模式，复现执行的 Approval Gate（License/沙箱确认弹窗 → `REPRO_WORKER_UNAVAILABLE` 如实落卡）仍为强制门。

### 12.6 回答操作条与流式平滑（2026-09-03，同日）

- 每个回答底部操作条：复制 / 重试 + 右侧「由 AI 生成」。
  - 复制：`navigator.clipboard`（降级 textarea 方案）复制 Markdown 原文，toast 反馈。
  - 重试：`send()` 拆出共享执行体 `runTurn(message)`，重试为同一问题追加新 turn（保留历史证据链，不覆盖原回答）；流式中禁用。
  - ~~点赞/点踩：评价服务未接入，点击只弹轻提示，不伪造"已反馈"。~~
    **已于 §13（P1-3）移除**：占位按钮制造"能反馈"的错觉。恢复前提是后端提供评价落点，届时在 `nexusCapabilities.js` 增 `feedback` 条目，UI 自动出现。
- 「突进式」输出修复：模板禁止逐 token 直接调 `renderContent`，一律走 `renderedAnswer`（WeakMap 缓存 + 200ms 节流，引用不变时 `v-html` 不写 DOM）；滚动改为 rAF 合并且仅底部附近跟随（上滑阅读不再被拽回）；demo 发射器 3 字/25ms → 5 字/35ms。契约测试 89/89（含新增节流回归断言）。

---

## 13. UX 评审与布局改版（2026-09-03 第三轮 · 设计板驱动）

> **配套视觉稿**：`docs/phase1/2026-09-03_Nexus_UX评审与布局改版设计板.html`（Board A 改版全景 / Board B 右栏两态与文案规范 / Board C 新会话启动页，含改动映射表与代码落点）。
> **改版约束**：不改变页面功能组件类型——三栏模型内的既有组件全部保留，只做布局重排、入口收敛、状态文案统一。

### 13.1 评审结论（便捷性 × 功能相关性，均有截图/源码双证据）

| 编号 | 级别 | 问题 | 根因 | 修法 | 状态 |
|---|---|---|---|---|---|
| P0-1 | P0 | 右栏桌面常驻 340px 不可收起（原 :1527 `v-if="!isTablet && !isMobileOrSmall"`），纯问答轮次主区被压到 ~590px | §12.5 产品决定「过程与来源始终可见」的直接代价 | 改 48px 图标轨（三个 tab + 真实计数徽标）+ 320px overlay 抽屉。**本条推翻 §12.5 决定** | ✅ 已实施（§13.4-1） |
| P0-2 | P0 | 左栏底部系统状态（数据源）/内容库（本机资料）/视图控制（收起）三类信息混排；「产物」无真实数据源仍显示裸计数 | 设备区无信息分层规范 | 底部收敛为「本机状态」卡两行：`数据源 / 演示数据｜切换`、`本机资料 / 聊天记录 · 复现 N · 产物 M｜展开`（去裸计数，无数据时行降级为不可点） | ✅ 已实施（§13.4-2） |
| P1-3 | P1 | 赞/踩按钮无数据通道仍渲染（原 :1455-1474 `feedbackSoon` 占位） | 操作条按"完整回答 UI"一次画全，未按能力状态裁剪 | 直接砍掉（不留「更多」折叠——折叠还是占位）；恢复前提：后端提供评价落点，届时 `nexusCapabilities.js` 增 `feedback` 条目，UI 自动出现 | ✅ 已实施（§13.4-3） |
| P1-4 | P1 | 课程绑定双入口（chips 行 + 右栏大卡），低频设置常驻首屏 | 上下文卡承担了"引导"职责，但引导属于启动页 | 顶部 chips 行移除课程 chip；引导条移至启动页（`.nx-start-course`）；对话中的入口收敛到右栏「上下文」面板的「更换课程」 | ✅ 已实施（§13.4-4） |
| P1-5 | P1 | 空态有示例问题、无模式感知；工具白名单差异藏在 Mode 下拉里 | 启动动线未前置模式选择 | 空态升级启动页：模式预设卡 ×2（含工具 pills，与 `NEXUS_MODE_CONFIG.tools` 同源，点击即 `switchMode`）+ 示例问题 + 课程引导条 | ✅ 已实施（§13.4-5） |
| ~~P1-6~~ | — | ~~会话重命名/置顶/删除入口不可见~~ | — | — | ❌ **原判断错误，撤回**（§13.5） |
| ~~P2-7~~ | — | ~~Composer 下方两个无标注浮动圆钮~~ | — | — | ❌ **原判断错误，撤回**（§13.5） |
| P2-8 | P2 | 状态文案四套词混用（已接通 / 数据就绪·未注入回答 / 数据就绪 / 未建立） | 展示层无统一映射 | 统一三态：**已生效 / 已连接·未生效 / 未建立**；只改 `capStateText()` / `capStateTagText()` 展示映射，nexusCapabilities 数据结构不动 | ✅ 已实施（§13.4-6） |
| P2-9 | P2 | 失败轮次的过程折叠行仍呈中性"完成"观感（如 ARXIV_UNAVAILABLE） | 折叠行无失败状态类 | `is-failed` 类（turn.failure 或存在 status=error 的 tool_result）→ amber 底 + amber 左边框 + `TriangleAlert` 图标，摘要补「· N 次失败」 | ✅ 已实施（§13.4-7） |

**值得保住（改版红线）**：能力三态单一真相源（nexusCapabilities.js 数据结构零改动）、「N 项待接入」popover、Mode 即工具白名单、过程折叠摘要 + 详情面板分工、fail-closed 演示状态条、只读引擎标识。

### 13.2 两个悬置问题的结论（2026-09-04 拍板 / 排查完成）

1. **右栏：选图标轨**（家良 2026-09-04 拍板）。取舍：图标轨把「全程全景可见」降级为「全程可入口 + 按需全景」，换来主区 +292px。为守住 §12.5 原本要保护的可见性，图标轨上补了两件事：
   - 信息源图标挂**真实计数徽标**（`sourcesTotal`，不是占位数字）；
   - 执行轨迹图标在抽屉收起时挂**琥珀未读点**（`unseenActivity` 计数，`tool_call`/`tool_result` 到达时 +1，打开该面板即清零）。
   因此"有没有新过程"始终可见，只是不再强制占用横向空间。抽屉开合状态按设备持久化（localStorage `nexus_detail_open`，与 `nexus_rail_collapsed` 同一机制，符合 page-design §3.4）。
2. **P2-7 浮动圆钮：不存在，撤回**。全仓排查结论见 §13.5。

### 13.3 本轮不动的部分

- 全局导航、品牌标识、Academic Ink + `--nexus-accent` 令牌体系；
- 三栏模型本身（page-design §4.1）；
- 所有与后端接线的契约（第 7 节）与能力三态数据结构（第 5 节）；
- 组件类型不变（改版约束）：新增的图标轨/抽屉/预设卡都是既有 `SfxButton` + 原生 div 组合，未引入新组件依赖。

---

### 13.4 实施结果（2026-09-04，全部落地并验证）

验证基线：契约测试 **89/89 通过**；`npx vite build --emptyOutDir=false` **通过**（13.75s）。

**1. 右栏图标轨 + overlay 抽屉（P0-1）**
- 结构：`.nx-detail-zone`（`position: relative` 的 48px 容器）内，`.nx-detail-drawer` 绝对定位 `right: var(--nexus-detail-rail)`、`width: var(--nexus-detail-width)`、`z-index: 30`、左侧投影；`.nx-detail-rail` 为常驻 48px 图标轨。抽屉覆盖主工作区右侧，不改变主内容宽度。
- 新增令牌（`frontend/src/app/styles/tokens.css`）：`--nexus-detail-rail: 48px`（`--nexus-detail-width: 340px` 复用为抽屉宽度）。
- 交互：`selectDetailTab(id)` —— 点不同 tab 切换并展开；点当前已展开的 tab 收起。抽屉头显示当前面板名 + 语义提示 + 收起按钮。
- 兜底：流式开始仍自动把 `activeDetailTab` 切到 `activity` 并清零未读，**但不强制展开抽屉**——尊重用户上一次的开合选择；此时新到达的事件通过琥珀未读点提示。

**2. 左栏「本机状态」区（P0-2）**
- 三层平铺 → 一个带标题的状态卡：行 1 `数据源 / 演示数据｜切换`（原有 popover 逻辑不变），行 2 `本机资料 / <摘要>｜展开`。
- `localResourcesSummary` 计算摘要：无数据显示「仅聊天记录」，有数据显示「聊天记录 · 复现 N · 产物 M」——不再出现孤立的「N 个会话」。
- 无数据时行 2 加 `.is-static`（光标/配色降级），点击给 toast「这台设备还没有产物或复现记录」而不是静默无响应。
- 删除 `.nx-rail-resources` / `.nx-ds-status` / `.nx-ds-text` 旧样式与对应模板块。

**3. 移除赞/踩（P1-3）** 删除两个 `SfxButton`、`feedbackSoon()` 函数与 `ThumbsUp/ThumbsDown` 图标导入；操作条只保留复制 / 重试 + 「由 AI 生成」。

**4. 课程入口收敛（P1-4）** 顶部 chips 行移除课程 chip（含 `.nx-chip-btn` 样式）；启动页新增 `.nx-start-course` 引导条（已绑定显示课程名 + 「更换」，未绑定显示「未绑定课程 · 回答只会用到 Web 与通用知识」+「绑定课程」）；对话中的入口为右栏「上下文」面板的「更换课程」。

**5. 启动页升级（P1-5）** `.nx-mode-cards` 两张预设卡，与 `NEXUS_MODE_CONFIG` 同源渲染 label / desc / tools pills，点击即 `switchMode(key)`，当前模式加 `.is-active`（accent 描边 + soft 底）+ `Check`。

**6. 状态文案统一（P2-8）** `capStateText()` / `capStateTagText()` 统一为 `已生效` / `已连接 · 未生效` / `未建立`。原四套词（已接通 / 数据就绪·未注入回答 / 数据就绪 / 未建立）全部替换；`capStateTagText` 此前对 ready 态返回空串导致标签缺失，现补齐。

**7. 失败过程折叠行（P2-9）** `.nx-process-summary-card.is-failed`（amber 底 + amber 左边框，badge 转 `amber-700` + `TriangleAlert`）；`failedToolCount(turn)` 统计 `status === 'error'` 的 tool_result，`processSummaryLabel` 追加「· N 次失败」。

**8. 顺带修的键盘可达性缺陷**：`.nx-session-more` 此前只靠 `:hover` 显示，Tab 用户无法触达。补 `:focus-within` 选择器。

---

### 13.5 撤回的两条（记录错误判断，避免重犯）

> 这两条都是**没量就下判断**的产物，和 §8 里那条已作废的 `stream_mode` 判断是同一类错误。留档提醒。

- **~~P1-6~~ 会话行操作组不可见 —— 判断错误，实际已实现。**
  代码事实：`NexusPage.vue` `.nx-session-more { display: none }` + `.nx-session-item:hover .nx-session-more { display: block }`，操作组（置顶 / ⋯ → 重命名·删除）本来就是 hover 显示。真正的问题只有一个：`:hover` 之外键盘用户进不去，已用 `:focus-within` 补上（§13.4-8）。
- **~~P2-7~~ Composer 下方两个浮动圆钮 —— 不存在。**
  排查范围与结论：`main.js` 只挂载 `App`；`App.vue` 仅 `<router-view />`；`NexusPage.vue` 内无任何 `position: fixed/absolute` 的浮动圆钮；全仓唯一全局 `position: fixed` 是 `PrimaryNav.vue:454` 的移动端导航抽屉。**代码中不存在这两个按钮。**
  错误成因：这条来自对截图的推断——本会话的图片输入被过滤，我实际看不到图，却按"图里有两个圆钮"写了结论。以后凡是"我在截图里看到 X"的判断，先确认能不能真的看到图再说。
