> **历史快照（2026-09-05，v1.3 清理前）**：仅供追溯，不作为当前实现、工具面或开发指令。现行入口：[v1.3 架构](CodeNexus_转型设计与实施方案_v1.3.md)、[开发计划](CodeNexus_P2开发计划.md)、[前端规格](Nexus_AI_前端开发规格与UX落地说明.md)。下文旧默认模式、审批、License、分支和状态描述可能已被纠正。

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


***

# 第五部分：P2 主线收官后的推进路线（2026-09-05）

## 22. 当前状态

P2 主线 M0-M5 已完成当前验收范围：独立 Runtime、General/Research 模式、Web 与 Course/CS RAG、Artifact、nanoGPT 预设执行、基础结果卡、确定性报告、权限隔离、消息历史恢复和 Legacy Research S3 下线。它形成了真实的受控 MVP 演示链，不能等同于原 Phase 12 的完整 Paper Research / Paper-to-Reproduction 目标。当前准确定位为多工具、长上下文、可恢复 Agent Runtime + Verified Preset Reproduction Runner；最终产品缺口按 §27–31 和 P2 计划 §11.1 继续建设。

已完成的依据包括：M0-M4 验收记录、M5 S3 与压力套件验收记录、线上 health/对话/复现/Artifact 实证，以及 Runtime 压力套件 82 项通过（其中 M5 新增 7/7）。

## 23. 当前不纳入 P2 主线的事项

以下事项不影响既定比赛演示链，但应保持边界清晰：

- **Clean Verification**：目前 Quick Reproduction 已完成受限 Worker 执行与确定性报告；开发环境 A / 冻结验证环境 B 的完整双环境语义仍属于 P2+。
- **Paper Research**：当前只有 Paper Search（arXiv 元数据检索）。真正的 Paper Research——全文阅读、证据收集、方法比较、综合回答和可核查 Citation——尚未完成，是 Nexus Research 的主要功能缺口；应优先评估 PaperQA（Apache-2.0）或同类成熟 Scientific RAG/Agent 方案。
- **Harness 扩展**：当前 Todo 与 Subagent 尚未产品化；通用文件/执行工具继续关闭。它们属于最终 Nexus Harness 的规划能力，不应从产品设计中删除。
- **Personal Context**：长期用户偏好记忆尚未进入比赛 P0，不阻塞主链。
- **会话附件（范围已扩展）**：按用户最新要求，General/Research 均规划支持 PDF、DOCX、JPG、PNG、XLSX、PPTX、PPT、DOC；Research Paper Import 是共享附件入口上的论文处理 Profile。替代此前“仅 PDF、其他附件不做”的范围限制；当前尚未接线，详见 §30。
- **两项既有域测试**：`test_alembic_migration` 与 `test_p0_2_async_tasks` 属于 course-access/任务域既有问题，单独修复，不归因于 Nexus M5。

## 24. 比赛前落地顺序

以下保留为稳定 preset 演示的准备清单，不再作为禁止继续建设产品的范围冻结。今天确认的附件、Harness、论文研究/复现、Console 与 Session 按 P2 计划 §十一独立推进，未经新验收不替换稳定演示链：

1. 用已入课账号和真实课程 15 走一遍 Course RAG；无权限账号保留一次诚实拒绝演示。
2. 在 Research 模式完成论文检索 → nanoGPT 计划 → Worker 执行 → 阶段状态 → PASS/FAIL → report.md/report.json 下载。
3. 浏览器手工走查 Mode 切换、会话恢复、Stop、错误提示、Artifact 下载、复现状态卡和报告卡。
4. 固化演示账号、课程、论文预设、清理方式和故障备用路径；所有账号和令牌继续只存在服务器环境。
5. 比赛前执行一次 Nexus 全量测试、前端契约测试、构建和线上只读健康检查，记录版本与时间戳。

## 25. P2+ 推进准则

后续分必要主线与可选增强。Harness、八格式附件、Paper Research、Sandbox Runtime、Paper-to-Reproduction（含 A/B Clean Verification）、Experiment Console 与服务端 Session 均为已纳入的产品目标，不能混入永久“不排期候选池”。Personal Context 等为可选增强。go/no-go 用于组件和集成方式，不用于取消已确认产品目标；必要能力暂未实现时如实标明。

- **Paper Research（优先）**：先验证 PaperQA/同类项目的 License、全文获取、证据定位、引用质量和依赖隔离；产出 `paper_research`、`gather_evidence`、`compare_papers` 等薄 Adapter 或明确 no-go。
- **会话附件与 Research Paper Import（必要入口）**：先接通共享附件生命周期，再按格式补齐八类解析；论文 Profile 增加章节、页码、表格与证据定位。复用 Backend 底层解析组件和对象存储，独立管理 Nexus 会话附件，不调用课程入库流水线；见 §30。
- **Harness Todo（优先）**：按任务复杂度启用 `TodoListMiddleware`；简单 General 不启用，复杂 General 允许启用，Research/复现长任务默认启用；补齐持久化、SSE、前端投影、取消和恢复。
- **Harness Subagent（次优先）**：先在 Research 长任务中开放受限 Subagent Profile，使用独立工具白名单和可审计子任务状态。
- **文件与执行工具（后置）**：在独立文件沙箱、审批、配额和会话级工作区明确前，不恢复 `write_file`/`edit_file`/`execute`。
- Clean Verification：先冻结 nanoGPT repo、镜像、命令和配置，再验证 B 环境；只有 B 成功才写 `reproducible=true`。
- Paper Research 全文化：先比较 License、依赖、全文获取和引用质量，再决定 library、独立服务或不接入。
- Personal Context：只存用户明确确认的稳定偏好，支持查询、更新和删除，不替代 TeachingAgent 学习模型。
- 可靠性维护：继续观察 Compact 全图触发边界、Worker 并发和对象存储 retention；发现问题先加回归测试再改线上。

## 26. 文档与发布纪律

后续每个 P2+ 变更都必须同步验收记录、P2 计划和文档索引；线上变更继续遵守“先只读核查、明确授权、可回退”。任何新能力只有在真实链路和失败语义通过后，才能从 `wired/unwired` 翻为 `ready`。

## 27. Harness 能力边界修订（2026-09-05）

### 27.1 当前真实状态

当前 Nexus 已完成 Deep Agents 驱动的多工具、长上下文、可恢复 Agent Runtime，已验证 Tool Loop、Streaming、Checkpoint、Context Summarization、权限边界和 Quick Reproduction 产品链。

当前仍有意收敛的通用 Harness 能力包括：

- `TodoListMiddleware` / `write_todos`：未进入当前产品运行时；
- `GeneralPurposeSubagentProfile` / `task`：当前未对 Nexus 用户开放；
- `write_file`、`edit_file`、`glob`、`grep`、`execute`：继续关闭，避免在没有独立文件沙箱、审批和会话级工作区前扩大攻击面。

因此，当前 Nexus 的准确表述是：

> **已完成 Deep Agents 驱动的多工具、长上下文、可恢复 Agent Runtime；Todo 与 Subagent 尚未产品化，通用文件/执行工具仍按安全边界关闭。**

不得把当前状态宣传为“完整复杂任务 Harness”或“通用 Codex 工作区”。

### 27.2 Todo 重新启用原则

Deep Agents 0.7 并未删除 Todo 能力；默认 Harness 移除了 `TodoListMiddleware`，可通过显式 `middleware=[TodoListMiddleware()]` 重新启用。后续按任务复杂度启用：

- 简单 General 请求：不启用 Todo；
- 明显多步骤的 General 请求：允许启用 Todo；
- Research 长任务、复现任务：启用 Todo / Planning，并将真实状态事件展示给前端。

启用前必须完成：工具面契约、状态持久化、SSE 事件、前端展示、取消/恢复语义和失败测试；没有这些配套时不得只把 `write_todos` 暴露给模型。

### 27.3 Subagent 重新评估原则

Subagent 是可选的产品增强，不是比赛 P0 的必需项。后续如启用，必须限定：

- 只在 Research 或明确的长任务 Profile 中开放；
- 使用独立权限和工具白名单；
- 子 Agent 不得绕过 Course Access、Artifact owner 校验或 Repro Worker 安全边界；
- 父任务可取消、可恢复，并保留可审计的子任务状态；
- 先用一个只读、无外部副作用的子任务做验证，再扩大能力。

### 27.4 后续执行顺序

这不是立即扩大工具面的指令。比赛演示继续使用已验收的收敛工具面；下一轮开发先做 Harness 能力评估，再决定是否实现：

1. 评估并接入 TodoListMiddleware，优先 Research 长任务；
2. 为 Todo 增加持久化、SSE 和前端状态投影；
3. 评估受限 Subagent Profile；
4. 在独立文件沙箱与审批方案明确后，再评估 `write_file` / `edit_file` / `execute`；
5. 每项能力单独验收，未通过则保持关闭。

## 28. 复现执行隔离边界修订（2026-09-05）

### 28.1 当前实现的准确定位

现有 `repro-worker` 是一个受资源限制的执行容器，内部通过 bash subprocess 运行已审核的 preset。其安全性依赖于：仅允许代码内置 preset（当前为 `nanogpt`）、仓库与命令预先核验、CPU/内存/PID/网络/900 秒截止限制、无生产凭据以及串行队列。

因此当前能力应称为：

> **受限、预设驱动的 Verified Preset Reproduction Runner。**

它不是可接收任意 GitHub URL 和任意 shell command 的通用 Sandbox Runtime，也不应被宣传为已经实现了完整论文复现实验环境。

### 28.2 与目标架构的差异

最终 Paper-to-Reproduction Pipeline 需要显式分离环境构建与清洁验证：

```text
Paper / Repo / ReproPlan
        ↓
Container A：依赖安装、环境修复、冒烟运行
        ↓ freeze
Container B：从冻结规格重建的干净验证环境
        ↓
确定性指标比较 → 报告
```

Container A 的尝试、修复和缓存不得直接成为成功证据；只有 Container B 在冻结的仓库版本、镜像/依赖锁、命令和配置下完成，才能把结果标记为 `reproducible=true`。当前 Worker 仅覆盖预设执行和单环境结果，A/B 双环境仍是 P2+ 能力。

### 28.3 任意仓库开放前置条件

在独立 Sandbox Runtime、文件系统隔离、网络出口策略、凭据零暴露、资源配额、任务取消与清理、审计日志和人工/策略审批完成并通过安全验收前，禁止开放：

- 用户任意 GitHub URL；
- LLM 任意生成的 shell command；
- 在 Backend、Judge0 或生产网络中直接运行未知仓库代码。

未知仓库必须先经过来源与 License 核验，再生成受约束的 ReproPlan；依赖安装脚本、构建脚本和运行命令都视为不可信输入。若任一隔离或审批门失败，任务必须 fail-closed，并保留可解释的拒绝原因。

### 28.4 P2+ 落地顺序

1. 把当前 Worker 的 preset 执行接口与未来 Sandbox Runtime 接口分离，保持比赛演示链可回退。
2. 设计 Sandbox Job、Workspace、Image/Dependency Lock、Network Policy、Approval 和 Cleanup 契约。
3. 先实现只读、无外部副作用的 Container A/B 烟囱验证，再接入论文仓库。
4. 增加恶意安装脚本、越权路径、网络探测、资源耗尽、超时和取消回收测试。
5. 只有 A/B、指标判定、报告和审计链全部通过后，才评估从 preset 扩展到受控仓库集合；任意仓库执行属于更后置的 go/no-go 决策。

## 29. 成熟开源优先的复现运行时路线（2026-09-05）

### 29.1 当前偏差

当前 Repro Worker 的 Worker API、Job 状态、License 检查、命令执行、超时/磁盘配额、artifact 扫描、seed 解包、preset、指标提取和报告生成，主要是 Nexus 自研代码。它已经满足比赛版 `nanogpt` 的受控演示，但与“复现运行时优先复用成熟开源产品”的设计原则存在偏差。

### 29.2 保留现状，改变目标架构

不重做已经验收的 Worker。比赛阶段继续使用 `Preset Repro Worker`，确保稳定、可回退、无新增外部依赖。后续将增加一层 `Reproduction Orchestrator`，把论文/仓库解析、ReproPlan、环境构建、执行、冻结、验证和报告编排与具体运行时解耦：

```text
Nexus Research
      ↓
Reproduction Orchestrator
      ↓
SandboxProvider（统一契约）
      ↓
SWE-ReX / OpenHands Runtime / 同类执行运行时（待评估）
```

现有 Worker 保留，后续再适配为 `PresetSandboxProvider`（当前不存在该已验收适配层）；未来以 SWE-ReX 或同类成熟执行运行时作为优先候选。repo2docker 是环境构建层候选，可与执行层组合，不作为等价 shell runtime；A/B 生命周期仍须编排验收。Nexus 自研代码集中在权限、策略、编排、指标判定、报告和业务适配，不重复实现通用 shell/runtime 隔离层。

### 29.3 开源方案评估与迁移门槛

接入前必须形成可复核的选型记录，至少比较 License、隔离强度、Docker/本地/云执行适配、网络和凭据策略、超时/取消/日志、A/B 环境支持、依赖维护活跃度和与现有 Worker 的迁移成本。候选方案未通过安全与功能验收时，继续使用 `PresetSandboxProvider`，不得为了“开源优先”破坏比赛链路。

迁移采用兼容适配：先让同一 `SandboxProvider` 契约同时支持 preset Worker 和候选开源 runtime，再以同一组 nanoGPT 回归、恶意仓库防护、资源耗尽、取消清理和 A/B 可复现测试比较结果；通过后才允许扩大仓库范围。

## 30. General / Research 会话附件设计（2026-09-05，规划，未实施）

### 30.1 范围与复用证据

用户将输入范围明确扩展为 `.pdf/.docx/.jpg/.png/.xlsx/.pptx/.ppt/.doc`。附件上传属于产品必需能力；Paper Import 是其中的论文处理模式，不再另建一套上传系统。本节替代 §23/§25 和 P2 计划此前“仅 PDF、其他附件不做”的限制。DOCX **输入解析**与此前 DOCX **产物生成**的 no-go 是两件事。

2026-09-05 本地代码核查（未做八格式线上验收）：

- `backend/pyproject.toml` 已声明 Docling、python-docx、python-pptx、openpyxl；依赖存在不代表 Nexus 已接线。
- `backend/app/services/document_parse_pipeline.py` 的注册表接入 NativePptx、PdfPlumber、PythonDocx 等 Provider；不能仅凭 Docling 依赖就把当前主流水线称为 Docling。
- `backend/app/platform/document_intelligence/registry.py` 已有 `ParserProvider` / `ParserOutput`，可复用结构化解析边界；`planner.py` 尚无 XLSX 专用分支，必须补齐，不能落到任意 Provider。
- 同目录 `libreoffice_converter.py` 已有 DOC/PPT → PDF 转换；`ocr_port.py` 有独立 PaddleOCR HTTP 适配。真实服务可用性需另验收。
- `backend/app/services/document_parse_service.py` 绑定 course/material、证据及图谱候选；Nexus 附件不能直接调用该课程业务服务，更不能伪造 course_id 以复用它。

### 30.2 推荐解析路由

| 输入 | 推荐复用/补齐路线 | 给模型的内容与定位 |
| --- | --- | --- |
| PDF | 复用 PDF Provider；论文复杂排版评估 Docling；扫描页经已有 OCR 接口 | 正文、表格、页码、块坐标；公式和图表质量不足给 warning |
| DOCX | 复用 PythonDocx Provider；需要版面引用时转换 PDF | 标题、段落、表格；原生以段落/块定位，禁止编造页码 |
| JPG / PNG | 校验后优先将原图/受控派生图与问题传给支持视觉输入的模型；OCR 按文字提取、检索和坐标引用需要调用 | 图像解释及原图引用；OCR 路径另返回文字、区域与置信度，不以 OCR 替代看图 |
| XLSX | openpyxl 专用薄适配，read-only，分 sheet/范围读取 | sheet、单元格坐标、类型、公式与缓存值；不执行公式，缓存缺失/可能陈旧需提示 |
| PPTX | 复用 NativePptx Provider | 幻灯片号、标题、正文、备注、表格；图表图像按需增强 |
| PPT / DOC | 复用 LibreOffice 转 PDF，再复用 PDF/OCR | 保留源文件与转换件关联；页码注明来自转换版本，提示排版/备注等转换损失 |

推荐组合是“现有解析 Provider + OCR + LibreOffice + XLSX 薄适配”；Docling 作为复杂论文解析优先评估项，MarkItDown 作为轻量 Markdown 转换候选，无需同时引入两套全格式主解析器。用含扫描页、公式、表格、中文和备注的合成样例比较引用准确性与成本，再选择增强器。

**图片传模修订**：General/Research 共用多模态附件适配。图片不强制等待 OCR 或生成 Markdown；服务端校验 MIME、解码/像素限额和 owner/session 后，保留私有原件，以模型端点支持的 image content block 传入受控字节或短期授权 URL。模型必须同时具备视觉能力且请求链路保留图片字段，不能用“OpenAI 兼容”推断视觉可用；Backend 与 Nexus 间仍只通过 HTTP 传附件标识和授权后的内容。只取本系统已授权对象，不抓取用户任意 URL、不公开桶、不向模型暴露存储凭据。

模型能力表区分 `vision` 与 `text`。当前模型不支持图片时，使用已配置且获准调用的视觉模型辅助；没有可用视觉模型时，可将 OCR 作为明确标注的文字降级，对图表/照片理解返回能力不足，不声称已看图。图片直读状态与 OCR 状态分开：OCR 失败不阻塞已可用视觉路径。原图过大可缩放或裁剪，保留坐标映射及原件引用；视觉上下文同样计入图片数、分辨率和费用预算。外部模型传图遵守与文本相同的数据与服务授权策略。

官方参考：[Docling 支持格式](https://docling-project.github.io/docling/usage/supported_formats/)（PDF、DOCX、PPTX、XLSX、图片及 Markdown/JSON 输出）；[MarkItDown](https://github.com/microsoft/markitdown)（MIT、面向 LLM 的轻量 Markdown 转换，OCR/视觉能力取决于配置，不能只看格式名认定全文可读）；[LibreOffice 命令行转换](https://help.libreoffice.org/latest/en-US/text/shared/guide/start_parameters.html)。DOC/PPT 采用显式转换，不假定前两者原生支持。任何新增依赖安装另按 AGENTS.md 授权。

### 30.3 数据路径与生命周期

```text
General / Research 附件入口
  → Backend 鉴权入口 → 既有私有对象存储（object_key）
  → 文档：异步解析任务 → Markdown + blocks/tables + 定位信息 + warnings
    图片：校验后直接构造视觉输入（OCR 按需并行或后补）
  → Nexus 会话附件清单 → 按需读取/检索 → LLM 回答与引用
```

原件、转换件和解析件复用媒体/文档域存储；owner/session 绑定、解析任务与上下文索引等元数据归 Nexus 自己的存储。只复用物理存储和解析能力，不写课程材料、课程知识库、LearningEvidence 或 Course Graph。Nexus 与 Backend 保持 HTTP 边界，不共享 Python 环境、不从 Nexus 直接 import Backend。

对模型先提供附件清单、结构目录和状态；短文件在 token 预算内提供全文，长文件按块检索，表格按 sheet/范围读取。返回内容必须含 attachment_id、版本及页/幻灯片/单元格/段落引用。附件内容是用户提供的资料，不能作为系统指令；摘要不能代替可核查原文。

建议新接口族（待实现，非现有路由）：`/api/v1/nexus/attachments` 提交上传，按 attachment_id 查询状态、删除和鉴权下载；chat 传 `attachment_ids`，服务端逐一校验 owner/session、保留期与解析状态。预会话上传先绑定用户，发送时原子绑定会话；同一内容哈希不能代替权限校验。内网解析结果接口也须校验身份与附件归属。

状态区分 `uploading/queued/parsing/ready/partial/failed/expired/deleted`；UI 显示文件卡、阶段、可读范围和重试/移除。上传成功不等于可供模型使用；图片另报视觉可用/OCR 状态，文档 partial 只允许引用成功解析部分。OCR 必需但不可用、损坏、加密、超限均返回明确原因，不产生空白成功。

建议首版配置基线（待样例实测调优）：每次最多 5 文件、单文件 20 MiB、合计 50 MiB，文档 200 页/张、图片 20MP、工作簿总计 10 万非空单元格，单解析任务 180 秒；另设解压后大小、ZIP entry 数、进程内存和用户并发限额，不能只限制上传体积。未绑定文件 24 小时、已绑定会话附件 7 天到期，可在后续产品策略中调整；到期显式提示重新上传。

解析环境固定命令参数、禁宏/外链更新、禁止主动抓取文件内 URL，无宿主敏感目录与生产凭据；LibreOffice 的 headless 参数本身不是安全沙箱。网络默认关闭，OCR 经受控内部服务通道。删除立即撤销读取，异步清理原件/转换件/解析件/索引；取消和删除采用版本/状态校验，防止迟到任务写回。Checkpoint 中已注入片段也必须纳入保留和清理策略，不承诺仅删对象即可抹去历史上下文。

### 30.4 交付顺序与验收

1. 先做附件 API、鉴权、对象存储和任务状态、前端文件卡，以 PDF 完成上传→读取→引用→删除的真实链。
2. 接入 DOCX/PPTX、JPG/PNG 视觉直传与按需 OCR，补 XLSX 专用解析和 DOC/PPT 转换；每格式至少一份合成文件验证定位。验证图片字段经前后端送达模型、不支持视觉时的诚实降级及 OCR 非必经语义；未通过的格式单独标记不可用，整体范围仍是八类。
3. 接 Research 论文 Profile，验证双栏/扫描/表格/公式的证据定位；接入 Paper Research 与后续 Claim Extraction。附件 ready 不自动代表 Paper Research 已完成。
4. 验收跨用户/会话拒绝、OCR/转换器缺失、密码文件、解析超时、压缩膨胀、超大图片、取消/删除竞态、过期清理与长文件按需读取。部署和真实付费模型调用另需授权；当前只更新设计。

## 31. Experiment Console 与长任务会话（2026-09-05，纳入开发规划，未实施）

按用户要求将本轮讨论纳入现行规划。交付顺序为：服务端 run/job 关联与刷新恢复 → 实时 Experiment Console → 独立 Cancel 闭环 → 服务端会话元数据与完整产品事件恢复。这里确认的是规划范围，不代表功能完成或部署授权；任务拆分见 P2 计划 §十一 NX-E1 至 NX-E4。

### 31.1 代码现状与判断

- `frontend/src/app/pages/nexus/NexusPage.vue` 已有 job 轮询、步骤命令、exit_code、duration_s、确定性指标和报告卡。当前是基础作业结果面板，并非只有报告；无需开放交互 Shell 才算符合产品设计。
- `deploy/repro-worker/worker.py` 的 `_run_step` 使用 `proc.communicate()`，结束后返回 log_tail；`_execute_job` 先将步骤存入局部列表，主要在终态将 steps_result 写回 job。当前不等同于连续阶段和实时日志。
- `backend/app/api/v1/endpoints/nexus_proxy.py` 对日志裁剪至 300 字符，前端轮询映射未保留 log_tail；不能仅加日志组件就宣称实时 Console 完成。
- Worker 当前公开作业提交和查询，未提供用户取消端点；聊天 AbortController/Stop 不是取消已提交的实验。
- 页面 `refreshRemoteSessions` 合并本地与远程列表，remote-only 默认 General、未置顶、courseId=null；`loadRemoteHistory` 将 toolEvents 留空。`nexus/src/nexus/persistence.py` 的列表主要返回 session_id/title/updated_at，不含这些用户偏好和运行关联。
- `nexus/src/nexus/main.py` 的 `_serialize_history` 只投影 HumanMessage 与最终 AIMessage。准确缺口是工具执行的产品历史没有独立持久化/恢复接口；不能因此推断 LangGraph checkpoint 从未保存 ToolMessage。Checkpoint 会受上下文压缩和保留策略影响，不宜直接充当前端历史 API。
- 同浏览器刷新可保留 localStorage 中的工具卡，但当前轮询主要在新 tool_result 到达时启动，未见挂载后统一恢复未完成 job 的逻辑；换设备/清空缓存时，执行过程、模式和任务绑定缺口更突出。本轮为本地代码核查，未做线上手工验收。

### 31.2 Experiment Console 的最小产品范围

沿用会话内实验卡，详情展开为只读 Console，字段为：**Stage、Command label、Elapsed、Exit code、最近 20 行日志（可配置 10–30 行）、Metric、Report、Cancel**。命令标签由服务端 preset/受审核计划生成，如“准备仓库”“安装依赖”“训练”“评估”，不提供命令编辑或 stdin。日志同时限制行数与字节数，先在服务端脱敏，再做前端纯文本转义，过滤控制序列；仅发起人可查询。

阶段由实际执行边界产生，目标顺序为 Preparing → Building → Running → Metric → Verifying → Completed，失败/取消/超时另列终态。当前 preset 用预构建镜像时，Building 标记复用/跳过；未实现干净环境 B 时，Verifying 标记未实施/不适用，不能借指标比较冒充 Clean Verification。进程成功、指标 PASS/FAIL 和清洁复现结论分开显示，缺失指标显示不可判定。

先改 Worker：写入 current_stage/step_id/started_at，增量消费 stdout/stderr 并维护有界日志缓冲，阶段完成即更新结果；防止长行和无换行输出无限占内存。随后扩展代理返回受控日志尾和版本，前端继续每 2–5 秒轮询即可，暂不需要 WebSocket 或终端组件。Elapsed 使用服务端时间戳，运行中 exit_code=null；无新日志不能被显示为任务失败，轮询断开要标为连接未知。

**Cancel 独立交付**：提出按发起人鉴权的 job cancel API，Worker 按 job 精确停止排队任务或整个进程组/执行容器，终态确认后才显示 cancelled。请求处理中显示 cancelling；超时未确认显示取消待确认。取消幂等，并处理与自然完成竞争；不停止其他任务或整个共享 Worker。继续保留总截止，聊天 Stop 文案与实验 Cancel 分开。完成前按钮不宣称具备取消能力。

### 31.3 Session 从本地合并升级为服务端权威

划分三类数据，复用现有 PostgreSQL 与 LangGraph，不自研第二套 Agent 执行引擎：

| 数据 | 权威位置与用途 |
| --- | --- |
| 会话产品状态 | Nexus 域：owner、title、mode、course_id、pin、version、timestamps；附件/产物/run 引用。localStorage 只作用户隔离缓存，展开折叠等设备偏好可继续本地 |
| 长任务可见记录 | Nexus 域：session/turn/run/job 关联与最小事件投影；支持换设备恢复、状态查询和前端回放 |
| Agent 续跑状态 | LangGraph checkpoint：服务端控制执行恢复；与产品事件投影分开，不把前端历史回放当作重新执行 |

每个事件含 event_id、run_id、seq、type、occurred_at、status 和经过白名单裁剪的 payload；记录 Tool 开始/结束/错误、阶段、耗时、错误码与资源标识。保留可定位的证据和 Artifact 引用，不持久化完整 Prompt、模型思维或原始 Tool 参数/结果。日志尾独立短期保留，课程来源在恢复/下载时重新鉴权，不因为记住 course_id 而恢复权限。

会话元数据以服务端 version 做并发更新；本地缓存迁移只能在本人登录后导入已校验偏好，不能覆盖较新服务端值或把本地 toolEvents 当成真实审计。按 owner/session 查询快照与游标事件（断线重复投递按 event_id 去重），刷新/换设备先恢复 run/job 关联，再查询权威 job 快照并恢复轮询；严禁重新提交实验来“恢复”。尚未完成的历史任务若无可核查关联，显示旧版过程不可恢复，不能凭回答生成 Trace。

Worker 当前 `_jobs` 是进程内状态；因此仅持久化前端事件不保证 Worker 重启可恢复。需配套持久化作业快照并对账执行实例，无法确认仍在运行时标记 interrupted/unknown，不能伪造续跑或自动重放有副作用的命令。事件追加与任务启动/终态通知需具备幂等键及重试/对账机制，避免产生无归属实验。同步附件、事件、checkpoint 和对象保留/删除策略。

### 31.4 推进次序与验证

1. **近期并行范围（工作划分，不自动启动多 Agent）**：图片传模设计独立于 Console；Console 的实时状态/日志与 Session 的元数据/run-job 绑定可同步设计，但使用同一 run/job 标识契约。
2. **比赛体验补齐**：先保留 job 关联和刷新恢复查询，再交付阶段、耗时、日志尾、指标；Cancel 作为需 Worker 支持的完整小闭环单独验收。无需等待完整事件回放或 Sandbox A/B。
3. **长任务基础**：服务端元数据权威、最小事件持久化、游标恢复和 Worker 重启对账，随后接 Todo/Subagent 产品状态；这些是长任务产品建设方向，不把当前 MVP 误写成最终产品。
4. **验收样例**：运行中持续可见新日志；缓存命中/未实现 B 阶段诚实显示；换设备恢复 mode/course/pin/job；断线重连无重复事件、无重复执行；跨用户拒绝；取消后无残留子进程且不影响其他 job；Worker 重启显示真实恢复/中断状态；日志脱敏与到期清理。当前仅提出方案，未改变代码或上线状态。
