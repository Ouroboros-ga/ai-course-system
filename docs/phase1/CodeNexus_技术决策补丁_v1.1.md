我先把文档和仓库实际状态对一遍——不然提的疑问会是空泛的。
我把文档逐节对照了仓库实况（`feature/xh202620` 分支、pyproject、research provider、compose 配置、GitHub API 查参考池），下面每条疑问都标了文档出处和实测到的代码事实。

**结论先行**：文档的产品判断是对的，工程前提是没验证的——三层结构（Teaching / Nexus General / Nexus Research）清晰，但"独立 Runtime + Deep Agents + 沙箱复现"这三条支柱各自压着一个未解决的硬约束，而 §19 参考池里有两个**无 License** 仓库。

---

## A. 产品转型方向的清晰度与可行性

**A1 [P0] 基准分支与现状严重脱节。** 文档头部声明基准 `feature/xh202620`，而当前 HEAD 是 `dev-liu`，两者差 **318 个文件 / +20724 −25398 行**。§18 要求"编码前应首先检查当前 `feature/xh202620` 实际代码"，却没说两个分支的合并策略。AI 编码智能体照此开工，会在一个落后两万行的分支上建新 Runtime。
→ 需明确：Nexus 从哪个分支切出？旧分支的 2.5 万行删除是什么（是已废弃还是未合并）？

**A2 [P0] course-scoped 与全局助手的定位冲突。** §3 把 Nexus 定位为 "ChatGPT / Codex" 通用助手，§5.2 又依赖"用户位于某门课程上下文时"这个前提。但现有 ResearchAgent 是**课程内**的：API 全是 `/api/v1/research-agent/courses/{course_id}/*`，权限走 `course.view` / `course.question.ask`，README 首段写"课程内、用户私有的科研工作台"。
→ Nexus 页面挂在路由树哪一层？全局入口下 Course RAG 的语境从哪来？无课程上下文时 Research Mode 是禁用、降级还是只走 Web？

**A3 [P0] "替换旧的 Agent 调度核心"的迁移成本被写成了一句话。** §8 原则是"保留领域能力，替换旧的 Agent 调度核心"。但现有 ResearchAgent 是一整套刚落地的东西：alembic 0053 五张表（`research_workspaces/todos/notes/scopes/memories`）、743 行 workspace provider、LangGraph StateGraph 九节点、4 个 API、前端四面板（Memory/Notepad/Scope/Todo），且 README §7 明写"**不引入第二套 Agent 平台**"。Phase 11 只给了 `Disable Entry → Observe → Remove Dead Code` 五步。
→ 缺一份迁移影响面清单：五张表是保留、迁移还是废弃？已有 workspace 数据怎么办？前端四面板是复用还是重建？

**A4 [P1] §8 的"可复用能力"清单有一半不存在。** §8 列举可复用 "Paper provider / Citation / Evidence / Research Workspace 数据"。但 README 第 19–21 行白纸黑字：*Semantic Scholar/OpenAlex/Crossref、多源证据综合、学术成文和完整 GitHub 仓库复现仍未接通，不得按已上线能力展示*。实际只有 `providers/research/paper_search.py`（232 行 `ArxivPaperSearchProvider`）是真实实现。
→ §8 清单要按"只有 arXiv 可用"的口径重写，否则编码智能体会以为 citation 层已经有了。

**A5 [P1] §5.1 "已经完成的 CS Knowledge Base" 缺判定依据。** Phase 3 说"让 Nexus 真正利用 CodeNexus **已经完成**的 CS KB"，但 `knowledge_data/` 只有 `algorithms.json` / `data_structures.json` / `relations.json` / `import_to_neo4j.py`，`providers/retrieval/` 只有 `active_bundle.py` 和 `demo.py`。且口径打架：pyproject pin `lancedb==0.34.0`，AGENTS.md 与 README 却说 pgvector + `<=>` 余弦。
→ 这个 KB 现在有多少条目、是否已向量化、Nexus 该调哪个 Port？"已完成"是谁判的？

**A6 [P1] §10 的验收样例与算力现实脱节。** 文档给的是"paper accuracy 91.4% vs 实际 90.8%"。而 Judge0 worker 限额是 **cpus 0.50 / mem 512M**，服务器有无 GPU 文档未提，§19 又把 dstack/SkyPilot 划到 P2、"P0 不要求多云调度"。
→ P0 的算力从哪来？建议把"选哪篇论文"前移为 P0 决策，并给出筛选标准（纯 CPU / 分钟级 / 数据集 < 1GB / 仓库自带 Dockerfile）。

**A7 [P2] §4.1 的 17 项能力清单没有优先级标注。** 其中 Subagent、Personal Context、Approval 都不在第四部分 P0 列表里（Personal Context 在 P1，Subagent 未出现）。编码智能体会照单全做。
→ 每项能力标 P0/P1/P2，并声明 §4 描述的是"最终形态"还是"P0 形态"。

---

## B. 复用 vs 自研的划分

**B1 [P0] 头号复用对象与现有依赖存在硬冲突风险。** §11 表把 Agent Harness 指向 Deep Agents。实测：`backend/pyproject.toml` pin `langgraph>=0.6,<0.7`，主依赖里**没有** langchain / langchain-core；而 deepagents 0.7.12 要求 `langchain-core>=1.6.1`、`langchain>=1.3.18`，还硬依赖 `langchain-anthropic>=1.7.0`。同一个 pyproject 依赖集大概率解不出来。
→ §9 画的"独立 Runtime"是**模块级隔离**，解不了依赖冲突。必须明确：是独立 venv、独立服务进程，还是干脆升级 langgraph？这条路不定，Phase 1 第一周就会卡住。

**B2 [P1] §9 的四条隔离理由只有一条是技术性的，且未验证。** 该条是"旧 LangGraph 版本阻碍升级"——但文档没论证**为什么不能升级**。现有 langgraph 0.6 只被 Teaching/Prep/Coding/Research 四个 Agent 用着，升级破坏面没测过。
→ 先跑一次 `langgraph 0.6 → 1.x` 的兼容性验证再写结论。没测过就别把它当成立项理由。

**B3 [P1] §16 自研清单漏了最大的两块工作量。** §16 说自研集中在 Adapter / Profile / Tool Registration / Verifier 这类"薄"代码。但真正的技术难点是 Phase 7 的 `Repro Plan → Build → Smoke → Repair` 循环和 Phase 8 的双环境 A/B freeze——文档把它们算作"薄 Reproduction Glue"（§Phase 7 开发原则第 5 条）。Repair 循环 + 环境快照 + deterministic verifier 是这个项目唯一有原创性的部分，不是 glue。
→ 建议把 Reproduction Orchestrator 显式列为一等自研模块单独估工，否则排期会严重低估。

**B4 [P1] §17 的六个新 Port 与现有 contracts 的关系没交代。** 文档列了 PaperResearchPort / EnvironmentBuilder / SandboxProvider / PersonalContextProvider / ComputeProvider / ArtifactProvider；仓库已有 `agents/contracts/`（含 `research_workspace.py`）和 `providers/research/`（workspace 743 行）。
→ 是平级新增还是重构现有？尤其 **Nexus 的 thread/checkpoint 存哪**——Phase 1 要 checkpoint/resume，而现有 README 明写"未配置 checkpointer，profile 不声明 checkpoint 能力"。

**B5 [P2] §8 与 §13 的复用优先级矛盾。** §8 说优先复用 Legacy 领域能力，§13 的优先顺序却把"已有项目能力"排在"官方/成熟社区项目"之后。两者冲突时听谁的？

---

## C. 架构与设计决策

**C1 [P0] 沙箱权限是全文档最大的空白。** §11 表 + Phase 7/8 需要 Docker / repo2docker 构建并运行实验环境。但 `deploy/judge0/docker-compose.yml` 文件头注释明确写着：*"本配置已移除 `privileged` 字段……不得通过环境变量……手动配置 `privileged: true`，并接受部署安全评审"*；主 `deploy/docker-compose.yml` 也没有挂载 `docker.sock`。
→ Nexus Sandbox 跑在哪、如何获得容器能力、是否走安全评审、与 Judge0 是否共用——文档零字。这是 Demo 能否成立的前提，也是安全问题，不是实现细节。

**C2 [P0] §21 "Nexus Runtime 不重新建立一套业务数据库" 与 Phase 1/7 的需求自相矛盾。** Phase 1 要 thread/checkpoint/resume，Phase 7 要产出 report.md/json/logs/environment info。对话状态、checkpoint、复现产物存哪？若全写回现有 backend，"独立 Runtime"的隔离边界在数据层就被打破了。
→ 需要一张存储归属表：哪些新建表、哪些复用、artifact 走 `object_key` 还是本地路径（AGENTS.md §4.1.7 要求媒体资产走 object_key 且发布不可变）。

**C3 [P1] Mode Switch 的作用域未定义。** §4 说切换改变 Prompt + Tools + Skills + Policy；Phase 2 验收只测"General 看不到 Research-only Tool"。
→ 会话中途切换会怎样？已产生的 Tool 结果和 context 怎么处置？Research 下生成的 Artifact 切回 General 后是否可见？mode 是 thread 级还是 message 级属性？

**C4 [P1] §5.2 的 RAG 融合策略无可验证判据。** 文档正确地拒绝了 `course_score *= N`（这点很好），但只给了原则。Phase 3 验收写"并由 Nexus 根据相关性决定最终使用哪些证据"——没有 golden set 就无法判定。
→ 补 10–20 条标注好的 query（课程强相关 / CS 强相关 / 需混合 / 都不相关）作为验收集。

**C5 [P1] Phase 8 的 freeze 粒度未定义。** 说"B 使用被冻结的 repository snapshot / environment / command / config"，但环境 freeze 是镜像 digest 还是 requirements pin？B 环境能否联网 pip？随机种子谁负责（论文仓库通常不设）？末句又说"不要为了追求完美可复现规范拖死 Demo"。
→ 给出最低可接受的 freeze 定义 + 明确的降级标记（例如 `reproducible=true` 但 `seed_controlled=false`）。

**C6 [P2] Teaching 与 Nexus 的共享面只有一句话。** §1 说"可以共享现有课程、知识库、用户权限等业务基础设施"。
→ 具体到 Course Access v1 的能力项，Nexus 用哪些？Course Access 是 course-scoped，Nexus 在课程外运行时权限模型是什么？

---

## D. 开源引入的版权 / 许可 / 维护 / 选型

**D1 [P0] 参考池里有两个无 License 仓库，而这是文档唯一没有兜底的一处。** 实测（2026-09-02 GitHub API）：

| 项目                           | Stars | License    | 最近 push  |
| ------------------------------ | ----- | ---------- | ---------- |
| `Future-House/paper-qa`        | 9142  | Apache-2.0 | 2026-08-26 |
| `langchain-ai/deepagents`      | 28842 | MIT        | 2026-09-02 |
| `AI9Stars/AutoReproduce`       | 45    | **无**     | 2026-04-10 |
| `1a1a11a/2026_paper_reproduce` | **0** | **无**     | 2026-07-22 |
| `mtilyxuegao/PaperPilot`       | 16    | Apache-2.0 | 2026-07-07 |

无 License = 默认 all rights reserved，参考其代码不具备明确授权。§19 对这一类只写了"注意：参考设计前必须再次检查当前 License 和成熟度"——这是全篇最危险的一行：它给了许可去参考，却没给兜底规则。
→ 建议直接把无 License 的仓库剔出参考池，或限定为"只读公开 README 层面的思路，不读源码、不复制结构"。

**D2 [P1] paper-qa 的接入前提完全没验证。** paper-qa 2026.8.12 依赖 `fhaviary[llm]`、`fhlmi`（FutureHouse 自家 LLM 抽象层）、`tantivy`（Rust 全文索引，需二进制轮子）、`pydantic~=2.0`；而本项目 `config.py:59` 默认 `LLM_PROVIDER="doubao"`，走 OpenAI 兼容端点。
→ paper-qa 的 LLM 层能否接 doubao？要不要 LiteLLM 中转？tantivy 在 Windows 开发机（win32）和 Linux 服务器上轮子是否可用？pydantic 约束与 sqlmodel 是否冲突？**在跑一次 dependency dry-run 之前，Phase 5 的"优先直接作为 library 使用"是一句没验证的话。**

**D3 [P1] deepagents 的迭代速度与 §15 的 Pin 策略打架。** 28842 stars、MIT、今天还在 push，但版本是 0.7.12——pre-1.0 高频迭代，"经过验证的最新稳定版本"（§15）在这种项目上不存在。
→ pin 之后遇到 upstream breaking change：跟还是不跟？adapter 隔离还是长期 fork？文档 §14 把"长期 Fork"列为最后手段，但没说 pre-1.0 项目该怎么处理。

**D4 [P1] 模型能力前提缺失。** deepagents 的 middleware（Todo / Filesystem / Subagent / Compaction）重度依赖模型 tool-calling 质量，而默认模型是 doubao。
→ 建议在 Phase 1 前加一个 model capability probe：验证 doubao 在连续 tool loop、长 context、并行工具调用上的成功率。否则 Phase 1 验收"连续两次以上 Tool Call 真实成功"可能卡在模型而不是架构，却会被误判为架构问题。

**D5 [P2] OpenHands / opencode 的定位模糊。** 这两者是完整产品级应用（自带 server、runtime、UI），不是可嵌入的 library，但 §19 把它们和 library 放在同一池，用途写"Coding UX / Sandbox"。
→ 若只是参考交互，请明确标注"仅参考 UX 设计，不作为依赖"，否则编码智能体可能把整个 OpenHands 拖进来。

**D6 [P2] §11 表"复用成熟 Coding Agent / Sandbox 能力"——仓库已有 `agents/coding/`（CodingEduAgent + Judge0）。** 是复用它还是另起一套？文档没说。

---

## 值得保住的部分（修订时别删）

§5.2 拒绝 `course_score *= N` 的写死权重、§10 "最终 PASS/FAIL 不交给 LLM 主观判断"、Phase 9 明令"禁止静默成功 / 编造实验结果 / 没执行却写 PASS"、§18 拒绝文件级施工图、§14 的复用前检查清单、§15 的三阶段版本策略——这六条比文档里的任何架构图都值钱，是这份方案真正的水准所在。

**如果只补三件事**：① 把 deepagents × langgraph 0.6 的依赖冲突跑出结果（决定"独立 Runtime"到底是独立进程还是独立 venv）；② 定下沙箱的授权路径与安全评审边界（决定 Quick Reproduction 能否做）；③ 剔除参考池里的无 License 仓库。



# CodeNexus 技术决策补丁 v1.1

> 适用范围：补充并覆盖《CodeNexus 转型设计与实施方案 v1.2》及《Nexus Runtime 技术补充说明 v1.0》中存在歧义的工程部分。  
> 目标读者：AI 编码智能体 / 后端开发者。  
> 本文只记录已经做出的技术决策、实施前必须通过的 Gate，以及不能越过的工程边界。

---

# 1. 开发基线：不再把 `feature/xh202620` 写死为施工分支

## 决策

Nexus 开发必须从**当前实际集成主线**切出，而不是根据旧设计文档固定使用 `feature/xh202620`。

当前开发工作按用户确认的实际工作线：

```text
dev-liu
```

作为施工基线。

`feature/xh202620` 仅作为：

```text
历史实现参考
旧 Research Harness 参考
赛题阶段代码参考
```

不再作为 AI 编码智能体默认修改目标。

## 开工前必须生成 Baseline Report

编码智能体在真正修改代码前必须执行：

```text
git status
git branch --show-current
git rev-parse HEAD
git merge-base <current> feature/xh202620
git diff --stat <merge-base>..<current>
```

并记录：

```text
active branch
HEAD SHA
feature/xh202620 SHA
merge base
关键目录差异
数据库 migration 差异
Agent 目录差异
deploy 差异
```

如果远端与本地状态不同：

> 以用户当前实际开发工作区为准，不自行 reset / merge / rebase。

---

# 2. Nexus 是全局助手，Course Context 是可选绑定

现有 ResearchAgent 是 course-scoped，不代表新的 Nexus 也必须 course-scoped。

## 产品模型

```text
Nexus Session
│
├── active_course_id = null
│   ├── CS Knowledge
│   ├── Web
│   ├── Artifact
│   └── Research Tools
│
└── active_course_id = <course>
    ├── Course RAG
    ├── CS Knowledge
    ├── Web
    ├── Artifact
    └── Research Tools
```

因此：

```text
Nexus Research
```

在没有课程上下文时仍然可以使用。

不会因为：

```text
active_course_id = null
```

而整体禁用 Research Mode。

## Course RAG Tool Gate

只有：

```text
active_course_id != null
+
用户拥有 course.view / 对应权限
```

时，Course Retrieval Tool 才可用。

无课程：

```text
Course Tool = unavailable
```

而不是给 Tool 传空 course_id。

## Course Context 来源

允许：

- 从课程页面进入 Nexus 时显式带入；
- 用户在 Nexus 中手动选择课程；
- 后续显式切换课程。

不建议仅根据历史消息暗中猜测 course_id。

---

# 3. Legacy Research 的迁移策略：P0 不迁数据库

现有 ResearchAgent 已经拥有自己的 Workspace/Todo/Note/Scope/Memory 数据。

## P0 决策

以下 Legacy 数据：

```text
research_workspaces
research_todos
research_notes
research_scopes
research_memories
```

全部：

```text
保留
不删除
不迁移
不改表语义
```

它们继续属于：

```text
Legacy Research Workspace
```

新的 Nexus 不以这些表作为：

```text
Thread
Checkpoint
Personal Memory
Todo
```

的持久化基础。

## 原前端四面板

现有：

```text
Memory
Notepad
Scope
Todo
```

P0 不要求搬进 Nexus。

保留 Legacy UI。

新 Nexus 的 Todo / Context / Workspace UI 按新的 Runtime 能力实现。

如果未来确实需要导入旧 Research Workspace：

```text
Legacy Export / Adapter
↓
Nexus Workspace
```

另做迁移。

不要在 P0 做数据库重构。

---

# 4. 现有 Research 能力的真实口径

编码智能体不得根据旧设计文档假定以下能力已经上线：

```text
Semantic Scholar
OpenAlex
Crossref
多源论文 Evidence Synthesis
完整 Academic Writing Pipeline
完整 GitHub Paper Reproduction
```

当前可确认的旧 Research 真实线上能力，应以实际代码 Spike 为准。

在已有审查中确认的真实论文检索实现主要是：

```text
ArxivPaperSearchProvider
```

因此 Legacy Research 的复用口径改为：

```text
Confirmed:
- arXiv search provider
- existing workspace data / CRUD
- existing access control and audit patterns

Must rediscover before reuse:
- citation
- evidence
- writing
- trend
- external paper providers
```

任何“看文档像存在”的能力都必须经过：

```text
code path
+
runtime smoke
```

后才能列为可复用能力。

---

# 5. CS Knowledge Base：产品上视为已完成，工程上必须重新发现真实 Retrieval Contract

产品范围不重新讨论 CS Knowledge Base 是否应该存在。

但 Nexus 集成前必须解决：

```text
到底哪个 Retrieval Port / Provider 是生产路径
```

因为仓库中可能同时存在：

```text
LanceDB
pgvector 描述
demo retrieval
graph / JSON source
```

## Phase 3 前置 Gate

编码智能体必须实际完成：

```text
query("binary search")
↓
real production retrieval path
↓
structured results
↓
source / citation metadata
```

并记录：

```text
active provider
index location
embedding model
vector dimension
retrieval API
course scope behavior
CS scope behavior
```

Nexus 只调用已经实测工作的 Retrieval Contract。

不根据 README / AGENTS / pyproject 的单一描述自行猜测。

---

# 6. Deep Agents 与旧 LangGraph：不是“不能升级”，而是 P0 明确选择不升级

当前旧 Backend：

```text
langgraph >=0.6,<0.7
```

当前 Deep Agents 生态要求 LangChain 1.x，并间接要求 LangGraph 1.x。

这说明：

```text
Deep Agents
```

不能直接加入现有 Backend dependency environment。

但本文不再声称：

> LangGraph 0.6 → 1.x 技术上绝对无法升级。

正确结论是：

> **比赛 P0 不承担升级现有四类 Agent 的迁移风险，因此主动选择 Runtime 隔离。**

以后如果有必要，可以单独建立：

```text
Legacy LangGraph Upgrade Spike
```

但它不是 Nexus P0 前置条件。

---

# 7. “独立 Runtime”的严格定义

独立 Runtime 不是：

```text
backend/app/nexus/
```

这种模块级分目录。

必须至少满足：

```text
独立 Python environment
独立 pyproject
独立 lockfile
独立 process
```

推荐进一步：

```text
独立 container
```

因此：

```text
Backend
  Python Env A
  LangGraph 0.6

Nexus Runtime
  Python Env B
  Deep Agents
  LangChain 1.x
  LangGraph 1.x
```

两者不直接 Python import。

通信使用：

```text
HTTP / SSE / JSON
```

或经过明确验证的其他 IPC。

---

# 8. Deep Agents 版本策略

Deep Agents 当前仍处于 pre-1.0 快速迭代阶段。

## 禁止

```text
follow main
每次部署自动升级最新版
不锁版本
直接复制 upstream 源码
```

## 推荐

开发 Spike：

```text
检查最新 release
↓
阅读 release notes
↓
选择候选版本
↓
兼容性测试
```

集成后：

```text
pin exact version
+
commit uv.lock
+
建立 Harness Contract Tests
```

例如：

```text
Tool loop
Streaming
Checkpoint
Interrupt
Subagent
Filesystem
Compaction
```

都要有最小契约测试。

升级规则：

```text
有明确收益 / blocker fix
↓
单独 upgrade branch
↓
contract tests
↓
merge
```

不长期 fork。

只有 upstream 扩展点确实无法满足核心能力时，才重新评估 fork。

---

# 9. Model Capability Probe 必须在 Harness 实现之前完成

当前主系统模型配置倾向 Doubao/OpenAI-compatible，并不能因此假定：

```text
Deep Agents + 当前模型 = 可用
```

Agent Harness 的效果高度依赖模型 Tool Calling 能力。

## Phase 0 Model Probe

使用最终计划接入 Nexus 的真实模型，测试至少：

### T1 单 Tool

```text
成功选择正确 Tool
参数 schema 合法
```

### T2 连续 Tool Loop

```text
Tool A
→ Observation
→ Tool B
→ Final
```

### T3 Tool Failure Recovery

Tool A 返回明确 failure 后：

```text
重试 / 换策略 / 正确报告失败
```

### T4 Long Context

加入较长上下文后仍能：

```text
保持 Goal
正确调用 Tool
```

### T5 Structured Output

Pydantic / JSON 输出稳定。

## P0 建议门槛

至少：

```text
单 Tool 成功率 >= 95%
连续 2-step Tool Loop >= 90%
Tool 参数 schema 有效率 >= 95%
```

并行 Tool Call 不作为 P0 硬要求。

如果 Doubao 无法达到：

> Nexus Runtime 允许使用独立于 Teaching Agent 的模型 Provider。

不要为了“全系统统一模型”牺牲 Harness 可用性。

---

# 10. 自研工作重新分级：Reproduction Orchestrator 是一等模块

此前把论文复现中的业务逻辑统称为：

```text
thin glue
```

不准确。

真正需要 CodeNexus 自己负责的核心之一是：

# Reproduction Orchestrator

它至少管理：

```text
PLAN
↓
BUILD
↓
SMOKE
↓
REPAIR
↓
EXECUTE
↓
FREEZE
↓
VERIFY
↓
REPORT
```

以及：

```text
retry budget
repair budget
cancel
timeout
artifacts
failure classification
state transition
```

它不是 Agent Framework，但也不是几行 Adapter。

## 正确边界

成熟开源负责：

```text
Agent Harness
Shell / Sandbox primitives
Environment Builder primitives
Paper Search
Container runtime
```

CodeNexus 自研负责：

```text
Reproduction state machine
Claim / Metric contract
Repair policy
Freeze policy
Verification policy
ReproReport
```

这是 Nexus Research 的核心产品逻辑。

不要再按“700 行胶水一定能完成”做排期。

先 Spike，再估工。

---

# 11. 新 Contracts 与旧 `agents/contracts` 的关系

P0 不要求重构旧 Agent Contracts。

新的 Nexus Runtime 可以拥有自己的：

```text
runtime-local interfaces / protocols
```

例如概念上：

```text
KnowledgeToolClient
PaperResearchProvider
SandboxProvider
EnvironmentBuilder
ArtifactClient
```

Backend 侧只暴露稳定 HTTP Contract。

不要为了“统一 Port”：

```text
大规模搬迁旧 agents/contracts
```

后续稳定后再决定是否抽取：

```text
shared contracts package
```

---

# 12. 复用优先级冲突的统一规则

以后不使用一个笼统的“开源优先级”。

区分两类能力。

## 已经真实生产可用的领域能力

例如：

```text
Course RAG
CS RAG
Auth
Course Access
已有 Artifact
```

优先：

```text
Reuse Existing
```

不要为了“GitHub 有更成熟的”重新替换。

## 新增的通用基础设施

例如：

```text
Agent Harness
Context Compaction
Checkpoint
Generic Sandbox
Paper Research
Environment Builder
```

优先：

```text
Mature Upstream
↓
Thin Adapter
```

所以原则是：

> **领域真相优先保留现有；通用基础设施优先成熟开源。**

---

# 13. Sandbox：P0 不复用 Judge0

Judge0 当前属于：

```text
Teaching Agent
学生题目级执行
```

并已有严格的：

```text
CPU
Memory
Network
Linux capability
non-privileged
```

安全约束。

Quick Reproduction 的需求却是：

```text
clone repository
install dependencies
build container
edit files
run arbitrary project commands
```

两者安全模型完全不同。

因此 P0：

```text
Judge0
≠
NexusLab Reproduction Sandbox
```

不要修改 Judge0 为了兼容论文复现。

---

# 14. Reproduction Sandbox 的正式拓扑

P0 推荐：

```text
Nexus Runtime
      │
      │ authenticated job API
      ↓
Dedicated Repro Worker
      │
      ├── Repository Workspace
      ├── Docker / Container Engine
      ├── Build
      ├── Container A
      └── Container B
```

## Repro Worker 运行位置

优先：

```text
专用 Linux VM / 专用服务器
```

可以是比赛部署中的单独节点。

它不应运行在：

```text
主 Backend 业务容器
Judge0 worker
```

中。

## Docker 权限

如果 Repro Worker 使用 Docker socket：

```text
docker.sock
```

只能暴露给：

```text
受信任 Repro Worker control plane
```

不能直接暴露给：

```text
LLM Tool
Nexus Runtime
外部请求
论文容器
```

模型只能调用高层受控操作：

```text
build
start
exec
stop
snapshot
collect_artifact
```

而不是任意 Docker API。

正式部署前必须经过安全评审。

---

# 15. P0 算力决策：先选论文，再实现复现链

论文选择是 P0 技术 Gate，不是最后 Demo 时再找。

## 第一版演示目标

优先：

```text
CPU
或已有明确可用单 GPU
```

为了降低风险，默认筛选标准：

```text
官方开源 Repo
明确 License
单机
CPU 可跑优先
总运行 <= 5 分钟
数据 <= 1 GB
有 pretrained artifact / quick eval / demo
结果机器可解析
依赖可公开下载
```

如果最终选择 GPU 论文：

必须在开发 Phase 0 就确认：

```text
GPU host
driver
CUDA
available VRAM
network
worker access
```

不能等 Quick Reproduction 写完以后再发现没有算力。

---

# 16. Nexus Runtime 可以有“运行数据库”，但不能复制业务数据库

v1.2 中：

```text
Nexus Runtime 不重新建立业务数据库
```

指的是：

```text
不要复制 User / Course / Knowledge / Teaching 数据
```

不代表 Runtime 完全无持久化。

## 存储归属

| 数据 | 归属 |
|---|---|
| User / Auth / Course | Existing Backend DB |
| CS / Course Knowledge | Existing Knowledge Layer |
| Learner Model / RE-KT | Teaching Domain |
| Legacy Research Workspace | Existing Backend DB，原样保留 |
| Nexus Product Session metadata | Existing Backend 或明确的 Nexus metadata store |
| LangGraph Thread / Checkpoint | Nexus Runtime operational DB |
| Personal Context | 独立 Personal Context Provider，P1 |
| Artifact metadata | Existing Artifact / Storage domain 优先 |
| Artifact binary/file | Object Storage，通过 `object_key` |
| Repro Worker temporary workspace | Worker ephemeral disk |
| Build / experiment logs | Artifact storage + run metadata |
| Docker image | Repro Worker / Registry |
| Reproduction Report | Artifact storage |

关键区别：

```text
Business DB
≠
Runtime Operational Store
```

---

# 17. Nexus Checkpoint 存储

如果需要：

```text
process restart → resume
```

就必须使用持久化 Checkpointer。

推荐优先评估：

```text
LangGraph Postgres Checkpointer
```

但它属于：

```text
Nexus Runtime dependency environment
```

不是旧 Backend 的：

```text
psycopg2 connection/session
```

Nexus Runtime 可以连接：

- 同一个 PostgreSQL 实例下独立 database/schema；
- 或独立 PostgreSQL。

P0 更重要的是：

```text
权限隔离
migration 可控
crash/resume 实测通过
```

不是必须物理独立数据库服务器。

---

# 18. Mode Switch 的精确定义

产品：

```text
Nexus
⇄
Nexus Research
```

共享同一 Product Session。

## Mode 属性

推荐：

```text
mode = per-run input
```

即每次用户发起新 Run 时确定：

```text
general
research
```

同一个 Thread 可以跨 Run 切换 mode。

## 切换规则

Run 执行中：

```text
mode locked
```

不允许执行到一半切换 Tool Set。

Run 完成后：

```text
下一条消息可以切换
```

如果 Run 正处于：

```text
approval interrupt
```

先 resolve / cancel 当前 Run，再切 mode。

## 历史 Context

Research Mode 产生的：

```text
messages
citations
artifacts
```

切回 General 后仍然可见。

但：

```text
Research-only Tool
```

在新的 General Run 中不可调用。

也就是说：

```text
历史可见
能力受当前 mode 控制
```

---

# 19. RAG 融合必须有 Golden Set

Phase 3 不再用：

> “看起来检索得不错”

作为验收。

准备最少：

```text
10–20 条人工标注 query
```

覆盖：

```text
Course 强相关
CS KB 强相关
Course + CS 混合
需要 Web
Course 明显无关
内部知识均无答案
```

每条标注：

```text
expected source class
must-have evidence
forbidden irrelevant source
```

验收至少观察：

```text
Recall
Source Selection
Citation Correctness
Course Leakage
```

P0 不必建立大型 benchmark，但必须有可重复 Golden Set。

---

# 20. Freeze 的 P0 最低定义

Quick Reproduction 的 Verification B 至少冻结：

```text
repository base commit SHA
final patch / snapshot hash
container image digest
exact command
config hash
dataset identifier / checksum（可得时）
Python version
package snapshot
OS
CUDA / GPU info（如有）
```

并记录：

```text
seed_controlled: true/false
network_isolated: true/false
environment_rebuildable: true/false
```

## P0 Reproducibility Level

建议区分：

### L1 Execution Repeatability

```text
冻结后的 image + repo snapshot
在新 Container B 中可重新运行
```

这是 P0 必须做到的。

### L2 Environment Rebuildability

```text
从 Dockerfile / lock / source
重新 build 环境
再运行
```

P0 非强制。

所以比赛报告不要把：

```text
docker commit 后第二次跑通
```

夸张描述成“完全可复现”。

可以描述：

> 已通过隔离环境中的重复执行验证。

---

# 21. Paper Research：PaperQA 默认先作为 Sidecar 候选

PaperQA 是有价值的成熟候选，但它拥有自己的：

```text
LLM abstraction
index/search dependencies
tantivy
optional parser / local / qdrant / office extras
```

因此默认实施顺序改为：

```text
Independent PaperQA Spike
↓
验证真实 Doubao / OpenAI-compatible Provider
↓
验证 Windows dev / Linux deploy
↓
验证 dependency tree
↓
验证 query + citation
```

## 默认倾向

如果 PaperQA 依赖树较重：

```text
Nexus Runtime
↓ HTTP
Paper Research Sidecar
↓
PaperQA
```

而不是强行装进 Nexus Runtime。

如果 Spike 证明 library integration 非常干净，再使用 Adapter 直接依赖。

---

# 22. PaperQA 模型兼容性必须真实验证

不能假定：

```text
OpenAI-compatible endpoint
=
PaperQA 一定支持 Doubao
```

必须跑真实：

```text
search
query
evidence
citation
```

如果需要大量修改 FutureHouse 的内部 LLM abstraction：

> 不要为了 PaperQA 硬改它。

可以：

- 使用它支持良好的模型作为 Research 专用 Provider；
- 换其他成熟 Paper Research 项目；
- 使用 Sidecar 做 provider isolation。

---

# 23. 开源 License 红线

以下规则对编码智能体是硬约束。

## 可以作为依赖 / 源码参考

必须有明确 License，并满足项目使用条件。

当前主要候选：

```text
Deep Agents → MIT
PaperQA → Apache-2.0
repo2docker → BSD-3-Clause
PaperPilot → Apache-2.0（使用前再次核验）
```

## 无 License 仓库

例如当前审查发现：

```text
AI9Stars/AutoReproduce
1a1a11a/2026_paper_reproduce
```

没有明确开源 License。

处理：

```text
禁止复制源码
禁止移植函数
禁止复制目录结构作为实现蓝本
禁止加入 vendor
禁止作为 package dependency
```

允许：

```text
阅读公开论文
阅读 README 中的高层产品概念
引用其公开描述做背景调研
```

实现必须独立完成，或来自有明确 License 的其他项目。

因此这两个项目从：

```text
Implementation Reference Pool
```

中移除。

---

# 24. OpenCode / OpenHands 的定位

## OpenCode

```text
UX / Agent product behavior reference only
```

重点：

- Session；
- Tool progress；
- Permission；
- Stop；
- Workspace；
- coding interaction。

P0 不作为依赖。

## OpenHands

```text
Sandbox / Runtime architecture reference
```

P0 默认也不作为 dependency。

只有 Repro Worker Spike 证明：

```text
直接使用 OpenHands Runtime
```

能显著减少代码且不会引入巨大平台依赖时，才重新评估。

不能因为它在“参考池”就整个集成。

---

# 25. Existing Coding Agent 的边界

现有：

```text
agents/coding
Judge0
CodingEduAgent
```

继续属于：

```text
Teaching / Student Practice
```

Quick Reproduction 不复用它作为 Repo-level Coding Agent。

原因：

```text
题目级执行模型
≠
仓库级 Research Workspace
```

未来如果 Nexus General 要增加真正的 Coding Agent：

> 单独立项。

不要借论文复现阶段顺便改造 Teaching Coding Agent。

---

# 26. P0 能力优先级重新标记

## P0

```text
Nexus Runtime isolation
Model Capability Probe
Deep Agent multi-tool loop
Streaming
Session / Thread
Cancel
Persistent Checkpoint
General / Research Mode
CS RAG
Course RAG
Web
Artifact
Paper Research
Repro Worker
Quick Reproduction
Clean Verification L1
Deterministic Verifier
```

## P1

```text
Personal Context
更完整 Todo UI
更完整 Subagent 策略
Research Workspace UI
更多 Artifact 格式
更强 Sandbox
环境 L2 rebuild
```

## P2

```text
dstack
SkyPilot
多云 GPU
学校 Slurm
完整 Paper Lineage
多 Claim 自动验证
长期训练
通用 Repo Coding Agent
```

Deep Agents 内部可能已经包含 Todo/Subagent 等能力，但：

> “框架存在”不等于 P0 必须把它们产品化。

---

# 27. Quick Reproduction 开发顺序重新调整

论文复现不直接从“写 Orchestrator”开始。

## Gate R0：选定 Demo Target

必须先确定：

```text
真实 Paper
真实 Repo
真实 License
真实 Compute
真实 quick command
真实 metric
```

## Gate R1：手工复现

不使用 Agent，开发者先手动完成：

```text
clone
build
run
metric
```

如果人工都无法在目标环境 5 分钟内稳定完成：

> 不进入自动化。

## Gate R2：Environment Automation

自动：

```text
clone
build
sandbox
run
```

不加 Agent Repair。

## Gate R3：Agent Repair

在确定性流程失败时再引入：

```text
Deep Agent
```

## Gate R4：Clean Verification

A 成功后进入 B。

## Gate R5：Report

最后生成 Artifact。

这个顺序比“一开始让 Agent 自动解决所有环境问题”可靠得多。

---

# 28. Phase 0 必须先完成的五个 Spike

正式开发前按顺序完成：

## Spike 1：Branch Baseline

确认当前开发基线和 Legacy 差异。

## Spike 2：Model + Deep Agents

```text
Doubao/目标模型
+
Deep Agents
+
2-step Tool Loop
```

## Spike 3：Persistent Checkpoint

```text
process kill
↓
restart
↓
same thread resume
```

## Spike 4：Paper Research

```text
PaperQA/候选项目
+
真实 provider
+
真实 citation
```

## Spike 5：Repro Worker

```text
isolated Linux worker
+
container build
+
timeout
+
cancel
+
artifact collection
```

只有五个 Spike 都有明确结论后：

> 才进入完整功能编码。

---

# 29. 最终安全边界

任何时候：

```text
未知 GitHub Repo
```

都视为：

```text
Untrusted Code
```

禁止：

```text
在 Backend host shell 运行
在 Nexus Runtime host shell 运行
继承生产 secrets
挂载业务数据库凭证
挂载用户主目录
挂载生产 object storage credentials
直接获得 Docker control API
```

Repro Worker 提供：

```text
临时 workspace
受限网络
资源 quota
timeout
cancel
artifact whitelist
```

详细 hardening 可以 P1 增强，但这些底线 P0 就要存在。

---

# 30. 本补丁后的最终工程哲学

不是：

> 旧代码全部推翻。

也不是：

> GitHub 项目越多越好。

而是：

```text
已经真实稳定的领域能力
        ↓
        保留

缺失的通用基础设施
        ↓
选择成熟、明确 License 的开源项目

CodeNexus 独有产品逻辑
        ↓
自己实现
```

其中当前真正值得 CodeNexus 自己承担的一等逻辑是：

```text
Nexus Mode / Capability Mapping
Domain Context Mapping
RAG / Citation Integration
Reproduction Orchestrator
Deterministic Verification
Product UX
```

而不应该自研：

```text
Generic Agent Runtime
Generic Context Compressor
Generic Checkpointer
Generic Scientific Search Engine
Generic Container Engine
```

---

# 31. 对后续 AI 编码智能体的执行指令

开始任何 Phase 前：

```text
Inspect actual current code
↓
Inspect current upstream release
↓
Run smallest possible Spike
↓
Record factual result
↓
Choose integration strategy
↓
Implement
↓
Contract test
```

遇到本文与实际仓库不一致：

> 不猜。

先输出：

```text
Observed Fact
Conflict
Options
Recommended Decision
```

再继续。

最重要的是：

> **不要把架构文档中“候选能力存在”误读成“代码已经存在”，也不要把“某个开源项目值得参考”误读成“必须把它集成进来”。**
