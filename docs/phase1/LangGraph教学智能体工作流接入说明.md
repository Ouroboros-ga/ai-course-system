# LangGraph 教学智能体工作流接入说明

> **归档说明(2026-07-30)**:本文档反映的是 Agent 架构迁移前的接入说明,
> 部分语义已与当前代码不一致:
> (1) 文中"应用默认不构造运行时,返回 503"已不成立——
> `backend/app/platform/agents/bootstrap.py` 在 `TEACHING_AGENT_MODE=enabled`
> 且 LLM 配置齐全时已注入真实运行时;
> (2) 文中测试命令 `unittest discover -s backend\tests\agents` 已失效,
> 测试目录在迁移中已重组,实际入口在 `backend/tests/` 根目录与各子目录;
> (3) 未反映 `edu/`、`prep/`、`coding/` 三目录已物理分离。
> 本文保留仅用于历史追溯,**不再作为当前实现依据**。
> 当前事实以 [AGENTS.md](../../AGENTS.md) §2.2 与 §5、
> `backend/app/platform/agents/` 实际代码为准。

## 已实现的边界

新增 `backend/app/platform/agents/`，以 LangGraph `StateGraph` 编排单一教学智能体。它维护结构化 `TeachingState`，而不是只拼接聊天记录；节点只通过 Port 调用领域能力，不直接访问 ORM、数据库、图数据库或系统命令。

主链为：请求范围校验 → 意图/候选概念 → 知识点定位 →（有概念时）学生状态与图谱上下文 → 课程证据 → 代码沙箱上下文 → 确定性教学策略 → 生成 → 引用校验 → 学习事件与轨迹记录。

策略由 `policies/teaching_action.py` 确定性决定。LLM 仅通过 `TeachingLLMPort` 负责意图、候选概念和教学语言；它不能更新学生状态、选择推荐优先级或改写图谱。

## 运行时与安全

新 API 为 `POST /api/v1/teaching-agent/respond`。应用默认不构造运行时，因此会返回 `503 TEACHING_AGENT_NOT_CONFIGURED`；不会影响现有 `/chat` 或其他 V1 路由。

应用组合根必须显式提供全部 Port，尤其是课程/学生作用域校验、只读学生状态、推荐、沙箱、事件和 LLM。`build_course_sidecar_runtime()` 只能复用已有隔离 R2 课程侧车作为图谱/证据端口；它不会自行启用侧车，也不会把研究侧车接入 V1。

LLM 不可用时返回明确 503，不伪造回答。图谱、学生状态、检索、推荐、沙箱或事件服务不可用时，工作流记录降级和 trace；检索无证据时删除引用，避免伪 Citation。

## 验证

使用标准库测试入口，未调用真实 LLM、数据库、图服务或代码沙箱：

```powershell
$env:PYTHONPATH = 'backend'
.\.venv\Scripts\python.exe -m unittest discover -s backend\tests\agents -p 'test_*.py' -v
```

覆盖普通知识问答、弱前置、重复错误、证据不足、代码上下文、检索失败降级、作用域整批拒绝、LLM 不可用、默认 503 与显式运行时注入。

## 后续接入门槛

真实 M3 接入前，需由各领域 Owner 提供并审核：

1. 课程范围授权的 `ScopePort`；
2. 只读学生状态与弱前置查询；
3. 已验收的图谱与 Evidence 检索服务；
4. 受控代码沙箱和 append-only 事件记录器；
5. 支持结构化输出、版本记录与超时的 `TeachingLLMPort`。

在这些 Port 注入前，新路由保持不可用；这不是功能缺失，而是防止工作流绕过领域权限和证据边界。

## KG-MEST Shadow 端口接入

`backend/app/platform/agents/tools/kg_mest_shadow.py` 提供
`KGMetShadowReportStudentModelingPort`。它是正式系统与研究算法之间的
唯一 StudentModelingPort 边界：只接收已生成、已审核的 KG-MEST Shadow
报告，不导入研究模块、不读取数据库、不执行 bundle、不写学生状态。

端口在构造时绑定一个学生和一个课程。请求超出该范围时返回未知状态与
空弱前置集合，教学策略将进入诊断，而不会复用别人的状态。报告中的：

- `observed_performance_score` → `mastery_score`；
- 八维中的错误风险、提示依赖、迁移 → 既有教学策略字段；
- `review_confirmed_weak_prerequisite` → 既有弱前置决策；
- 证据引用、原因码、策略版本和数据版本 → Agent trace。

应用组合根可显式调用 `build_kg_mest_shadow_sidecar_runtime()`，并将返回
runtime 注入 `app.state.teaching_agent_runtime`。该函数仍要求已有的课程侧车、
推荐、沙箱、事件和 LLM Port；不读取 bundle 路径、不自动打开路由、不影响 V1。
只有完成真实 Shadow 数据交接清单中的审批后，领域 Owner 才能进行这一次显式注入。

## 当前集成限制

后端正式环境为 `backend/.venv`，其中已有 `python-jose` 与 `sqlmodel`；
以 `AI_COURSE_SKIP_STARTUP_SIDE_EFFECTS=1` 导入 `app.main` 已通过。项目根
`.venv` 与 PaddleNLP 研究环境不是主后端解释器，不能用于判断主应用依赖。

现有 `RuleBasedMasteryProvider` 的规则包含参与度/提问类信号，和当前双因子
研究中“提问数量不能直接加分”的边界不一致。它没有被注入 TeachingAgent。
KG-MEST 端口只接收符合冻结证据契约的只读 Shadow 报告。
