# ResearchAgent HarnessEngineer Todo

> 状态：执行中（2026-08-11）  
> 变更原因：现有 ResearchAgent 只有 arXiv 元数据检索的四节点线性图，尚不具备可持久化科研工作台和 Harness 能力。  
> 详细步骤：[实施计划](../superpowers/plans/2026-08-11-research-agent-harness.md)

## 0. 已完成的基线与本轮决策

- [x] 保留 P0 的 Course Access 双门、PII 脱敏、arXiv 节流/缓存、metadata-only EvidenceGate。
- [x] 核对现有图：它是真实 LangGraph，但仅 `scope_validator → literature_search → evidence_gate → response`，不满足本轮条件路由与 Harness 要求。
- [x] 核对 checkpoint：共享层当前只有 Port/Null 实现，不能据此宣称可恢复。
- [x] 决定复用 Deep Agents 的 middleware 分层思想、Open Deep Research 的研究/压缩分离、langgraph-bigtool 的“先检索工具再注入”模式；不引入第二套 Agent 平台。
- [x] PostgreSQL 目标定为 18，向量能力使用 pgvector；SQLite 仅用于本地 Demo 与测试兼容。

## 1. HarnessEngineer 内核

- [ ] 动态 Prompt：角色/任务模板组合、变量白名单、缺失变量 fail-closed、版本/hash 审计。
- [ ] Todo：创建、更新、优先级排序、状态跟踪、作用域隔离。
- [ ] 动态工具：意图匹配、上下文相关度、白名单与课程能力交集后注入。
- [ ] 上下文：窗口预算、相关性筛选、重叠分块、近期保留。
- [ ] Notepad：课程/用户/workspace/scope 四级隔离的持久化读写与版本。
- [ ] 压缩：超限自动摘要；摘要器不可用时确定性提取式降级并明确标记。
- [ ] 作用域：子任务独立上下文、active scope 切换、中断、恢复、完成状态机。
- [ ] Memory：短期摘要、长期记忆、真实 embedding Port、pgvector 存储/相似检索与关键词降级。

## 2. LangGraph 与工程治理

- [ ] 将固定线性图升级为具备条件边的完整 Harness 图，并为每个分支提供真实实现。
- [ ] 工具白名单 + API/Tool 双重 Course Access；不开放主机 shell。
- [ ] 外部工具具备超时、有限重试、指数退避与熔断。
- [ ] 结构化日志、节点 trace、run event 与基础计数/耗时指标。
- [ ] Provider/Port 解耦 embedding、存储、论文检索和执行环境。

## 3. 数据与 API

- [ ] 新增 Research Workspace、Todo、Note、Scope、Memory 模型。
- [ ] 新增 Alembic 0047：空库建表、PostgreSQL pgvector、SQLite 兼容、downgrade。
- [ ] 新增 workspace/run/todo/note/memory/scope API，并保留旧 capabilities/search 契约。
- [ ] API 响应只暴露安全状态摘要，不返回完整 Prompt、密钥或内部完整 trace。

## 4. 前端工作台

- [ ] 展示当前 workspace、active scope、上下文预算、动态工具与降级状态。
- [ ] Todo/Notepad/Memory/Scope 均有可操作面板和 loading/empty/error 状态。
- [ ] 保留论文检索与来源核验，补充研究命令入口而非改成聊天消息墙。
- [ ] 完成 Browser 的真实可见性、交互、Console/Network 与响应式验收。

## 5. 文档与验证

- [ ] 新增模块 README，更新架构文档、根 README、文档索引与功能审计表。
- [ ] 提供单元、图路由、API、权限隔离、迁移、前端构建与浏览器验收用例。
- [ ] 完成代码注释校准、diff 自审、Ruff、pytest、Vite build、`git diff --check`。

## 当前诚实边界

- 已接通：P0 arXiv metadata-only 检索。
- 本轮执行中：Harness、Workspace、pgvector、API 与前端面板。
- 不在本轮伪装完成：Semantic Scholar/Crossref 多源检索、完整仓库 Reproduction Worker、论文全文证据抽取和正式学术综述生成。
