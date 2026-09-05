# CodeNexus 转型设计与实施方案 v1.2

> 基准分支：`feature/xh202620`\
> 文档用途：冻结 CodeNexus 当前转型范围，并作为后续 AI 编码智能体的开发上下文与实施计划。\
> 本文不要求后续实现机械照抄某个目录或某个开源项目；优先保证产品边界、能力目标、稳定性和验收结果。

***

# 第一部分：产品与功能设计

# 1. CodeNexus 当前产品结构

CodeNexus 由原有教学系统继续演进。

现有教学能力继续由 **Teaching Agent** 承担；新增的 **Nexus AI** 则作为一个类似 ChatGPT / Codex 的通用智能体助手存在，并通过界面按钮切换为研究增强模式。

整体关系：

```text
CodeNexus
│
├── Teaching Agent
│   ├── 课程学习与答疑
│   ├── 个性化教学
│   ├── 练习 / 做题
│   ├── Judge0 / 代码测评
│   ├── Learning Evidence
│   └── RE-KT / Learner Model
│
└── Nexus AI
    │
    ├── General Mode
    │
    └── Research Mode
        ├── Paper Search / Paper Research
        └── NexusLab / Quick Reproduction
```

Teaching Agent 与 Nexus AI 可以共享现有课程、知识库、用户权限等业务基础设施，但不应再次混合它们的职责。

***

# 2. Teaching Agent

Teaching Agent 继续负责学生学习相关能力。

包括：

- 课程问答；

- 教师课程资料；

- 学习过程；

- 练习与题目；

- 学生代码测评；

- Judge0；

- Learning Event；

- Learning Evidence；

- RE-KT；

- Learner Model；

- Cognitive Projection；

- 基于学习状态选择教学策略。

因此：

```text
RE-KT
Learner Model
学生练习状态
学生代码测评
```

全部属于 Teaching Agent。

这些能力不作为 Nexus AI Harness 的一部分。

***

# 3. Nexus AI

Nexus AI 是 CodeNexus 新增的通用智能体助手。

产品形态更接近：

- ChatGPT；

- Codex；

- OpenCode；

- 具有 Tools / Context / Workspace 的通用 Agent。

用户进入的是同一个 Nexus AI 页面。

界面上可以提供：

```text
[Nexus]   [Nexus Research]
```

或者等价的模式切换按钮。

这里不是两个独立产品，也不是两套 Agent Runtime。

***

# 4. Nexus 与 Nexus Research 的切换

底层始终是同一个 Nexus Harness。

```text
                    Nexus AI
                       │
                  Mode Switch
                       │
            ┌──────────┴──────────┐
            │                     │
         General               Research
            │                     │
       General Profile       Research Profile
```

切换 Research 后，核心变化主要是：

```text
System / Profile Prompt
        +
Available Tools
        +
Skills
        +
Research Policy
```

Prompt 可以只有轻微差异。

真正明显的区别来自 Research Mode 新增的能力。

***

## 4.1 Nexus General

主要能力：

- 通用多轮对话；

- 复杂任务拆解；

- Tool Loop；

- 必要时 Plan / Todo；

- Context Management；

- Computer Science Knowledge RAG；

- Course RAG；

- Web Search；

- Personal Context；

- 文件型 Workspace；

- Markdown；

- LaTeX；

- DOCX；

- 其他 Artifact；

- Interrupt / Resume；

- Cancel；

- Approval；

- 必要时 Subagent。

***

## 4.2 Nexus Research

Research Mode 保留 General Mode 的全部基础能力，并增加：

- Paper Search；

- Paper Research；

- 学术来源与 Citation；

- Research Skills；

- Research Workspace；

- NexusLab；

- Quick Reproduction；

- 实验日志；

- 复现报告；

- 后续可扩展科研 Compute。

因此它可以理解为：

> **同一个 Nexus AI，在 Research Mode 下开放更多科研工具。**

***

# 5. Nexus RAG 范围

Nexus 可以访问两个主要内部知识来源。

## 5.1 Computer Science Knowledge Base

作为通用计算机学科知识源。

主要覆盖：

- 编程语言；

- 数据结构；

- 算法；

- 操作系统；

- 数据库；

- 计算机网络；

- 软件工程；

- 人工智能；

- 其他 CS 学科内容。

***

## 5.2 Course Knowledge

课程知识来自：

- 教师上传课件；

- PPT；

- 教材；

- 文档；

- 课程解析结果；

- Course Evidence。

用户位于某门课程上下文时，课程资料具有更高的语境优先级。

推荐逻辑：

```text
Query
  ↓
Course Retrieval
  +
CS Retrieval
  ↓
Normalize / Merge / Rerank
  ↓
Relevant Context
```

不是简单写死：

```text
course_score *= N
```

课程材料不相关时不能为了“优先课程”强行进入最终 Context。

***

# 6. Paper Research

Paper Research 属于 Nexus Research 的高级科研能力。

它与 Quick Reproduction 是两个不同层次：

```text
Paper Research
    ↓
找论文 / 读论文 / 收集证据 / 比较论文 / 回答研究问题

Quick Reproduction
    ↓
针对一篇论文与代码仓库真正构建环境并运行实验
```

Paper Research 不需要从零实现。

当前可以优先评估成熟开源科学文献工具，例如：

### Future-House / paper-qa

公开定位：

> High accuracy RAG for answering questions from scientific documents with citations.

其当前版本已经提供：

- Paper Search；

- Candidate Paper Retrieval；

- Evidence Gathering；

- Scientific RAG；

- Agentic Search；

- Citation；

- 多轮工具调用；

- OpenAlex 等 metadata provider；

- 科研问题回答。

因此它非常适合作为：

```text
Nexus Research
      ↓
Paper Research Tool / Service
      ↓
PaperQA
```

但它只是候选实现。

后续编码智能体可以根据：

- 当前版本；

- 许可证；

- Python 依赖；

- Provider；

- 稳定性；

- 集成复杂度；

- 与 Nexus Harness 是否冲突；

决定直接依赖、独立服务适配，或选择其他更合适的成熟项目。

其他可参考方向：

- PaperPilot；

- pi-research-agent；

- Research Papers Skill；

- 其他支持 arXiv / Semantic Scholar / OpenAlex 的科研检索 Agent。

核心要求不是“必须使用 PaperQA”，而是：

> **Paper Research 优先采用成熟、活跃、可追溯的开源科研检索能力，不重新编写一整套论文搜索与 Scientific RAG。**

***

# 7. Nexus Harness

现有 `feature/xh202620` Research Harness 不再作为新的 Nexus 主执行链继续扩展。

新的目标是：

```text
User Request
    ↓
Nexus Harness
    ↓
Model
    ↓
Tool / Subagent
    ↓
Observation
    ↓
Model
    ↓
Continue / Re-plan / Compact
    ↓
...
    ↓
Answer / Artifact
```

而不是：

```text
Intent
↓
Action
↓
Single Tool
↓
Response
```

***

# 8. 旧 Research Harness

旧 Research Harness 暂时保留。

处理策略：

```text
Legacy
↓
保留回滚能力
↓
不继续向通用 Agent 方向扩建
↓
新 Nexus 稳定
↓
停止主入口使用
↓
再清理
```

可以继续复用其中真正有价值的业务能力，例如：

- Paper provider；

- Citation；

- Evidence；

- Research Workspace 数据；

- 写作 / 趋势等已有领域工具。

核心原则：

> **保留领域能力，替换旧的 Agent 调度核心。**

***

# 9. Nexus Runtime

建议 Nexus 建立独立 Runtime。

```text
Existing Backend
│
├── Auth
├── Course
├── CS Knowledge
├── Course Knowledge
├── Teaching Agent
├── Evidence
└── Existing Business
        │
        │ Controlled API / Tool
        ↓
Nexus Runtime
        │
     Agent Harness
        │
   Nexus Mode Switch
```

这样可以避免：

- 旧 Agent Runtime 与新 Harness 强耦合；

- 旧 LangGraph 版本阻碍升级；

- 新 Agent 依赖污染原教学后端；

- 失败时影响既有业务。

***

# 10. Quick Reproduction

比赛版本的 NexusLab 不追求“自动复现任意论文”。

只完成：

# Quick Reproduction

目标：

> 输入一篇论文和对应 GitHub Repository，在隔离环境中理解论文实验、分析仓库、构建环境、运行一个关键可执行实验，并使用真实结果生成复现报告。

典型链：

```text
Paper PDF + Repository
          ↓
       Parse
          ↓
   Extract Claim
          ↓
    Inspect Repo
          ↓
      Repro Plan
          ↓
Build Environment
          ↓
Development Sandbox
          ↓
 Smoke Test
          ↓
 Repair if needed
          ↓
Quick Experiment
          ↓
 Real Metric
          ↓
Clean Verification
          ↓
Deterministic Compare
          ↓
 Reproduction Report
```

比赛 Demo 只验证一个可执行 Claim。

例如：

```text
Paper accuracy = 91.4%
Actual accuracy = 90.8%
Tolerance = ±2%

Result = PASS
```

最终 PASS / FAIL 不交给 LLM 主观判断。

***

# 11. Quick Reproduction 的开源组合

优先考虑：

| 能力                        | 开源方向                            |
| ------------------------- | ------------------------------- |
| Agent Harness             | Deep Agents                     |
| Durable Runtime           | LangGraph                       |
| PDF                       | 现有 Docling 或成熟解析器               |
| Scientific Paper Research | PaperQA / 同类成熟工具                |
| Repository                | Git / GitHub                    |
| Environment Build         | Docker / repo2docker / 成熟环境工具   |
| Workspace                 | Deep Agents Sandbox 或兼容 Sandbox |
| Code Operation            | 复用成熟 Coding Agent / Sandbox 能力  |
| Verification              | 小型 deterministic adapter        |
| Report                    | Markdown / JSON Artifact        |

不是要求强制使用这张表中的所有项目。

实际实现时允许替换。

***

# 第二部分：面向 AI 编码智能体的工程原则

# 12. 总体开发哲学

这一阶段的目标不是证明团队“可以自己写一个 Agent Framework”。

目标是：

> **用尽可能少的自研代码，把已经成熟的生产级开源能力正确组合成 CodeNexus。**

编码智能体应优先：

```text
Search
↓
Evaluate
↓
Reuse
↓
Adapt
↓
Integrate
↓
Test
```

而不是：

```text
Read requirement
↓
Immediately implement from scratch
```

***

# 13. 开源优先原则

对于以下通用能力：

```text
Agent Loop
Todo
Context
Compaction
Checkpoint
Resume
Subagent
Filesystem
Sandbox
Paper Search
Scientific RAG
Repository Inspection
Environment Build
Artifact Rendering
GPU / Compute
```

在编写较大自研实现之前，先检查当前 GitHub 和官方生态是否已有成熟项目。

优先顺序：

```text
官方 / 活跃成熟项目
        ↓
成熟社区项目
        ↓
已有项目能力
        ↓
薄 Adapter
        ↓
必要时自研
```

***

# 14. 对“直接拿代码”的要求

复用开源项目不等于盲目 Copy-Paste。

编码智能体应自行检查：

- License；

- Release / Tag；

- 最近维护时间；

- Issue；

- 已知安全问题；

- Python / Node / Runtime 版本；

- API 稳定性；

- 与当前架构是否冲突；

- 是否会引入巨大的依赖树；

- 是否需要长期 fork；

- 是否存在更简单的 integration point。

优先：

```text
Package dependency
SDK
CLI
MCP
HTTP service
Plugin
Skill
Adapter
```

最后才考虑：

```text
复制源码
长期 Fork
```

***

# 15. 版本原则

“使用最新代码”不等于生产环境永远追 `main`。

推荐：

```text
开发调研阶段：
查看最新 upstream

↓ 确认能力与修复

集成阶段：
选择经过验证的最新稳定版本

↓ 测试

生产 / Demo：
Pin 具体版本 / commit
```

目标是同时获得：

- 新修复；

- 可重复构建；

- 不被 upstream 突然破坏。

***

# 16. 自研代码边界

CodeNexus 自己写的代码优先集中在：

```text
Domain Adapter
Profile
Tool Registration
Permission Mapping
Context Mapping
Citation Mapping
Artifact Mapping
Verifier
Product API
UI Integration
```

尽量避免自己重新实现：

```text
Agent Runtime
Generic Todo Engine
Generic Context Compressor
Generic Checkpointer
Generic Filesystem Agent
Generic Shell Agent
Generic Scientific Search Engine
Generic Docker Orchestrator
```

***

# 17. 低复杂度 Glue Code

后续代码设计应优先追求：

```text
少
薄
明确
可替换
可测试
```

例如：

```text
Nexus
↓
PaperResearchPort
↓
PaperQAAdapter
```

以后替换 PaperQA：

```text
PaperQAAdapter
      ↓
OtherPaperResearchAdapter
```

不影响 Nexus。

类似地：

```text
EnvironmentBuilder
SandboxProvider
PersonalContextProvider
ComputeProvider
ArtifactProvider
```

都应尽量保持薄接口。

***

# 18. 不把方案文档当成文件级施工图

后续编码智能体拥有自行分析仓库并决定目录与文件的空间。

本方案规定：

- 产品边界；

- 服务边界；

- 能力；

- 数据归属；

- 风险；

- 验收标准。

不要求机械遵守某个提前虚构的文件名。

编码前应首先检查当前 `feature/xh202620` 实际代码。

如果当前仓库结构与本文假设发生变化：

> 以不破坏产品边界和验收目标为前提，允许调整实现方式。

***

# 19. 推荐参考项目池

以下项目作为后续编码智能体优先研究范围，不构成强制依赖清单。

## Agent Harness

- `langchain-ai/deepagents`

- `langchain-ai/langgraph`

- `anomalyco/opencode`

- `OpenHands/OpenHands`

用途：

- Tool Loop；

- Context；

- Session；

- Compaction；

- Filesystem；

- Subagent；

- Permission；

- Coding UX；

- Sandbox。

***

## Scientific Paper Research

- `Future-House/paper-qa`

- `mtilyxuegao/PaperPilot`

- `hinsencamp/pi-research-agent`

- `marciob/skill-research-papers`

重点关注：

- Paper Discovery；

- OpenAlex；

- arXiv；

- Semantic Scholar；

- Citation；

- Evidence Gathering；

- full-text；

- agentic research。

***

## Paper Reproduction

参考：

- `1a1a11a/2026_paper_reproduce`

- `AI9Stars/AutoReproduce`

- PaperBench 的 reproduction / verification 思想

用途：

- Paper → Repo；

- Environment Inspection；

- Claim Extraction；

- Execution；

- Verification；

- Report。

注意：

> 参考设计前必须再次检查当前 License 和成熟度。

***

## Environment / Runtime

- `jupyterhub/repo2docker`

- Docker / devcontainer 生态

- SWE-ReX

- OpenHands Runtime

用途：

- Repository environment；

- Sandbox；

- Shell；

- Remote runtime。

***

## Compute

P1/P2 可研究：

- dstack；

- SkyPilot。

比赛 P0 不要求多云调度。

***

# 20. 编码智能体的决策准则

当候选方案 A 与 B 都可以实现功能时，优先：

```text
更成熟
>
更少自研代码
>
更稳定
>
更容易测试
>
更容易升级
>
与现有技术栈冲突更小
>
代码更少
```

不要仅仅因为：

> “这个库功能更多”

就选它。

***

# 21. 必须保持的系统边界

无论最终采用什么开源项目，以下边界不能被破坏。

## Teaching

```text
RE-KT
Learner Model
Judge0 学习测评
Learning Evidence
```

属于 Teaching Agent。

***

## Nexus

```text
General Agent
RAG
Web
Personal Context
Artifact
```

属于 Nexus。

***

## Research Mode

在 Nexus 基础上增加：

```text
Paper Research
NexusLab
Quick Reproduction
```

***

## Business Data

现有 Backend 仍然是：

```text
User
Course
Permission
Knowledge
Evidence
```

的业务真相来源。

Nexus Runtime 不重新建立一套业务数据库。

***

# 第三部分：实施 Plan

# Phase 1：建立新的 Nexus Harness

## 给人看

这一阶段先把 Nexus AI 真正跑起来。

目标不是接全部功能，而是证明：

> 同一个 Nexus Agent 可以进行连续 Tool Loop、Streaming、Context 管理和长任务，而不是旧 Harness 的单 Action 模式。

完成后，应该已经有一个最简单的 Nexus 聊天入口。

***

## 给 AI 编码智能体

需要完成：

- 审查当前 `feature/xh202620` Agent 代码；

- 不继续扩建 Legacy Research workflow；

- 建立与旧 backend 隔离的新 Nexus Runtime；

- 优先直接集成成熟 Deep Agent Harness；

- 建立至少一个简单 Tool；

- 验证连续两次以上 Tool Call；

- Streaming；

- Thread / Session；

- Cancel；

- 基础 checkpoint / resume；

- 保留未来 mode/profile 扩展接口。

自由度：

- 可以自行选择最合理目录；

- 可以根据 Deep Agents 最新 API 调整架构；

- 可以引入必要 dependency；

- 不要求复制本文中的示例文件布局。

验收：

```text
一个用户请求
→ Agent 调 Tool A
→ 根据结果调 Tool B
→ 返回最终结果
```

真实成功。

***

# Phase 2：实现 Nexus / Nexus Research 模式切换

## 给人看

用户仍在同一个 Nexus AI 中。

点击 Research 后，不换页面里的“另一个机器人”，而是给当前 Agent 增加科研 Profile 和科研工具。

***

## 给 AI 编码智能体

实现：

```text
mode = general
mode = research
```

或等价设计。

General：

- General Prompt；

- 通用 Tools。

Research：

- 在 General 基础上；

- 轻微 Research Prompt；

- 增加 Paper / NexusLab 等 Tools；

- 增加 Research Skills；

- 可以采用更积极的 Plan / Todo 策略。

必须确认：

- Runtime 是同一个；

- Session 模型不被复制；

- Tool 权限根据 mode 动态变化；

- 模式切换后不会污染 Teaching Agent。

验收：

```text
General 看不到 Research-only Tool
Research 可以正常使用 Research-only Tool
```

***

# Phase 3：接入内部 RAG 与 Web

## 给人看

让 Nexus 真正利用 CodeNexus 已经完成的 Computer Science Knowledge Base 和课程资料。

这一阶段是 Nexus 与现有系统真正连接起来的第一步。

***

## 给 AI 编码智能体

接入：

- CS Knowledge Retrieval；

- Course Retrieval；

- Citation；

- Web Search。

优先复用现有 Backend。

不要：

- 复制 CS Knowledge；

- 重新建立一套 Course KB；

- 把数据库直接搬进 Nexus Runtime。

目标模式：

```text
Nexus Tool
↓
Existing Backend Capability
↓
Structured Result
```

需要：

- source；

- title；

- section/page（若已有）；

- evidence/citation metadata。

验收：

一个问题可以同时：

```text
Course RAG
+
CS RAG
+
Web
```

并由 Nexus 根据相关性决定最终使用哪些证据。

***

# Phase 4：Artifact

## 给人看

Nexus 不仅返回聊天文本，还能真正生成可以使用的文件。

P0 优先：

- Markdown；

- LaTeX；

- DOCX。

***

## 给 AI 编码智能体

优先寻找成熟 Artifact / document generation 能力。

建立统一 Artifact 结果：

```text
artifact_id
type
title
location
metadata
```

不要让模型只是输出：

> “以下是 Word 文档内容。”

而要真正生成文件。

验收：

```text
User
→ 要求生成研究笔记
→ Nexus
→ Artifact Tool
→ 实际 .md / .docx
```

***

# Phase 5：Paper Research

## 给人看

Research Mode 可以真正搜索和研究学术论文。

它不是简单的 arXiv 搜索框，而是：

```text
Research Question
↓
Find Papers
↓
Gather Evidence
↓
Compare
↓
Synthesize
↓
Citation
```

***

## 给 AI 编码智能体

首先评估成熟 Scientific Research 项目。

优先研究：

```text
Future-House/paper-qa
```

当前公开项目已经覆盖：

- scientific document RAG；

- paper search；

- evidence gathering；

- citations；

- agentic workflows。

如果兼容：

> 优先直接作为 library/service/adapter 使用。

如果当前版本存在较大的：

- dependency conflict；

- security issue；

- runtime conflict；

- integration complexity；

允许选择其他成熟项目。

不要为了贴合本文而硬接 PaperQA。

最低能力：

```text
paper_search(query)
paper_research(question)
```

返回：

- paper metadata；

- evidence；

- citation；

- answer。

验收：

用户问：

> “最近有哪些工作研究 X？主要方法有什么差异？”

Nexus Research 能真实搜索多篇论文并给出可核查来源。

***

# Phase 6：Personal Context

## 给人看

Nexus 可以记住用户长期稳定信息。

例如：

- 常用语言；

- 研究方向；

- 项目；

- 长期目标；

- 输出偏好。

它不是学生掌握度模型。

***

## 给 AI 编码智能体

优先评估：

- Mem0；

- Deep Agents 自带长期 memory 能力；

- 当前 GitHub 更适合的成熟方案。

如果接入成本高：

> 可以推迟，不得阻塞 Harness、RAG 和 Research 主链。

至少保持一个稳定抽象：

```text
search relevant personal context
store explicit stable memory
update
delete
```

验收：

跨会话可以召回一个明确用户偏好。

***

# Phase 7：Quick Reproduction

## 给人看

这一阶段实现比赛最重要的科研演示能力。

输入：

```text
Paper PDF
+
Official GitHub Repo
```

输出：

```text
真实构建环境
真实执行实验
真实结果
可验证复现报告
```

不承诺完整自动复现整篇论文。

***

## 给 AI 编码智能体

目标链：

```text
Paper
↓
Parse
↓
Extract One Executable Claim
↓
Inspect Repository
↓
Build Environment
↓
Sandbox
↓
Smoke Test
↓
Repair
↓
Quick Experiment
↓
Clean Re-run
↓
Metric Compare
↓
Report
```

开发原则：

- Harness 用现成能力；

- Repo 操作用成熟 Git/Coding Agent 工具；

- Environment 优先复用成熟 project；

- Sandbox 不自己重新实现完整 shell agent；

- 只自研薄 Reproduction Glue 和 deterministic verifier。

重点调研：

```text
repo2docker
Deep Agents Sandbox
SWE-ReX
OpenHands Runtime
2026_paper_reproduce 的流程
AutoReproduce 的研究方法
PaperBench 的 clean verification 思想
```

P0 可以只支持：

```text
Dockerfile
or
repo2docker
```

P0 只验证一个 Claim。

Repair 最大轮数应有限。

最终 PASS / FAIL 由 deterministic metric comparison 决定。

验收：

至少选定一篇真实开源论文，完成：

```text
论文指标
vs
容器真实运行指标
```

并生成：

```text
report.md
report.json
logs
environment info
metric result
```

***

# Phase 8：Clean Reproduction

## 给人看

“Agent 在自己的开发容器里跑通”不能直接叫可复现。

需要一个新的干净环境重新运行。

***

## 给 AI 编码智能体

实现两个逻辑空间：

```text
Development Environment A
```

允许 Agent：

- 修改；

- 调试；

- 安装；

- Repair。

然后：

```text
Verification Environment B
```

使用被冻结的：

- repository snapshot；

- environment；

- command；

- config。

B 中不允许 Agent临时修。

只有 B 成功才输出：

```text
reproducible = true
```

P0 可以采用简单可靠的 freeze 方案。

不要为了追求完美可复现规范拖死 Demo。

***

# Phase 9：可靠性

## 给人看

这一阶段不增加新卖点，只把系统从 Demo 变成真正可用。

***

## 给 AI 编码智能体

建立 Harness Stress Suite。

至少测试：

```text
多 Tool 长任务
Tool 500
Context overflow
Runtime restart
Resume
Cancel
Approval
Malformed Tool
Duplicate write
Permission denial
Sandbox timeout
```

对于 Quick Reproduction：

```text
Build fail
Dependency fail
Smoke fail
Experiment fail
Metric missing
Clean verification fail
```

都必须产生明确状态。

禁止：

- 静默成功；

- LLM 编造实验结果；

- 没执行却写 PASS。

***

# Phase 10：前端整合

## 给人看

最终用户看到一个类似 ChatGPT / Codex 的 Nexus 页面。

主要交互：

```text
Conversation
Mode Switch
Tool Progress
Todo / Task
Artifact
Approval
Stop
```

Research Mode 再出现：

```text
Paper
Research
NexusLab
Reproduction
```

***

## 给 AI 编码智能体

先检查当前 frontend 实际架构，再决定组件与目录。

不要基于本文虚构页面路径。

必须实现的交互能力：

- Nexus / Research Mode；

- streaming；

- tool status；

- Stop；

- approval；

- artifact；

- reproduction stages；

- report link。

UI 不应暴露模型内部 Chain-of-Thought。

可以展示：

```text
Searching papers
Reading repository
Building environment
Running experiment
```

等操作状态。

***

# Phase 11：Legacy 迁移

## 给人看

当 Nexus 已经证明稳定，再逐步停止旧 Research Harness。

不是边写新系统边拆旧系统。

***

## 给 AI 编码智能体

迁移前先确认：

- 路由调用；

- frontend 调用；

- test；

- workspace data；

- provider；

- external dependency。

优先：

```text
Disable Entry
↓
Observe
↓
Remove Dead Code
```

不要一次性删除大量旧代码。

Teaching Agent 与 Prep Agent 不因 Nexus 上线被强制迁移。

***

# Phase 12：比赛验收链

最终需要稳定演示：

```text
进入 Nexus AI
↓
普通模式
↓
CS / Course RAG + Web
↓
生成 Artifact
↓
切换 Nexus Research
↓
Paper Research
↓
选择一篇论文
↓
Quick Reproduction
↓
环境构建
↓
真实运行
↓
Clean Verification
↓
Reproduction Report
```

其中最重要的是：

```text
真实 Tool
真实知识源
真实环境
真实命令
真实 Metric
真实 Artifact
```

而不是 UI 模拟。

***

# 第四部分：当前范围冻结

当前优先级：

```text
P0
Nexus Harness
Mode Switch
RAG
Web
Artifact
Paper Research
Quick Reproduction

P1
Personal Context
更完整 Research Workspace
更丰富 Artifact
更强 Sandbox

P2
GPU Compute Provider
dstack / SkyPilot
多云 / 学校集群
更完整论文复现
```

当前明确不做：

```text
重新设计 Teaching Agent
把 RE-KT 塞进 Nexus
重新实现完整 Agent Framework
强制 Fork OpenCode
Rust 重写
同时接入大量 Agent Framework
多云 GPU P0
任意论文一键完整复现
LLM 主观判定实验成功
```

整个转型当前可以概括为：

```text
Existing Teaching System
        │
        ├── Teaching Agent
        │
        │    Learning / Practice
        │    Judge0 / RE-KT
        │
        │
        └── Existing Domain Services
                     │
                     │
                Nexus Tools
                     │
                     ↓
                 Nexus AI
                     │
               Same Harness
                     │
             [General / Research]
                     │
                     └── Research Mode
                          ├── Paper Research
                          └── NexusLab
                               └── Quick Reproduction
```

后续编码的核心不是增加更多架构层。

而是：

> **尽量站在成熟开源产品肩膀上，用最少、最薄、最稳定的 CodeNexus 代码把这些能力真正接起来，并用真实可执行结果证明它们工作。**

