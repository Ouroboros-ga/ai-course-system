# CodeNexus 转型落地计划（实施路线图）

> **基线**：2026-09-03，Nexus Runtime P0 本地实现完成（18 测试通过、本地启动验证通过）
> **决策依据**：[2026-09-03\_CodeNexus转型实施决策.md](2026-09-03_CodeNexus转型实施决策.md)
> **状态**：本计划随实施进度持续更新；已完成项标记 ✅，进行中标记 🔄，待启动标记 ⏸️
> **当前进度（2026-09-04）**：S0 ✅ / S1 ✅ / S2 ✅ 均已完成并验收；当前处于 **S3 下线**（待启动）
> 与 **P1-C2/C3**（会话列表 API + 前端切换）、**nanoGPT 真实执行复测** 的待办区间（上述收尾项已并入
> [CodeNexus_P2开发计划.md](CodeNexus_P2开发计划.md) 的 M0 里程碑）。详见 §九 进度追踪。

***

## 一、总体原则

1. **比赛演示优先**：S2（切换期）之前旧 `/research` 不做任何行为变更，保证随时可回退到旧链路演示。
2. **里程碑驱动**：按 Nexus 功能验收节点推进（不用日历日期），每阶段有明确触发条件、交付物与回退方式。
3. **资源约束**：服务器为单一 4C8G 宿主机（Backend 主栈 + Judge0 + SearXNG + 未来 Repro Worker 均同机容器级隔离），Repro Worker 与 Nexus 部署需预留资源配额。
4. **可追溯性**：每批变更记录证据（测试输出、手工验收截图、日志片段）；失败时保留失败语义，不假造成功。
5. **数据安全**：`research_*` 表保留不 drop（按既有 retention 自然过期）；Nexus 数据分域；复现代码只经 Repro Worker 受限执行。

***

## 二、四阶段路线图

按决策文档 §6 设计，四阶段时间表如下：

| 阶段          | 触发条件                         | 核心动作                                                                                                                     | 交付物                                 | 回退方式                   | 预计工作量 |
| ----------- | ---------------------------- | ------------------------------------------------------------------------------------------------------------------------ | ----------------------------------- | ---------------------- | ----- |
| **S0 兼容冻结** | —                            | `research/` 标 Legacy、文档同步                                                                                                | ✅ 已完成（2026-09-03）                   | —                      | —     |
| **S1 双轨期**  | Nexus P0 本地可运行               | 后端 `/api/v1/nexus/*` 路由上线、前端新增 Nexus 入口（主导航移除科研工作台，深链保留）、旧 `/research-agent` 与 `/web-research` 加 `Deprecation: true` 响应头 | Backend 路由注册 + 前端单一 Nexus 页面 + 导航调整 | 前端导航恢复一个提交             | 3-5 天 |
| **S2 切换期**  | Nexus 真实链路手工验收通过（演示脚本完整走通一次） | 删除前端四面板页面与 `/research` API client、后端 `/research/*` 返回 `410 Gone` + 迁移说明 JSON                                             | 前端四面板代码删除 + Backend 410 响应          | 前后端各 revert 一个提交       | 1-2 天 |
| **S3 下线**   | S2 稳定 ≥ 1 迭代                 | 删除 Backend `/research` 路由注册与 service；`providers/research` 被 Nexus 真实调用部分迁入 `nexus/`，其余随模块删除；`research_*` 表保留不 drop       | Backend 代码清理 + Provider 迁移          | git revert；表数据未动，天然可回退 | 2-3 天 |

***

## 三、S1 双轨期实施细则

**触发条件**：✅ 已满足（Nexus Runtime P0 本地可运行，单测 18/18、健康检查 200、fail-closed 验证通过）

**实施状态（2026-09-03）**：代码侧已完成（S1-B2/B3/B4 + S1-F1/F2/F3/F4）；
S1-B1（服务器部署）与 S1-V1（真实链路验收）仍待授权与 DeepSeek Key。

### 3.0 开工后对本计划的三处事实修正

计划初稿基于假设路径，实施时核对仓库后修正如下——**以本节为准**：

| 计划初稿                           | 仓库实际                                                             | 影响                          |
| ------------------------------ | ---------------------------------------------------------------- | --------------------------- |
| 旧接口前缀 `/api/v1/research/*`     | `/api/v1/research-agent/*`，另有 `/api/v1/web-research/*`           | S1-B3 需标注两个前缀；S2 的 410 也是两个 |
| 前端科研工作台在 `/app/research/*`（全局） | 在**课程内** `/app/course/:id/research`（`ResearchWorkspacePage.vue`） | S2-F1 删除范围随之改变              |
| S1-F3 需"移除科研工作台入口"             | 该入口已于 2026-08-20 在 `CourseLayout.vue` 注释隐藏                       | S1-F3 实际只剩"新增 Nexus 入口"     |

另有一项实施发现：**前端此前没有任何 SSE 消费代码**（学习页的"流式输出"是
`setTimeout` 客户端打字机模拟，后端也无对应流式接口）。`api/nexus.js` 是本仓库
第一个真实 SSE 消费者，因此 `request.js` 需导出 `generateSignature` 供 fetch
链路复用签名（axios 拿不到 `ReadableStream`）。

### 3.1 后端任务（Backend 路由与反代）

| 任务 ID   | 任务内容                              | 输入                                           | 输出                                                                                                                                                                                                                                                                                     | 验收标准                                                                                              | 阻塞依赖                           |
| ------- | --------------------------------- | -------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- | ------------------------------ |
| S1-B1 ✅ | Nexus Runtime 服务器部署               | `nexus/` 完整代码 + `.env`（含 `DEEPSEEK_API_KEY`） | systemd 服务 `nexus-runtime.service` 运行于 47.99.97.154:8300                                                                                                                                                                                                                               | `curl http://127.0.0.1:8300/health` 返回 200；`systemctl status nexus-runtime` 显示 `active (running)` | ~~需用户授权部署~~ 已授权并完成（2026-09-03） |
| S1-B2 ✅ | Backend 反代 `/api/v1/nexus/*`      | —                                            | `backend/app/api/v1/endpoints/nexus_proxy.py`：`/health`、`/chat`、`/chat/stream`（SSE 逐块中继）；`X-Forwarded-*` + `X-Nexus-User-*` 身份头；到 Runtime 用内部服务令牌而非用户 JWT；非流式 60s、流式读超时 300s                                                                                                           | 三路由已注册；假 Runtime 真实 HTTP/SSE 链路实测通过                                                               | 无（代码不依赖部署）                     |
| S1-B3 ✅ | 旧接口加 Deprecation 头                | —                                            | `backend/app/core/deprecation_middleware.py`：`/api/v1/research-agent/*` 与 `/api/v1/web-research/*` 响应加 `Deprecation: true` + `Link: rel="successor-version"` + `X-Deprecation-Phase/Plan`。用中间件而非路由依赖，使 `HTTPException`/422 等框架生成的响应也带头                                                 | 实测含 `Deprecation: true`；旧链路状态码与响应体零变更                                                             | 无                              |
| S1-B4 ✅ | Backend 单测                        | S1-B2/B3 代码                                  | `backend/tests/test_nexus_proxy.py` 17 个测试：透传、身份不外泄、SSE 中继、未配置/不可达/超时/上游错误码/非 JSON 上游、鉴权、入参校验、Deprecation 标注不污染 Nexus 路由                                                                                                                                                               | 17/17 通过；`test_research_agent.py`+`test_web_research.py` 22/22 行为不变                               | S1-B2/B3                       |
| S1-B5 ✅ | Nexus 使用权限门控（决策 D10，2026-09-03 补） | 新增 `platform.nexus.use` + 迁移 0068（含全量默认授权回填） | `nexus_proxy.py` 三端点改走 `require_nexus_use`（403 `NEXUS_PERMISSION_DENIED`，不触达 Runtime）；**默认授予所有用户**（注册/登录/泛雅同步经 `ensure_default_nexus_grant` 自动授予，显式撤销优先、不被复活）；授权入口 `GET/POST/DELETE /api/v1/admin/users/{id}/platform-permissions`（软撤销+审计+防 ADMIN 自我提权）；前端 `canUseNexus` 导航门控 + 页面无权限态 | `test_nexus_proxy.py` 20/20、`test_platform_permissions.py` 10/10、关联回归 29 通过、前端契约 88/88、build 通过   | S1-B2                          |

**`Sunset`** **头的处理**：计划初稿写"日期 TBD"。转型按里程碑而非日历推进，编造到期日
会误导调用方，因此实现为配置项 `DEPRECATION_SUNSET_DATE`，**默认留空即不发送该头**；
日期确定后配置即生效，无需改代码。

**资源配额设计**：Nexus Runtime 初期配额建议 1C2G（uvicorn 单进程 + InMemorySaver），为 Repro Worker 预留 1C2G，主栈与 Judge0 共享剩余 2C4G。实测若内存不足可临时调低 paddleocr 限制或按需重启。

### 3.2 前端任务（Nexus 单一入口）

| 任务 ID   | 任务内容          | 输入                   | 输出                                                                                                                                                                                                                                  | 验收标准                                                        | 阻塞依赖     |
| ------- | ------------- | -------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- | -------- |
| S1-F1 ✅ | Nexus AI 页面骨架 | `design.md` 令牌 + SSE | `frontend/src/app/pages/nexus/NexusPage.vue`：对话历史 + 输入区 + 工具调用折叠卡片（token/tool\_call/tool\_result/done）；失败以真实错误码呈现在该轮内                                                                                                               | 构建通过（产出 `NexusPage` chunk）；oxlint 0 error                   | 无        |
| S1-F2 ✅ | Nexus API 客户端 | 反代路由                 | `frontend/src/api/nexus.js`：`getNexusHealth()`、`sendNexusMessage()`、`streamNexusMessage()`。流式用 **fetch + ReadableStream**（非 `EventSource`：后端流式是 POST，且 `EventSource` 不能带 `Authorization`），签名复用 `request.js` 导出的 `generateSignature` | 契约测试锁定路径与后端路由一一对应                                           | S1-B2    |
| S1-F3 ✅ | 主导航调整         | —                    | `PrimaryNav.vue` 一级导航新增"Nexus AI"（`/app/nexus`，`BrainCircuit` 图标）；`router.js` 注册 `app-nexus` 路由。科研工作台入口早已隐藏（见 §3.0），深链 `/app/course/:id/research` 保留                                                                                | 契约测试断言导航含 Nexus、不含科研入口、旧路由仍在                                | S1-F1    |
| S1-F4 ✅ | 前端契约测试        | S1-F2/F3             | `apiContracts.test.cjs` 新增 9 条：路径对应、`allowFlatResponse`（透传响应无信封）、fetch/SSE 与签名复用、错误码上抛、SfxButton 规范、导航与路由、S1 未改 410                                                                                                                 | `node --test src/api/__tests__/apiContracts.test.cjs` 87/87 | S1-F2/F3 |

**UI 设计约束**：

- Nexus 页面遵循 `design.md` §2（三层滚动）：固定顶栏（输入框）+ 可滚动对话区 + 底部操作（可选）。

- SSE 消息卡片使用 `--surface-2`（`#0F131C`）+ 琥珀 accent（`#E9A568`）工具调用高亮。

- 输入框优先使用 `SfxButton.vue`（`design.md` §9），避免原生 `<button>`。

- 对话历史按 session\_id 分组（P0 阶段会话重启即清，UI 提示"当前会话仅保留至服务重启"）。

### 3.3 真实链路冒烟（S1 → S2 门槛）

| 任务 ID | 任务内容          | 输入                 | 输出                             | 验收标准                                                                                   | 阻塞依赖                   |
| ----- | ------------- | ------------------ | ------------------------------ | -------------------------------------------------------------------------------------- | ---------------------- |
| S1-V1 | Nexus 端到端手工验收 | 部署完成的 Nexus + 前端页面 | 演示脚本（见下文 §3.4）完整走通一次，截图 + 日志归档 | 6 个用例至少 4 个成功（Web Search + arXiv 必成功，nanoGPT 复现规划必成功，复现执行可返回 UNAVAILABLE）；失败用例保留真实错误日志 | S1-B1/B2 + S1-F1/F2/F3 |

### 3.4 S1 演示脚本（手工验收清单）

**前置条件**：

- 服务器 Nexus Runtime 运行中（`systemctl status nexus-runtime` active）

- 前端已部署最新版本（含 Nexus 入口）

- DeepSeek API Key 已配置且有余额

- SSH 隧道已建立（本地开发需连 SearXNG：`ssh -N -L 18888:127.0.0.1:8888 root@47.99.97.154`）

**用例清单**：

1. **健康检查**

   - 操作：`curl http://47.99.97.154/api/v1/nexus/health`

   - 预期：返回 200，`llm_configured: true`、`searxng_configured: true`

2. **Web Search 主通道**

   - 操作：前端 Nexus 页面输入"搜索一下 Transformer 模型的最新进展"

   - 预期：SSE 流显示 `tool_call: web_search` → `tool_result: {channel: "searxng", total: >0}` → 生成总结

3. **arXiv 论文检索**

   - 操作：输入"搜索 arXiv 上关于 GPT-2 的论文"

   - 预期：`tool_call: search_arxiv_papers` → 返回至少 1 条结果（含 arxiv\_id、title、authors）

4. **nanoGPT 复现规划**

   - 操作：输入"帮我规划一下 nanoGPT 的复现步骤"

   - 预期：`tool_call: plan_reproduction` → 返回 nanoGPT 预设（MIT License + 5 步命令）

5. **复现执行（预期 fail-closed）**

   - 操作：输入"执行 nanoGPT 复现"

   - 预期：`tool_call: run_reproduction` → 返回 `REPRO_WORKER_UNAVAILABLE`（Repro Worker 未实现）

6. **会话续聊**

   - 操作：同一 session 继续输入"刚才搜到的论文有哪些作者？"

   - 预期：Agent 能引用前文 arXiv 结果回答（InMemorySaver 生效）

**验收结果记录**：每个用例截图（前端消息流 + 浏览器 Network 面板 SSE 事件）+ Backend 日志片段（工具调用与结果）→ 归档至 `docs/phase1/验收记录/S1_Nexus真实链路_{日期}.md`。

### 3.5 S1 交付检查清单

- [x] Nexus Runtime systemd 服务运行中（`systemctl status nexus-runtime` active）— ✅ 2026-09-03 完成部署

- [x] Backend 反代路由注册（`/api/v1/nexus/{health,chat,chat/stream}`，假 Runtime 实测 200）

- [x] 旧 `/research-agent` 与 `/web-research` 响应含 `Deprecation: true` 头

- [x] 前端主导航显示"Nexus AI"，不显示科研工作台

- [x] 前端 Nexus 页面可输入消息并消费 SSE 流（假 Runtime 实测逐帧到达）

- [x] 演示脚本 6 用例至少 4 个成功 — ✅ **6/6 通过**（2026-09-03，验收记录归档：
  [验收记录/S1\_Nexus真实链路\_2026-09-03.md](验收记录/S1_Nexus真实链路_2026-09-03.md)）

- [x] Backend 单测（17/17）+ 前端契约测试（87/87）全绿

- [x] Nexus 使用权限门控落地（S1-B5，决策 D10：`platform.nexus.use` 默认授予所有用户 + 可按用户撤销 + 授权管理入口；测试 20/20 + 10/10 + 关联回归 29 + 契约 88/88）

- [x] 旧 research 深链仍可访问（`/app/course/:id/research` 路由保留）

***

## 四、S2 切换期实施细则（S1 稳定后）

**触发条件**：S1-V1 演示脚本完整走通一次（验收记录已归档）

### 4.1 前端任务（四面板删除）

| 任务 ID   | 任务内容                      | 输出                                                                                                                 | 验收标准                                         |
| ------- | ------------------------- | ------------------------------------------------------------------------------------------------------------------ | -------------------------------------------- |
| S2-F1 ✅ | 删除科研工作台四面板页面              | 删除 `frontend/src/app/pages/course/research/*`（ResearchWorkspacePage + Memory/Notepad/Scope/Todo 四面板，§3.0 修正后的真实路径） | 构建通过；`app-course-research` 路由从 bundle 移除     |
| S2-F2 ✅ | 删除 `/research` API client | 删除 `frontend/src/api/research_agent.js` 与所有调用方（无独立 webResearch client）                                             | 前端测试通过；无 import 残留                           |
| S2-F3 ✅ | 前端契约测试更新                  | "S1 保留深链"断言翻转为"S2 已删除"（含文件不存在检查）                                                                                   | `node --test apiContracts.test.cjs` 89/89 全绿 |

### 4.2 后端任务（410 Gone 响应）

| 任务 ID   | 任务内容                                                             | 输出                                                                                                                                                                                  | 验收标准                                                                           |
| ------- | ---------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| S2-B1 ✅ | `/research-agent/*`、`/web-research/*` 返回 410 Gone（§3.0 修正后的两个前缀） | `deprecation_middleware.py` 短路返回 `410 Gone` + JSON `{"error": "RESEARCH_API_RETIRED", "migration": "Use /api/v1/nexus/* instead"}` + `Link: successor`；**路由注册保留至 S3**（revert 即恢复双轨） | 线上 curl 两前缀均 410（见验收记录）                                                        |
| S2-B2 ✅ | Backend 测试更新                                                     | API 级测试翻转为 410 契约（service 层单测保留至 S3）                                                                                                                                                | `pytest test_nexus_proxy.py test_research_agent.py test_web_research.py` 42/42 |

### 4.3 S2 交付检查清单（✅ 全部通过，2026-09-03；实测路径见 §3.0 修正与

[验收记录/S2\_切换期\_2026-09-03.md](验收记录/S2_切换期_2026-09-03.md)）

- [x] 前端四面板代码已删除（`frontend/src/app/pages/course/research/` 目录已删除）

- [x] 前端 `research_agent.js` API client 已删除（无 import 残留，构建通过）

- [x] Backend `/research-agent/*` 与 `/web-research/*` 全部返回 410 + `RESEARCH_API_RETIRED` 迁移说明（中间件短路，线上实测）

- [x] 前后端测试全绿（backend 42/42、前端契约 89/89、build 通过）

- [x] 旧 research 深链路由已从 bundle 移除（前端）；直接 API 调用 410（线上实测）

**回退方式**：前后端各 `git revert` 一个提交（S2-F = `8255a4c7`，S2-B = `6635f106`）。

***

## 五、S3 下线实施细则（S2 稳定后）

**触发条件**：S2 稳定运行 ≥ 1 个迭代（建议至少 3 天无回退需求）

### 5.1 Provider 迁移评估

**迁移原则**：只迁移 Nexus 真实调用的部分，不做提前抽象迁移。

| Provider 模块                          | Nexus 是否调用                                                        | 迁移动作                                                       |
| ------------------------------------ | ----------------------------------------------------------------- | ---------------------------------------------------------- |
| `providers/research/paper_search.py` | ✅ 是（`nexus/tools/paper_search.py` 已复用同一 ArxivPaperSearchProvider） | 迁入 `nexus/src/nexus/providers/paper_search.py`，Backend 侧删除 |
| `providers/research/workspace.py`    | ❌ 否（Nexus P0 用 InMemorySaver，不持久化 workspace）                      | 随 S3-B1 删除，不迁移                                             |
| `providers/research/memory.py`       | ❌ 否（Nexus P0 无 memory 持久化）                                        | 随 S3-B1 删除，不迁移                                             |
| `providers/research/embedding.py`    | ❌ 否（Nexus P0 无向量检索）                                               | 随 S3-B1 删除，不迁移                                             |

**实际操作**：S3 阶段只需把 `backend/app/platform/agents/providers/research/paper_search.py` 迁入 `nexus/src/nexus/providers/`，其余三个 Provider 直接删除。

### 5.2 Backend 代码清理

| 任务 ID | 任务内容                         | 输出                                                                                                                                                     | 验收标准                                                     |
| ----- | ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------- |
| S3-B1 | 删除 `/research` 路由注册与 service | 删除 `backend/app/api/v1/endpoints/research.py`、`backend/app/services/research_service.py`、`backend/app/platform/agents/research/` 除 paper\_search 外所有文件 | Backend 启动无 `/research` 路由；单测中 research 相关测试已移除或改为历史兼容测试 |
| S3-B2 | Provider 迁移                  | `paper_search.py` 迁入 `nexus/src/nexus/providers/`；删除 `providers/research/{workspace,memory,embedding}.py`                                              | Nexus 单测仍通过（已使用迁移后路径）                                    |
| S3-B3 | 保留数据表                        | `research_*` 表模型代码保留（`backend/app/models/research_models.py`）；Alembic 迁移保留；不新增 down 迁移                                                                 | 表结构定义可查；历史数据按 retention 策略自然过期                           |

### 5.3 S3 交付检查清单

- [ ] Backend `/research` 路由注册已删除（启动日志无 `/api/v1/research` 挂载）

- [ ] `research_service.py` 与 `platform/agents/research/` 大部分文件已删除

- [ ] `paper_search.py` 已迁入 `nexus/src/nexus/providers/`，Nexus 单测通过

- [ ] `research_*` 表模型与 Alembic 迁移保留（不 drop 表）

- [ ] Backend 单测全绿（research 相关测试已移除或改为兼容测试）

- [ ] Nexus Runtime 仍正常运行（依赖迁移后的 provider）

**回退方式**：`git revert` S3-B1/B2/B3 提交；表数据未动，代码恢复即可回退。

***

## 六、并行实施：Repro Worker 与会话持久化（P1 增强）

以下任务与 S1/S2/S3 主线并行，不阻塞转型上线，但需在 Nexus 真实演示前完成。

### 6.1 Repro Worker 容器实现

| 任务 ID   | 任务内容                    | 输入                                                                               | 输出                                                                                                                                      | 验收标准                                       | 预计工作量          |
| ------- | ----------------------- | -------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------ | -------------- |
| P1-W1 ✅ | Repro Worker Dockerfile | `deploy/repro-worker/README.md` 契约                                               | `deploy/repro-worker/Dockerfile`：Python 3.12-slim + git/编译工具，**非 root** 运行，限额在 compose 施加                                               | 代码就绪（构建在 W4 部署时执行）                         | —              |
| P1-W2 ✅ | Repro Worker 服务         | Worker 契约                                                                        | `deploy/repro-worker/worker.py`：`POST /jobs` + `GET /jobs/{id}`，bash 逐步执行（单步超时 SIGKILL、总预算 15min、磁盘 2GB、串行、工作目录 ephemeral、artifact 白名单） | 测试 7/7（`test_worker.py`）                   | 完成（2026-09-03） |
| P1-W3 ✅ | License 校验              | GitHub API + 本地 LICENSE 双重校验                                                     | 三源判定（请求声明/GitHub spdx/本地文件）fail-closed，越线返回 `LICENSE_VIOLATION`                                                                         | 测试覆盖 GPL 拒绝 / 无 License 拒绝 / MIT 放行        | 完成（2026-09-03） |
| P1-W4   | 服务器部署                   | P1-W1/W2/W3                                                                      | 独立容器（compose：独立网络 `repro_net`、1C2G/512 pids、仅绑 127.0.0.1:8400）+ iptables 出站白名单；部署清单见 `deploy/repro-worker/README.md`                    | `curl http://127.0.0.1:8400/health` 返回 200 | **需用户授权部署**    |
| P1-W5 ✅ | Nexus 对接                | P1-W4 + `nexus.env` 配置 `NEXUS_REPRO_WORKER_URL`（+ 可选 `NEXUS_REPRO_WORKER_TOKEN`） | `run_reproduction` 真实提交作业到 Worker（Bearer 认证已实现）；代码已同步服务器，URL 未配置前维持 fail-closed                                                         | 演示脚本用例 5 返回 `queued` 而非 `UNAVAILABLE`      | 待 W4           |

**安全约束**（AGENTS.md §4.1.10）：

- Worker 容器与 Backend/Judge0 **网络隔离**（独立 Docker 网络，不加入 `app_net`）

- 资源限制：`--cpus=1.0 --memory=2g --pids-limit=512`

- 磁盘配额：挂载独立 volume，`--storage-opt size=2G`（需 overlay2 driver）

- 执行超时：单次复现 15 分钟硬截止，超时 SIGKILL

- 网络限制：出站仅允许 GitHub.com / PyPI / 常见镜像站（iptables 白名单）

### 6.2 Nexus 会话持久化（可选，P1）

| 任务 ID | 任务内容                           | 输入                      | 输出                                                                                                    | 验收标准          | 预计工作量 |
| ----- | ------------------------------ | ----------------------- | ----------------------------------------------------------------------------------------------------- | ------------- | ----- |
| P1-C1 | PostgresSaver 替换 InMemorySaver | LangGraph PostgresSaver | `nexus/src/nexus/agent.py` 使用 `PostgresSaver`（连接 Backend 同一 PostgreSQL，独立 schema `nexus_checkpoints`） | 重启后会话可续聊      | 1 天   |
| P1-C2 | 会话列表 API                       | PostgresSaver           | `GET /api/v1/nexus/sessions`：返回当前用户会话列表（session\_id + 最后消息时间 + 标题）                                    | 前端可显示历史会话     | 0.5 天 |
| P1-C3 | 前端会话切换                         | P1-C2                   | Nexus 页面左侧边栏显示会话列表，点击切换 session\_id                                                                   | 切换会话后对话历史正确加载 | 1 天   |

**数据策略**（AGENTS.md §4.1.11）：

- Checkpoints 进 `nexus_checkpoints` schema（与业务数据库分域）

- Retention 策略：30 天未活跃会话自动清理（cron 任务）

- 不持久化完整 LLM trace 与 prompt（只保留结构化 checkpoint）

***

## 七、风险与应对

| 风险                                    | 影响                     | 概率 | 应对措施                                                   |
| ------------------------------------- | ---------------------- | -- | ------------------------------------------------------ |
| DeepSeek API 配额不足                     | S1-V1 验收失败             | 中  | 提前确认余额；备用 `NEXUS_DDGS_ENABLED=true` 降级方案               |
| 服务器资源不足（4C8G 同时跑 5 个容器）               | Nexus/Repro Worker OOM | 中  | 初期 Nexus 1C2G、Repro Worker 按需启动；实测不足时临时调低 paddleocr 限制 |
| S1 真实链路验收不通过                          | 无法触发 S2                | 低  | 保留 S1-V1 失败日志，按实际错误修复后重新验收                             |
| 前端 Nexus 页面 UI 复杂度超预期                 | S1-F1 延期               | 中  | 降低 P0 UI 复杂度：纯文本对话 + 工具调用折叠卡片，暂不做富文本/Markdown 渲染       |
| Repro Worker License 校验被绕过            | 执行未授权代码                | 低  | Worker 侧双重校验（GitHub API + 本地 LICENSE 文件解析）；日志记录所有执行请求  |
| 旧 research 数据迁移需求（用户要求导出历史 workspace） | S3 下线阻塞                | 低  | 提前告知数据按 retention 自然过期；紧急需求时提供一次性导出脚本                  |

### 7.1 实施中发现的既有隐患（非本次转型引入，待单独决策）

| 发现             | 事实                                                                                                                                                                                                                                | 现状                                                                |
| -------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| **签名校验实际全局失效** | `settings.NO_AUTH_WHITELIST` 含一条 `"/"`，而 `SignatureMiddleware` 用 `current_path.startswith(path)` 匹配白名单——任何路径都以 `/` 开头，故所有请求都跳过验签。另：前端 `request.js` 硬编码 `STATIC_KEY = 'dev-static-key-change-in-prod'`，正是后端 SEC-02 校验拒绝启动的 dev 默认值 | **未改动**。修复面覆盖全部接口与前端签名口径，风险与收益需单独评估后再动；本次 Nexus 链路仍按规范正常签名，不依赖该缺陷 |
| **ruff 门禁已红**  | 仓库无 `[tool.ruff]` 配置，`ruff check .` 按默认规则报 7913 项（其中 B008 一项 1078 处，是本仓库通行的 FastAPI `Depends` 写法）。CI 的 `ruff check` 与 `ruff format --check` 步骤在当前代码上无法通过                                                                          | **未改动**。新增文件与邻近代码风格保持一致；若要启用门禁，应先落一份 `[tool.ruff]` 配置确定基线         |

***

## 八、资源需求与外部依赖

### 8.1 需用户明确授权的事项

1. **部署授权**（S1-B1）：✅ 已授权并完成（2026-09-03）；P1-W4（Repro Worker 部署）仍待授权
2. **DeepSeek API Key**（S1-B1）：✅ 已提供并配置（仅存服务器 `nexus.env`，600 权限）
3. **服务器资源调整授权**（若实测资源不足）：临时调低 paddleocr 内存限制或重启部分容器

### 8.2 技术依赖清单

| 依赖                            | 当前状态  | 用途                                  | 缺失时影响                  |
| ----------------------------- | ----- | ----------------------------------- | ---------------------- |
| DeepSeek API Key              | ✅ 已配置 | Nexus LLM 推理                        | —（S1-V1 已验收）           |
| SearXNG 容器（47.99.97.154:8888） | ✅ 已部署 | Web Search 主通道                      | 降级到 DuckDuckGo，体验下降    |
| PostgreSQL 16                 | ✅ 已部署 | Backend 数据库 + Nexus checkpoints（P1） | P0 用 InMemorySaver 可跳过 |
| systemd（服务器）                  | ✅ 可用  | Nexus/Repro Worker 进程管理             | 无法持久化运行                |
| Docker（服务器）                   | ✅ 可用  | Repro Worker 容器隔离                   | P1-W 系列任务无法进行          |

***

## 九、进度追踪与验收

每完成一个阶段，更新本文档顶部状态标记：

- **S0 兼容冻结**：✅ 已完成（2026-09-03）

- **S1 双轨期**：✅ **全部完成（2026-09-03）**——S1-B1 服务器部署 + A2 迁移 0068
  （186/186 用户回填默认授权）+ S1-V1 真实链路冒烟 **6/6 通过**（验收记录：
  [验收记录/S1\_Nexus真实链路\_2026-09-03.md](验收记录/S1_Nexus真实链路_2026-09-03.md)）；
  冒烟中发现并修复非流式 /chat stream\_mode 缺陷（`93415f18`，附真实图回归测试）

- **S2 切换期**：✅ **完成（2026-09-03）**——旧接口 410 Gone（`6635f106`）、前端
  四面板/路由/client 删除（`8255a4c7`），release `8255a4c7` 线上验收通过
  （[验收记录/S2\_切换期\_2026-09-03.md](验收记录/S2_切换期_2026-09-03.md)）

- **S3 下线**：✅ **完成（2026-09-05，P2 计划 M5）**——删除
  `endpoints/research_agent.py`、`platform/agents/research/` 全目录、
  providers `{paper_search,workspace,access}`、路由注册与
  `bootstrap_research_agent`、旧 research 测试；410 由 deprecated 中间件
  继续短路（线上实证 `RESEARCH_API_RETIRED`）；`research_*` 表模型 +
  Alembic 保留、未新增 down 迁移（S3-B3）。事实修正：
  `services/research_service.py` 幽灵文件（从未存在）、paper_search 无需迁移
  （nexus 独立降级链实现）、question_bank/question_generation/web_research
  与 web_research 端点+service 保留（TeachingAgent/tasks 活消费）。
  验收记录：[验收记录/M5\_验收\_2026-09-05.md](验收记录/M5_验收_2026-09-05.md)

- **P1-W Repro Worker**：✅ **全部完成**——W1/W2/W3/W5（2026-09-03，提交
  `ec56ada1`；worker 测试 7/7、nexus 29/29）；W4 服务器部署完成（2026-09-04：
  torch 2.14.0+cu130 镜像构建、容器重建 healthy、`/health` ok、iptables 出站
  白名单重刷；随服务器迁移落新机 103.36.223.177，见
  [验收记录/服务器迁移_2026-09-04.md](验收记录/服务器迁移_2026-09-04.md)）。
  **nanoGPT 真实执行复测 ✅**（2026-09-04：作业 `b3002f061502` 5/5 步
  succeeded，train 2000 iters val loss 1.8857 ≈ 预设预期，sample 真实输出；
  过程修复：input.txt 注入种子规避 raw.githubusercontent.com 境内 TLS 阻断、
  OMP_NUM_THREADS=1 + step 720s 解决 cgroup 线程争抢超时）。

- **P1-C 会话持久化**：✅ **全部完成**——C1（2026-09-03，`cbd89410`：
  PostgresSaver + `nexus_checkpoints` 独立 schema）；C2/C3（2026-09-05，
  `5eeab092`：会话列表/历史 API + 反代透传 + 前端 real 模式侧栏接线）。
  线上验收：重启恢复实证、跨用户隔离实证、title 首插语义正确；全项记录见
  [验收记录/P1_验收_2026-09-05.md](验收记录/P1_验收_2026-09-05.md)。

**验收归档规则**：

- 每阶段验收记录归档至 `docs/phase1/验收记录/{阶段}_{日期}.md`

- 包含：操作步骤、预期结果、实际结果、截图/日志、通过/失败判定

- 失败时保留完整错误日志，不假造成功

***

## 十、后续优化方向（P2 及以后，不阻塞转型上线）

> 2026-09-04 更新：本节方向已立项为正式开发计划
> [CodeNexus_P2开发计划.md](CodeNexus_P2开发计划.md)（M0-M5 里程碑 + P2+ 候选池），
> 后续以该计划为准；本节保留作为原始方向记录。

1. **Nexus 前端富文本渲染**：Markdown、代码高亮、LaTeX 公式
2. **Nexus 多模态输入**：上传 PDF/图片作为对话上下文
3. **Repro Worker 并发队列**：支持多个复现任务排队执行
4. **Nexus 工具扩展**：GitHub API、Jupyter Notebook 执行、数据可视化
5. **Nexus 与 TeachingAgent 协作**：课程内调用 Nexus 做深度研究
6. **Nexus 性能优化**：LangGraph 编译缓存、工具结果缓存、流式 token 聚合

***

## 附录：关键文件清单

| 文件路径                                          | 用途                                           | 负责阶段  |
| --------------------------------------------- | -------------------------------------------- | ----- |
| `nexus/src/nexus/main.py`                     | Nexus Runtime 服务入口                           | S1-B1 |
| `nexus/src/nexus/agent.py`                    | Deep Agents 编排                               | S1-B1 |
| `nexus/src/nexus/tools/*.py`                  | 工具实现（web\_search/paper\_search/reproduction） | S1-B1 |
| `backend/app/api/v1/endpoints/nexus_proxy.py` | Backend 反代路由                                 | S1-B2 |
| `frontend/src/views/nexus/NexusPage.vue`      | Nexus 前端页面                                   | S1-F1 |
| `frontend/src/api/nexus.js`                   | Nexus API 客户端                                | S1-F2 |
| `deploy/systemd/nexus-runtime.service`        | Nexus systemd 服务                             | S1-B1 |
| `deploy/repro-worker/Dockerfile`              | Repro Worker 容器                              | P1-W1 |
| `deploy/repro-worker/worker.py`               | Repro Worker 服务                              | P1-W2 |
| `docs/phase1/验收记录/`                           | 验收记录归档目录                                     | 所有阶段  |

***

**计划状态**：本计划作为 CodeNexus 转型实施的权威路线图，随实施进度持续更新。下一步：等待用户授权部署 Nexus Runtime（S1-B1）与提供 DeepSeek API Key，启动 S1 双轨期实施。
