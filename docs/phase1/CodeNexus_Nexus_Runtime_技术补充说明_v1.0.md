# CodeNexus Nexus Runtime 技术补充说明 v1.0

> 适用文档：`CodeNexus 转型设计与实施方案 v1.2`  
> 目标读者：AI 编码智能体 / 后端开发者  
> 技术事实核验时间：2026-09-02  
> 目的：补充 v1.2 中容易被误读的依赖、Runtime、Profile、Checkpoint、Paper Research 与 Sandbox 技术事实。本文优先级高于 v1.2 中与这些细节发生冲突的宽泛描述。

---

# 1. 最重要的事实：旧 Backend 与新 Nexus Runtime 存在硬依赖冲突

当前 `feature/xh202620` 的：

```text
backend/pyproject.toml
```

已经明确约束：

```toml
requires-python = ">=3.12,<3.13"

dependencies = [
    ...
    "langgraph>=0.6,<0.7",
    ...
]
```

因此当前 Backend 属于：

```text
Legacy Agent Runtime Generation
LangGraph 0.6.x
```

截至 2026-09-02，Deep Agents 最新稳定 release 为：

```text
deepagents == 0.7.12
```

其当前依赖要求包括：

```text
langchain >= 1.3.18, < 2.0.0
langchain-core >= 1.6.1, < 2.0.0
```

而当前 LangChain `1.3.18` 又明确依赖：

```text
langgraph >= 1.2.11, < 1.3.0
```

所以：

```text
旧 Backend：
langgraph < 0.7

Deep Agents 当前生态：
langgraph >= 1.2.11
```

这不是“也许有冲突”。

这是：

# **不可在同一个 Python dependency environment 中满足的硬冲突。**

因此禁止做：

```bash
cd backend
uv add deepagents
```

也禁止为了安装 Deep Agents 直接把：

```toml
langgraph>=0.6,<0.7
```

改成：

```toml
langgraph>=1.2
```

这样做会把 Teaching / Prep / Legacy Agent 一起拖入未经验证的大版本迁移。

---

# 2. 正确的依赖拓扑

允许：

```text
同一个 Git Repository
```

但不允许：

```text
同一个 Python Environment
```

推荐：

```text
ai-course-system/
│
├── backend/
│   ├── pyproject.toml
│   ├── uv.lock
│   └── .venv/
│
└── services/
    └── nexus-runtime/
        ├── pyproject.toml
        ├── uv.lock
        └── .venv/
```

两个项目拥有：

```text
独立 pyproject
独立 uv.lock
独立 virtualenv
独立 process
最好独立 container
```

它们可以在同一个 monorepo。

但是 Nexus Runtime 不能：

```python
from app.platform.agents...
from app.services...
from backend.app...
```

直接 import Backend 业务代码。

两个服务通过：

```text
HTTP / SSE / JSON Tool API
```

或经过验证的其他进程间接口通信。

---

# 3. 不要把“独立 Runtime”误解为“重写整个 Backend”

Nexus Runtime 只负责：

```text
Agent Harness
Agent Thread
Model / Tool Loop
Context / Compaction
Checkpoint / Resume
Tool Exposure
Approval / Interrupt
Streaming
Subagent
Workspace reference
```

现有 Backend 继续负责：

```text
User
Auth
RBAC
Course
CS Knowledge
Course Knowledge
Evidence
Citation
Teaching Agent
RE-KT
Judge0
业务数据库
对象存储
```

关系：

```text
Nexus Runtime
      │
      │ Tool Request
      ↓
Existing Backend API
      │
      ↓
Existing Domain Service
```

不要为了 Nexus：

```text
复制数据库
复制 RAG
复制课程模型
复制用户表
```

---

# 4. Nexus Runtime 的依赖安装策略

## 4.1 第一原则

不要一开始人工拍脑袋固定一整套 LangChain / LangGraph 子依赖版本。

优先让：

```text
Deep Agents 的官方 dependency constraints
```

决定兼容版本。

当前可做的最小 dependency spike：

```text
新建干净 nexus-runtime Python 3.12 环境
        ↓
安装固定版本 deepagents
        ↓
安装实际模型 Provider
        ↓
让 uv 求解 transitive dependencies
        ↓
运行最小 Agent
        ↓
确认正常
        ↓
提交 uv.lock
```

截至本文核验时间，可以从：

```toml
deepagents==0.7.12
```

开始 Spike。

如果实际模型通过 OpenAI / OpenAI-compatible API：

```text
额外评估 langchain-openai
```

如果实际使用 Gemini / Anthropic，则使用与当前 Deep Agents 版本兼容的相应 Provider。

不要把旧 Backend 的：

```text
app.common.llm_client
```

直接 import 进 Nexus Runtime。

Nexus Runtime 应拥有自己的：

```text
Model Provider configuration
```

可以继续使用同一个外部模型 API，但代码依赖与生命周期要独立。

---

## 4.2 是否需要手工写 `langgraph==...`

初始阶段：

> **不建议为了“看起来明确”而重复 pin 所有 transitive dependencies。**

例如当前 Deep Agents → LangChain 已经给出了 LangGraph 兼容范围。

更合理：

```text
pin 顶层能力包
+
生成 lockfile
```

例如：

```text
deepagents == 已验证版本
model-provider == 已验证版本
```

然后：

```bash
uv lock
uv sync
uv tree
```

检查真实解析结果。

如果项目代码直接 import 某个 LangGraph API，或者后续需要对其版本建立明确兼容承诺，再增加与当前 Deep Agents / LangChain 兼容的显式 constraint。

但无论如何：

```text
Nexus Runtime 的 LangGraph 必须属于它自己的 dependency graph。
```

不能与 Backend 0.6 共用。

---

# 5. 当前版本事实快照

截至 2026-09-02，已核验：

| 组件 | 当前事实 |
|---|---|
| `ai-course-system/backend` | Python `>=3.12,<3.13` |
| 旧 Backend LangGraph | `>=0.6,<0.7` |
| Deep Agents latest stable | `0.7.12` |
| Deep Agents Python | `>=3.11,<4.0` |
| Deep Agents → LangChain | `>=1.3.18,<2.0.0` |
| LangChain `1.3.18` → LangGraph | `>=1.2.11,<1.3.0` |
| `langgraph-checkpoint-postgres` current repo version | `3.1.2` |
| checkpoint-postgres driver | `psycopg >=3.2` / `psycopg-pool >=3.2` |
| 旧 Backend PostgreSQL driver | `psycopg2-binary >=2.9.9,<3` |

最后两项也说明：

> 不要试图让新 Nexus Runtime 的 Checkpointer “顺便复用旧 Backend Python driver”。

它们处于不同 Python 环境，分别管理即可。

版本以后可能继续更新。

编码智能体开始施工前应：

```text
重新查看 upstream release
↓
确认 release notes
↓
做 dependency spike
↓
再 pin
```

本文数字是技术事实快照，不是永久版本圣旨。

---

# 6. Deep Agents、LangChain、LangGraph 的职责关系

不要把三者理解成三个互相竞争的 Agent Framework。

当前建议关系：

```text
Deep Agents
│
│ 提供 batteries-included Harness
│
├── filesystem
├── context management
├── summarization
├── skills
├── subagents
├── middleware
├── backend abstractions
└── harness configuration
        │
        ↓
LangChain Agent
│
│ 提供 model ↔ tool execution loop
│
        ↓
LangGraph
│
├── graph/state runtime
├── checkpoint
├── interrupt
├── resume
└── durable execution
```

因此 Nexus 不需要再自己写一套：

```text
IntentPlanner
→ DynamicToolSelector
→ route_tools
→ one action
```

作为主执行模型。

---

# 7. 一个非常容易误解的词：Profile

v1.2 中写：

```text
General Profile
Research Profile
```

这是：

# **CodeNexus 产品层 Profile / Mode**

它表达：

```text
当前用户点击的是 Nexus
还是 Nexus Research
```

它不等价于：

```text
必须创建两个 Deep Agents HarnessProfile 类
```

也不要求机械使用 Deep Agents 内部某个叫 `HarnessProfile` 的具体 API。

---

## 7.1 产品层要求

产品上必须保持：

```text
同一个 Nexus AI
同一个 Session 体验
一个 Mode Switch
```

Research 打开后：

```text
Prompt 轻微变化
+
额外 Paper Tools
+
额外 Research Skills
+
NexusLab
+
更严格 Citation policy
```

---

## 7.2 框架层允许多种实现

编码智能体应根据 Deep Agents 当前 API 选择最稳定的实现。

例如可能是：

### 方案 A

一个统一 Agent Graph：

```text
same graph
same thread
mode-aware middleware
dynamic tool filtering
```

这是最符合“同一 Session Mode Switch”的实现。

### 方案 B

两个 Agent factory/config：

```text
general config
research config
```

但由同一个产品 Session 管理。

如果两个 compiled graph 要共享同一个 checkpoint/thread：

> 必须先写真实测试确认 state schema、middleware state 和恢复语义兼容。

不能因为“它们都叫 Deep Agent”就假设 checkpoint 可以无条件互换。

---

# 8. Mode 建议不要写进 System Prompt 作为唯一权限控制

错误：

```text
System prompt:
你现在是 General Mode，请不要调用 Paper Tool。
```

然后实际上 Paper Tool 仍然暴露给模型。

权限不能只依赖 Prompt。

正确：

```text
mode
↓
Capability Policy
↓
实际 Tool Set
↓
Model
```

Research-only Tool 在 General 下应该：

```text
不可见
或
在 Tool Boundary 被拒绝
```

Prompt 只是行为指导。

Tool Registry / Middleware / Policy 才是真权限。

---

# 9. Checkpoint、Store、Personal Memory 是三件不同的东西

## 9.1 Checkpointer

回答：

> 这个 Agent Thread 执行到哪里了？

保存：

- graph state；
- messages；
- interrupt；
- pending execution state；
- resume 所需状态。

如果只用内存 Checkpointer：

```text
进程重启
=
状态丢失
```

所以：

> 不能在使用内存 Saver 时宣称“支持服务崩溃后 Resume”。

---

## 9.2 Persistent Checkpointer

需要：

```text
process restart
→ resume
```

时，使用真正持久化的 Checkpointer。

当前 LangGraph 官方存在：

```text
langgraph-checkpoint-postgres
```

截至本文核验版本：

```text
3.1.2
```

它使用：

```text
psycopg v3
```

如果采用：

- 独立 Nexus PostgreSQL schema/database；
- 正确 setup/migration；
- stable thread_id；

再进行 Crash / Resume 测试。

---

## 9.3 Store

Store 用于：

```text
跨 thread 的长期数据
```

它和 Checkpointer 不一样。

不要把：

```text
checkpointer
store
personal memory
```

写成同一个对象。

---

## 9.4 Personal Context

Personal Context 是产品能力：

```text
用户长期偏好
目标
项目背景
输出偏好
```

候选：

```text
Mem0
```

它不应该承担 LangGraph Checkpoint。

也不应该存 RE-KT Learner Model。

---

# 10. Session / Run / Thread 必须区分

建议至少在概念上区分：

```text
Product Session
Agent Thread
Agent Run
```

### Product Session

用户看到的一条 Nexus 会话。

### Agent Thread

LangGraph durable state 的逻辑线程。

### Agent Run

一次具体执行：

```text
用户发送消息
→ 模型
→ 多次 Tool
→ 本轮完成/暂停/失败
```

一个 Thread 可以有多个 Run。

不要每个用户消息都创建新的 thread_id。

否则：

```text
Context
Checkpoint
Resume
```

全部失去意义。

---

# 11. Cancel 与 Interrupt 不是一回事

### Interrupt

典型：

```text
Agent wants GPU
↓
approval.required
↓
pause
↓
user approve
↓
resume same thread
```

### Cancel

用户：

```text
Stop
```

含义是：

```text
停止当前 Run
```

并尽量向：

- Tool；
- subprocess；
- sandbox command；
- subagent；
- reproduction job；

传播取消。

不能只：

```text
前端停止 SSE
```

但后台 shell 继续跑半小时。

---

# 12. Backend Tool Adapter 的正确边界

Nexus Runtime 调用现有系统能力时，不要：

```python
from backend.app.services.course_xxx import ...
```

建议：

```text
Nexus Tool
↓
Backend Client
↓ HTTP
Internal Backend Endpoint
↓
Existing Service
```

返回尽量结构化：

```json
{
  "items": [],
  "citations": [],
  "scope": {},
  "trace_id": "..."
}
```

Backend 仍负责：

```text
course permission
user permission
source scope
data access
```

Nexus 不自行复制权限逻辑。

---

# 13. Internal Tool API 也必须进行权限校验

错误思路：

```text
“这是内网 API，所以无需权限”
```

Nexus Agent 是动态 Tool Caller。

即使内部接口，也必须至少能够识别：

```text
谁
在哪个 course
拥有哪种 capability
```

可以采用：

- user-scoped delegated token；
- signed internal request；
- service identity + explicit user context；

具体方案由当前鉴权架构决定。

但不能：

```text
nexus-runtime 拿一个超级管理员 token
然后所有 Tool 都无条件访问全部课程
```

---

# 14. PaperQA 的集成不能直接假定“装进 Nexus Runtime”

v1.2 把：

```text
Future-House/paper-qa
```

列为 Paper Research 的优先候选。

这个方向仍然成立。

但需要补充一个关键事实：

当前 PaperQA 是一个独立且依赖不小的科学 RAG 项目。

截至本文核验，其基础依赖包括：

```text
fhaviary
fhlmi
httpx
numpy
paper-qa-pypdf
pybtex
pydantic-settings
tantivy
tiktoken
...
```

还拥有：

```text
docling
local
memory
qdrant
office
zotero
...
```

多个 optional extras。

因此编码智能体不应直接：

```bash
cd services/nexus-runtime
uv add "paper-qa[everything]"
```

---

# 15. Paper Research 的正确集成流程

先做：

```text
PaperQA Compatibility Spike
```

在一个干净临时环境验证：

```text
Python version
installation
basic search
basic query
provider config
dependency tree
startup cost
memory usage
```

然后选择：

### 模式 A：Library Adapter

如果依赖兼容且轻：

```text
Nexus Runtime
↓
PaperQAAdapter
↓
paper-qa package
```

### 模式 B：Sidecar / Tool Service

如果依赖树过重或与 Nexus 冲突：

```text
Nexus Runtime
↓ HTTP
Paper Research Service
↓
PaperQA
```

### 模式 C：替换其他成熟实现

如果当前 PaperQA 在实际环境：

- 不稳定；
- API 大改；
- Provider 不适合；
- 部署成本过高；

允许换成熟方案。

产品要求是：

```text
真实 Paper Search
真实 Evidence
真实 Citation
```

不是“必须导入某个 Python package”。

---

# 16. PaperQA 与 Docling 不要重复堆叠

现有 Backend 已经使用 Docling。

PaperQA 也存在 Docling optional integration。

不要因此默认：

```text
同一 PDF
→ Backend Docling
→ PaperQA Docling
→ 再解析一次
```

需要明确用途：

### Course / Existing Document

继续走现有 CodeNexus Document Pipeline。

### Paper Research 外部论文

如果 PaperQA 自己管理 corpus 最简单，可以由 PaperQA 管。

### Quick Reproduction 单篇 PDF

P0 可以直接：

```text
Docling
→ markdown
→ Claim extraction
```

不要求经过 PaperQA。

---

# 17. Quick Reproduction 的 Docker 边界

这是 v1.2 最容易被编码智能体“写出一个能跑但非常危险”的地方。

禁止默认实现：

```text
Internet-facing nexus-runtime container
+
mount /var/run/docker.sock
+
让 LLM 任意 docker exec
```

Docker socket 基本等价于高权限宿主控制面。

对于未知 GitHub Repository：

> 默认视为不可信代码。

---

# 18. P0 推荐 Reproduction 执行拓扑

最小但相对安全：

```text
Nexus Runtime
    │
    │ Reproduction Job
    ↓
Dedicated Repro Worker
    │
    ├── git clone
    ├── environment build
    ├── Container A
    └── Container B
```

比赛 Demo 可以让：

```text
Repro Worker
```

运行在：

- 专用开发机；
- 专用 VM；
- 独立 GPU server；

而不是生产 Backend 主机。

Runtime 和 Worker 之间只传：

```text
job spec
status
logs
artifacts
cancel
```

---

# 19. repo2docker 的定位

repo2docker 是：

```text
Environment Builder
```

不是：

```text
Research Agent
```

也不是：

```text
万能论文复现系统
```

正确关系：

```text
Repository
↓
Dockerfile?
├─ yes → normal Docker build
└─ no  → repo2docker candidate
```

如果 build 失败：

```text
Build Log
↓
Nexus Repair Reasoning
↓
Workspace Patch
↓
Rebuild
```

不要先让 LLM 猜一套 pip install。

---

# 20. 不允许使用 Host Local Shell 运行未知论文仓库

Deep Agents / Coding Agent 生态可能提供：

```text
Local Shell Backend
```

这对：

```text
开发者自己机器上的可信工程
```

可以很方便。

但 Quick Reproduction 输入的是：

```text
外部 GitHub Repository
```

默认不可信。

因此：

```text
未知 Repo
→ isolated sandbox/container
```

不能：

```text
unknown repo
→ nexus-runtime host subprocess
```

---

# 21. Development Container A 与 Verification Container B

P0 必须保留这个概念。

### A

允许：

```text
Agent edit
install
debug
repair
```

### B

用于：

```text
clean re-run
```

B 不允许 Agent 在运行失败后临时修改。

流程：

```text
A success
↓
freeze snapshot
↓
B fresh start
↓
same reproduce command
↓
metric
↓
verifier
```

否则：

```text
“Agent 在自己折腾了半天的环境里跑通”
```

不能充分证明 reproducibility。

---

# 22. Quick Reproduction 的 PASS 规则

最终状态至少区分：

```text
REPRODUCED
PARTIALLY_REPRODUCED
FAILED
INCONCLUSIVE
```

P0 最简单可以使用：

```text
expected metric
actual metric
tolerance
```

确定性比较。

例如：

```python
abs(actual - expected) <= tolerance
```

LLM 可以：

```text
解释结果
总结 blocker
生成报告文字
```

但不能自行决定：

```text
PASS
```

---

# 23. Artifact / Tool Result 不要全部塞进消息历史

例如：

```text
docker build log 40,000 行
pytest output 5 MB
paper full text
```

不能全部作为 ToolMessage 永久留在 Thread。

推荐：

```text
Large Result
↓
Artifact / Workspace file
↓
ToolMessage only keeps:
summary
path / artifact_id
key metadata
```

这样才能让 Context Compaction 真正有效。

Deep Agents 已经存在 large result / filesystem / summarization 相关机制。

优先使用框架现成能力。

---

# 24. “能直接用开源代码”与“复制源码”是两回事

优先级：

```text
1. 官方 package
2. 官方 SDK
3. CLI integration
4. HTTP / MCP / sidecar
5. plugin
6. thin adapter
7. fork
8. copy source
```

如果 Package API 已经满足：

> 不要把整个 GitHub 仓库复制进 CodeNexus。

如果确实要 fork：

```text
保留 upstream
记录原 commit
记录 license
尽量小 patch
```

---

# 25. 编码前必须执行 Dependency Spike

在真正修改 CodeNexus 主线前，先完成：

# Spike A：Deep Agents

目标：

```text
全新 Python 3.12 environment
↓
install deepagents stable
↓
install selected model provider
↓
create minimal agent
↓
one tool call
↓
two sequential tool calls
↓
stream
```

确认：

```text
resolved package versions
no dependency errors
model provider works
tool loop works
```

然后才把版本写进：

```text
services/nexus-runtime/pyproject.toml
uv.lock
```

---

# 26. Spike B：Checkpoint

验证：

```text
Thread
↓
Run
↓
process stop
↓
new process
↓
same thread_id
↓
resume / continue
```

没有完成这个实验：

> 不得在 README 写“支持崩溃恢复”。

---

# 27. Spike C：Paper Research

在独立环境：

```text
PaperQA candidate
↓
install minimal dependency
↓
paper search
↓
evidence query
↓
citation output
```

记录：

```text
install size
runtime dependency
provider
latency
error rate
API shape
```

再决定 library / service / replace。

---

# 28. Spike D：Sandbox

验证：

```text
sandbox start
file read
file edit
command
timeout
cancel
large stdout
path escape attempt
```

未知 repo 不能进入下一阶段，直到：

```text
path isolation
timeout
cancel
```

至少工作。

---

# 29. 编码智能体不得做的事情

除非用户之后明确批准架构迁移，否则禁止：

```text
❌ 升级 backend LangGraph 0.6 → 1.x
❌ 在 backend 直接安装 Deep Agents
❌ Nexus Runtime import backend Python modules
❌ 删除 Teaching / Prep Runtime
❌ 把 RE-KT 接入 Nexus
❌ 把 Judge0 变成 NexusLab
❌ 为 General/Research 复制两套完整 Runtime
❌ 用 prompt 代替 Tool 权限
❌ 用内存 checkpoint 宣称 crash recovery
❌ 未执行实验却生成成功 metric
❌ 在 Backend 主机本地 shell 执行未知论文 Repo
❌ 为了复用 PaperQA 安装所有 optional extras
❌ 在尚未做 compatibility spike 前锁死大量版本
```

---

# 30. 编码智能体可以自行决定的事情

允许根据实际代码和最新 upstream 自主决定：

```text
✓ nexus-runtime 的内部目录
✓ 使用 FastAPI / 其他轻量 service wrapper
✓ 具体 Deep Agents middleware
✓ 产品 Mode 如何映射到框架扩展点
✓ PaperQA 是 library 还是 sidecar
✓ Sandbox Backend 的具体实现
✓ Checkpoint PostgreSQL 的 schema/database 组织
✓ Internal Tool API 的 URL
✓ DTO 具体名称
✓ Artifact backend
```

前提是：

```text
不破坏本文硬边界
+
通过验收测试
+
减少自研基础设施
```

---

# 31. 建议的最小技术验收顺序

不要一开始同时接所有功能。

正确顺序：

```text
1. Dependency isolation
↓
2. Minimal Deep Agent
↓
3. Multi-tool loop
↓
4. Streaming
↓
5. Stable thread
↓
6. Persistent checkpoint
↓
7. General / Research mode gating
↓
8. Backend RAG Tool
↓
9. Artifact
↓
10. Paper Research
↓
11. Sandbox
↓
12. Quick Reproduction
↓
13. Clean Verification
```

如果：

```text
3. Multi-tool loop
```

还没有稳定通过，

不要开始：

```text
11. Sandbox
12. Quick Reproduction
```

否则错误层叠后很难定位。

---

# 32. 最小成功定义

Nexus Runtime 第一阶段真正成功的判据不是：

```text
项目成功启动
```

而是：

```text
用户发送一个任务

→ 同一个 thread 内模型调用 Tool A
→ Tool A 返回 Observation
→ 模型基于 Observation 调 Tool B
→ Tool B 返回
→ 模型给出最终回答

→ 整个过程 streaming 可见
→ thread 可以继续下一轮
→ Stop 真正取消本轮
```

第二阶段：

```text
进程重启后同一 thread 继续
```

第三阶段：

```text
切换 Research 后出现 Paper Research Tool
切回 General 后该 Tool 不再可调用
```

第四阶段：

```text
真实论文
→ 真实 Repo
→ 真实容器
→ 真实命令
→ 真实 Metric
→ Clean Verification
```

这四层依次成立以后，才可以认为 v1.2 描述的 Nexus 技术路线真正落地。

---

# 33. 给编码智能体的最终约束

如果本文与旧 Research Harness 的既有实现发生冲突：

```text
优先保持现有 Teaching / Prep 稳定
+
新建隔离 Nexus Runtime
```

不要为了“代码复用”把新旧 Runtime 强行揉在一起。

如果本文列出的某个开源项目在实际调研中：

```text
版本不兼容
已停止维护
有严重 Bug
License 不合适
部署成本不合理
```

允许替换。

真正不允许改变的是以下四条：

```text
1. Teaching 与 Nexus 的产品边界不能再次混淆
2. Nexus / Nexus Research 是同一产品 Session 的 Mode 切换
3. 新 Harness 不继续建立在旧 Research 单 Action Workflow 上
4. 通用基础能力优先成熟开源，自研只做薄的产品与领域 Glue
```

---

# 34. 已核验的上游技术来源

本补充中的版本与依赖事实核验自：

```text
Ouroboros-ga/ai-course-system
  backend/pyproject.toml
  branch: feature/xh202620

langchain-ai/deepagents
  libs/deepagents/pyproject.toml
  release: deepagents==0.7.12

langchain-ai/langchain
  libs/langchain_v1/pyproject.toml
  version: langchain 1.3.18

langchain-ai/langgraph
  libs/checkpoint-postgres/pyproject.toml

Future-House/paper-qa
  pyproject.toml
```

编码开始时再次检查这些 upstream 的当前 release，不要假定本文中的版本永远不变。
