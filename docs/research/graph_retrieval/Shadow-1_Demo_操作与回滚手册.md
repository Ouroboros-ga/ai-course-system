# Shadow-1：本地可见检索与课程图谱 Demo 操作与回滚手册

## 1. 定位与边界

这是仅用于答辩录屏、调试和 V1/V2 观察的本地 Shadow-1 演示：

- R2 真实执行冻结的 `BM25 + 本地 BGE Dense + RRF`；不调用真实 LLM、向量服务、生产数据库或 R3。
- 前端复用已有 `graph-browser` 的 `GraphCanvas`，展示冻结 `GraphSnapshot` 中当前课程的 `accepted` 结构边；不做 GraphRAG 或图扩展检索。
- 检索命中保留 `course_id`、PPT 页码、`block_id`、Research Evidence ID 与 citation key。点击 Citation 只显示真实冻结定位坐标，不伪造 PPT 图片渲染。
- `Reviewed Silver v0.2` 是研究演示素材，不是 Human Gold。页面和接口均标注“实验回答，拒答校准尚未完成”。
- V1 聊天/文档链路、R3、课程脚本/进度/掌握度/记忆模块均不被调用或修改。V1 对照只能由操作者粘贴已有结果，演示不会自动调用 V1。

默认配置是 `v1_only`。只有开发、测试或 demo 环境才可显式开启可见演示；production 环境会强制降级为 `v1_only`。

## 2. 启动配置

后端在独立终端中启动。`AI_COURSE_SKIP_STARTUP_SIDE_EFFECTS` 避免演示启动触发数据库初始化、建表或迁移。

```powershell
Set-Location E:\smartcarb\ai-course-system\backend
$env:AI_COURSE_SKIP_STARTUP_SIDE_EFFECTS = '1'
$env:DEMO_RETRIEVAL_ENVIRONMENT = 'development'
$env:DEMO_RETRIEVAL_MODE = 'demo_compare' # 或 demo_shadow_visible
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

前端在另一终端启动：

```powershell
Set-Location E:\smartcarb\ai-course-system\frontend
$env:VITE_ENABLE_RETRIEVAL_DEMO = 'true'
npm.cmd run dev
```

以管理员身份登录后访问 `/demo/retrieval`。前端 flag 关、后端 `v1_only`、非 demo 安全环境、或点击页面回滚按钮时，页面显示明确的关闭状态；查询、课程、图谱等可见接口返回 `503 / DEMO_SHADOW_DISABLED`。状态接口保留只读响应，以便页面解释为什么被关闭。

本地 BGE 权重位于研究运行目录，首次载入可能比后续查询慢；不得把它替换为联网模型或向量服务。

## 3. 录屏/截图检查清单

按以下顺序录制可完整说明演示边界和真实运行证据：

1. 未设置 `VITE_ENABLE_RETRIEVAL_DEMO` 时打开页面，显示“前端 Demo Flag 未启用”。
2. 设置后端 `DEMO_RETRIEVAL_MODE=v1_only`，刷新页面，显示关闭状态和 V1 未修改说明。
3. 切换为 `demo_compare` 后重启后端，展示顶部“实验模式”与 `demo_compare` 状态。
4. 选择一个课程和预设问题，运行 R2；展示课程过滤、BM25、本地 Dense、RRF、Evidence/Citation closure 的实际 trace。
5. 展示命中行中的课程、PPT 页码、block、Evidence/Citation；点击一个 Citation，展示定位面板中的相同页码、block 与 citation key。
6. 展示“确定性课程图谱快照”：节点可选择，边列表只包含 `CONTAINS`、`GROUNDED_BY`、`MAPPED_TO`、`NEXT` 等 accepted 结构关系，并说明没有执行 R3/GraphRAG。
7. 可选：粘贴一段操作者已经取得的 V1 输出，展示“operator supplied V1 reference”，并说明演示没有自动调用 V1。
8. 展示运行元数据：P50/P95、BGE revision、权重 SHA、R2 配置 SHA；再点击“一键回退 v1_only”，刷新或再次查询时展示清楚的关闭状态。

## 4. 一键回滚与进程外回滚

页面的“一键回退 v1_only”只修改当前后端进程内的 demo override；它不会修改任何 V1 代码、数据或配置。适合录屏现场立即关停。

若需重启后持续关闭，停止演示进程并以下列配置重新启动：

```powershell
$env:DEMO_RETRIEVAL_MODE = 'v1_only'
```

再取消前端 `VITE_ENABLE_RETRIEVAL_DEMO` 并重启 Vite，可使入口本身不可见。演示运行记录仅写入被 Git 忽略的 `research/product1_graph_retrieval/demo_runs/`，不使用 ORM、迁移或生产数据库。

## 5. 已知风险与禁止解读

- 当前 Silver test 报告中 R2 的无答案误答率为 `1.0000`；这说明 BM25/Dense/RRF 尚无可用的拒答阈值或校准器。页面只能展示 Evidence-led 文本摘录，不能把它称为已验证问答准确率；该数字也不是 Human Gold 指标。
- Reviewed Silver 不可替代 Human Gold；不能由演示页面推导正式 Recall、MRR、拒答率或“优于 V1”的结论。
- 该演示不证明知识图谱检索优于 BM25/Dense。图谱仅用于可解释浏览和绑定验证。
- 如本地模型不可用，接口返回 `abstain / demo_provider_unavailable`，保留操作者提供的 V1 参考文本，且不自动退回调用 V1。

## 6. 验证记录

- Shadow-1 后端门控、主应用管理员拒绝、回滚端点、错误隔离、Citation/R3 约束及既有 feature flag：35 项 pytest 通过。
- 前端默认关闭、Citation/GraphSnapshot 契约：4 项 Node 测试通过；Vite production build 通过。
- 本地真实 R2 试跑：`EE101` 返回 50 个命中；BGE revision 为 `7999e1d3359715c523056ef9478215996d62a620`，R2 配置 SHA 为 `2bee391da84795bc7ea03387b2da154541c5bea644168c94fe277f65c1f327d7`，`r3_graph_expansion_called=false`。
- 通过实际挂载的本地 FastAPI 应用验证：`demo_compare` 返回 4 个课程；`EE101` GraphSnapshot 为 674 个节点、478 条 accepted 边；真实 R2 查询 HTTP 200，返回 50 个同课程命中。命中数量不是准确率指标。
