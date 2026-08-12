# ResearchAgent HarnessEngineer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有 arXiv P0 升级为可持久化、可恢复、可观测的 ResearchAgent 科研工作台，使 Prompt、Todo、工具选择、上下文、Notepad、压缩、子任务作用域和记忆都进入真实 LangGraph 状态机与 Course Access 边界。

**Architecture:** 保留 `backend/app/platform/agents/research/` 的物理隔离，以一个条件路由 LangGraph 编排 Harness；业务状态通过 Research Workspace Port 持久化，外部能力通过白名单 Tool Registry 注入。PostgreSQL 18 + pgvector 是部署目标，SQLite 仅保留为本地 Demo/测试兼容；所有外部论文继续属于补充 Research Evidence Domain。

**Tech Stack:** Python 3.12、FastAPI、SQLModel/SQLAlchemy、Alembic、LangGraph 0.6、PostgreSQL 18、pgvector、Vue 3、Vite。

## Global Constraints

- 每个 Research Tool 在执行点再次校验 `course.question.ask`，不从 `User.role`、课程 owner 或前端状态推断权限。
- 不持久化完整系统 Prompt、密钥或内部完整 LLM trace；只记录 prompt 版本/hash、节点、耗时、状态和错误码。
- 外部研究结果只作补充参考，不写入掌握度、推荐、正式 Course Evidence 或课程图谱。
- 不在主应用执行用户命令；代码执行仍只能走 Judge0/独立 Reproduction Worker。
- 新表只由 Alembic 创建；应用启动不得调用 `create_all`。
- 自动化测试不得调用真实付费 LLM、真实私有仓库或真实学生数据。

---

### Task 1: 固化开源选型与可勾选交付清单

**Files:**
- Create: `docs/phase1/ResearchAgent_Harness_TODO.md`
- Modify: `docs/phase1/研究智能体整体架构与前端设计.md`

- [x] 审计现有 ResearchAgent 图、Port、API、页面、测试与共享 Runtime。
- [x] 调研 LangGraph persistence/interrupt、Deep Agents、Open Deep Research、langgraph-bigtool、LangMem 与 pgvector 官方实现。
- [x] 记录“复用模式而非引入第二套 Agent 平台”的适配结论。

### Task 2: Harness 纯逻辑内核（测试先行）

**Files:**
- Create: `backend/tests/research/test_harness_prompt_context.py`
- Create: `backend/tests/research/test_harness_tooling.py`
- Create: `backend/app/platform/agents/research/harness/prompting.py`
- Create: `backend/app/platform/agents/research/harness/context.py`
- Create: `backend/app/platform/agents/research/harness/tooling.py`
- Create: `backend/app/platform/agents/research/harness/reliability.py`

- [ ] 先写失败测试：模板变量缺失/未授权变量、相关性筛选、分块、自动压缩。
- [ ] 实现角色模板 + 任务模板 + 白名单变量注入，运行态只保留 prompt hash/version。
- [ ] 实现上下文预算、窗口裁剪、相关性评分、重叠分块与确定性摘要降级。
- [ ] 先写失败测试：工具意图匹配、白名单交集、权限拒绝、超时/重试/熔断。
- [ ] 实现 Tool Registry、动态选择器与可靠执行器。

### Task 3: Research Workspace 持久化与 pgvector（测试先行）

**Files:**
- Create: `backend/tests/research/test_workspace_store.py`
- Create: `backend/app/models/research_workspace_model.py`
- Create: `backend/app/platform/agents/contracts/research_workspace.py`
- Create: `backend/app/platform/agents/providers/research/workspace.py`
- Modify: `backend/app/models/database.py`
- Create: `backend/alembic/versions/20260811_1500_0047_research_harness_workspace.py`

- [ ] 先写失败测试：workspace 隔离、Todo 排序/状态机、Notepad 版本、scope 中断/恢复。
- [ ] 实现 Workspace/Todo/Note/Scope/Memory 的 SQLModel 与 session-scoped Port。
- [ ] 实现短期摘要与长期记忆写入；配置真实 embedding provider 时写 pgvector，失败时明确降级为关键词检索。
- [ ] 增加 PostgreSQL `vector` 扩展、向量列与可回滚迁移；SQLite 空库迁移仍可执行。
- [ ] 验证 migration upgrade/downgrade/upgrade 可重入。

### Task 4: 真实条件路由 LangGraph

**Files:**
- Create: `backend/tests/research/test_harness_workflow.py`
- Modify: `backend/app/platform/agents/research/state.py`
- Modify: `backend/app/platform/agents/research/workflow.py`
- Modify: `backend/app/platform/agents/research/composition.py`
- Modify: `backend/app/platform/agents/research/profile.py`

- [ ] 先写失败测试，锁定节点图与 `START → scope → hydrate → prompt → select → context_guard → 条件工具分支 → persist → response`。
- [ ] 为 literature/todo/notepad/memory/scope 建立真实节点与条件路由，保留 EvidenceGate。
- [ ] 实现子 scope 的独立 context summary、interrupt/resume 状态转换和 active scope 切换。
- [ ] 所有节点输出结构化 trace；外部工具通过 retry/timeout/circuit breaker 执行。
- [ ] profile 只声明实际接通的白名单工具和能力。

### Task 5: 装配、API 与契约

**Files:**
- Modify: `backend/app/platform/agents/bootstrap.py`
- Modify: `backend/app/platform/agents/providers/container.py`
- Modify: `backend/app/api/v1/endpoints/research_agent.py`
- Modify: `backend/tests/test_research_agent.py`
- Create: `backend/tests/research/test_harness_api.py`

- [ ] 装配真实 workspace、embedding（若配置）、run event 与 Research Harness providers；启动不得触网。
- [ ] 新增 workspace snapshot、run、Todo、Note、Memory、Scope API，保持 capabilities/search 兼容。
- [ ] API 与每个工具执行点双重 Course Access 检查。
- [ ] 响应不泄露完整 Prompt/内部 trace/密钥，只返回安全的 graph route、tool 名与状态摘要。

### Task 6: 科研工作台前端

**Files:**
- Modify: `frontend/src/api/research_agent.js`
- Modify: `frontend/src/app/pages/course/research/ResearchWorkspacePage.vue`
- Create: `frontend/src/app/pages/course/research/components/ResearchTodoPanel.vue`
- Create: `frontend/src/app/pages/course/research/components/ResearchNotepadPanel.vue`
- Create: `frontend/src/app/pages/course/research/components/ResearchMemoryPanel.vue`
- Create: `frontend/src/app/pages/course/research/components/ResearchScopePanel.vue`

- [ ] 接入 workspace snapshot 与 Harness run；显示 active scope、上下文预算、所选工具与降级状态。
- [ ] Todo 支持创建、更新、优先级排序与状态跟踪。
- [ ] Notepad 支持持久化读写；Memory 支持写入与检索；Scope 支持创建、中断、恢复和切换。
- [ ] 遵循 `design.md`：三层滚动、Academic Ink token、单一主操作、全部使用 `SfxButton`。
- [ ] Browser 验收可见入口、页面身份、交互、Console/Network、响应式和截图。

### Task 7: 文档、注释、自审与验证

**Files:**
- Create: `backend/app/platform/agents/research/README.md`
- Modify: `README.md`
- Modify: `docs/phase1/研究智能体整体架构与前端设计.md`
- Modify: `docs/phase1/功能现状审计表.md`
- Modify: `docs/DOCUMENTATION_INDEX.md`
- Modify: `docs/phase1/ResearchAgent_Harness_TODO.md`

- [ ] 为安全边界、Port 契约、状态转换、压缩算法和向量降级添加意图型注释。
- [ ] 同步实际完成/降级/未接通边界和开源来源适配说明。
- [ ] 运行 targeted pytest、migration smoke、Ruff、前端 build/契约测试、`git diff --check`。
- [ ] 做一次全量范围内自审，逐项核对需求矩阵与 Todo；未验证项保持未完成。

