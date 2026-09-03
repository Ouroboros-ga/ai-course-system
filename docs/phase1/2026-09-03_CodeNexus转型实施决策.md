# CodeNexus 转型实施决策记录（2026-09-03）

> **状态**：现行决策文档
> **依据**：《CodeNexus 转型设计与实施方案 v1.2》《CodeNexus Nexus Runtime 技术补充说明 v1.0》
> 《CodeNexus 技术决策补丁 v1.1》及仓库核查
> [CodeNexus\_技术决策补丁v1.1\_核查结论.md](CodeNexus_技术决策补丁v1.1_核查结论.md)，
> 加开发者 2026-09-02/03 逐项确认的遗留问题答复。
> **基线**：`dev-liu` @ `67f94026`（`feature/xh202620` 全部 71 个提交已于 2026-09-03 合并回
> `dev-liu`，开发基线回归单一主线）。
> **服务实际部署地址**：`http://47.99.97.154/`（编码智能体在不确定时可对其做只读访问，
> 已写入 AGENTS.md §1/§3.1）。

***

## 0. 决策背景

《技术决策补丁 v1.1》核查后仍遗留 7 项未回答/不完整问题（P0×1、P1×4、P2×2）。
开发者于 2026-09-03 全部答复完毕，本文是这些答复的正式落档，并记录同日完成的
基线合并与文档清理。此前《转型方案 v1.2》与补丁 v1.1 中与本冲突的旧口径作废。

## 1. 决策清单

| #   | 主题                | 最终口径                                                                                                                                                                                                                                                                                                                                        |
| --- | ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| D1  | 开发基线              | `feature/xh202620` 合并进 `dev-liu`（merge `67f94026`），此后只在 `dev-liu` 单一主线开发；`feature/xh202620` 仅作历史参考。                                                                                                                                                                                                                                         |
| D2  | 产品双入口             | **TeachingAgent**：课程内便捷问答智能（教学问答、教学动作、对话式代码挑战），工作流固定，本质是"能检索到精确知识的问答机器人"。**Nexus AI**：从课程外进入的全局入口，负责复杂问题拆解与持续执行（论文研究、快速复现等），是"真正的 Agent"；基于 Deep Agents + LangGraph，运行于独立 Nexus Runtime。CodeNexus 方向与既有文档冲突时以新方向为准，AGENTS.md 已同步。                                                                                                           |
| D3  | Web Search        | 用由服务器 IP 直接发起的免费搜索能力，配置**双通道**：主通道为服务端 Web Search（部署在 `47.99.97.154` 服务环境），下位替代为本机（agent 侧）Web Search 能力。**已落地（2026-09-03）**：SearXNG 容器 `nexus-searxng` 部署于 47.99.97.154 并验收通过（中英文 20+ 结果、延迟 0.8–2.0s），产物见 [deploy/searxng/](../../deploy/searxng/)。                                                                                        |
| D4  | Demo 论文候选         | 选人工智能 / 机器学习 / CS 方向。候选清单已建立（2026-09-03，License 经 GitHub API 核实）：[2026-09-03\_Demo论文候选清单.md](2026-09-03_Demo论文候选清单.md)。**主选 nanoGPT**（GPT-2 最小复现，MIT，官方 CPU 命令约 3 分钟训练闭环），备选 CLIP；其余 4 项为候选池。                                                                                                                                               |
| D5  | Repro Worker      | 部署于 `47.99.97.154` 服务环境，与 Backend、Judge0 **同宿主机、容器级隔离**（独立容器与独立网络，非物理隔离——该机为 4C8G 单机，主栈与 Judge0 栈均运行其上；原表述"物理隔离"不准确，2026-09-03 经开发者澄清修正）；未知 GitHub Repo 视为不可信代码，只进 Repro Worker 受限执行。                                                                                                                                                       |
| D6  | Nexus 数据策略        | 语义分域，见 §3。                                                                                                                                                                                                                                                                                                                                  |
| D7  | 旧科研工作台            | 前端四面板科研工作台下线；新能力收敛为单一 Nexus 入口（前端设计后续做，当前优先实现后端功能）。                                                                                                                                                                                                                                                                                         |
| D8  | Teaching Agent 戏份 | 继续承担验收链中的"教学"场景（课程内问答、学情、代码挑战）；Nexus 承担"科研助研"场景（拆解赛题、论文研究、快速复现）。两者共享业务基础设施但职责分离。                                                                                                                                                                                                                                                            |
| D9  | 文档清理              | SmartCarb 时代文档删除；XH-202620 差距分析文档标注为现行赛题工作文档；`research/README.md` 标注 Legacy，见 §4。                                                                                                                                                                                                                                                           |
| D10 | Nexus 使用权与课程绑定    | **新增平台权限** **`platform.nexus.use`** 作为 Nexus AI（课程外全局入口）的使用门槛，**默认授予所有用户**（注册/登录/泛雅同步自动授予 + 迁移 0068 回填存量用户），**不强制绑定课程**——`active_course_id = null` 时 Nexus 仍可用，Course RAG 仅在有课程上下文且拥有对应课程权限时开放。`platform.admin` 为超集自然可用。管理员可经 `GET/POST/DELETE /api/v1/admin/users/{id}/platform-permissions` 按用户**撤销**；显式撤销优先于默认授权，不被登录/同步流程复活。落地证据见 §4.3。 |

## 2. Web Search 免费方案调研与落地（2026-09-03）

按"服务器 IP 直接发起、免费、无需付费 Key"的要求，候选排序：

| 方案                                  | 是否需 Key | 成本         | 判断                                                 |
| ----------------------------------- | ------- | ---------- | -------------------------------------------------- |
| **SearXNG 自部署**                     | 否       | 容器资源       | 开源元搜索引擎，聚合多引擎，支持 JSON 输出；容器化部署无按次计费。**已选为主通道并落地**。 |
| **DuckDuckGo（duckduckgo-search 库）** | 否       | 免费         | 无 Key、Python 库直连，最简接入；实际可用频率有隐性上限，保留为代码内降级路径。      |
| Brave Search API 免费档                | 是（免费注册） | 2000 次/月   | 独立索引质量好，但额度对 Demo 演示偏紧，未选。                         |
| Tavily / Exa / Bing                 | 是       | 1000 次/月左右 | 需注册 Key，未选。                                        |

**落地结果（47.99.97.154，容器** **`nexus-searxng`，仅绑定** **`127.0.0.1:8888`）**：
部署与验收细节见 [deploy/searxng/README.md](../../deploy/searxng/README.md)。要点：

- 服务器为境内节点，SearXNG 默认引擎（brave/duckduckgo/google cse/startpage/
  wikipedia/wikidata）全部不可达且拖满 3s 连接超时；实测显式启用
  **360search + yandex**（bing/mojeek 可达但无结果，保留观察），禁用被墙引擎；

- 验收：中英文聚合查询 20+ 结果、延迟 0.8–2.0s、零失败引擎；英文论文类查询
  可直接检索到 arXiv abstract 页面；

- 镜像经 `docker.1panel.live` 镜像源拉取（服务器 daemon.json 加速器均已失效）；

- 消费契约：`GET http://127.0.0.1:8888/search?q=<query>&format=json`。

## 3. Nexus 数据策略语义（D6 落地口径）

三个数据域，写入路径与保留策略互不混用：

1. **业务数据库（现有 PostgreSQL 业务库）**：用户、课程、权限、课程内容、
   LearningEvidence 等业务数据。Nexus 只能经 Course Access v1 与既有服务读写，
   不绕过授权决策链。
2. **Nexus 运行时存储（Nexus 专属，同一 PostgreSQL 实例的独立 schema 或独立库）**：
   LangGraph checkpoint、todo/notepad、artifact 元数据、Nexus 会话审计。独立保留
   周期与删除策略，不混入业务表；同样不持久化完整原始 Prompt 与完整模型输出，
   沿用现有最小化白名单思路。
3. **Artifact 存储**：媒体类复用现有媒体域（`object_key`，不可变发布语义不变）；
   文档/报告类 artifact 新建轻量记录（object\_key + 来源 + License 标注），
   不新建平行存储。

不变边界：外部 Web/论文研究结果标记"补充参考"（`is_supplementary`），不写入掌握度、
推荐、正式 Evidence 或课程图谱；复现输出标注来源仓库与 License。

## 4. 同日完成的落地变更（代码证据）

- **基线合并**：`git merge feature/xh202620` → `dev-liu` @ `67f94026`（71 commits），
  工作区无冲突遗留。

- **AGENTS.md**：§1 阶段与部署地址改写（CodeNexus 转型、`http://47.99.97.154/`
  只读授权、基线 `dev-liu`）；§2.2/§5.2 `research/` 标注 Legacy；§3.1 增加部署服务
  只读访问说明；§4.1 新增 9–11 三条硬边界（Nexus 独立环境、Repro Worker 与
  License 红线、Nexus 数据分域）。

- **`backend/app/platform/agents/research/README.md`**：顶部加"已废弃（仅历史追溯）"
  标注，指向本文与转型方案。

- **SmartCarb 文档清理**：tracked 文档 6 个（`SmartCarb_技术文档.tex`、
  《SmartCarb项目技术文档正式稿》等）已在合并提交中删除；本次再删除 untracked 残留
  `frontend/dist/static/docs/project/SmartCarb项目技术文档正式稿.docx`（构建产物，
  源已删）与 `generated_pptx/SmartCarb路演PPT_14页.pptx`（旧路演材料）。
  **保留**：`deploy/` 下 `smartcarb-postgres-*` systemd unit 与
  `smartcarb-release.sh` / `smartcarb-prune-releases.sh` —— 属部署基础设施而非
  文档，重命名/删除会破坏线上部署；如需去 SmartCarb 命名，应作为一次显式的
  部署变更单独处理。

- **赛题文档标注**：[2026-08-20\_XH202620差距分析与产品定位.md](2026-08-20_XH202620差距分析与产品定位.md)
  顶部状态改为"现行赛题工作文档"，基线行更新为 `dev-liu`，新增 R15 记录本次转型。

- **文档索引**：`docs/DOCUMENTATION_INDEX.md` 顶部新增本决策记录入口。

### 4.1 同日补充落地（2026-09-03 第二批，用户五项答复后）

- **SearXNG 主通道部署**（用户授权容器部署）：产物入库
  [deploy/searxng/](../../deploy/searxng/)（compose + settings + README），并实际部署
  至 47.99.97.154 `/opt/searxng`；引擎可用性实测与验收结果见 §2 与该 README。

- **Demo 论文候选清单**：新增 [2026-09-03\_Demo论文候选清单.md](2026-09-03_Demo论文候选清单.md)
  （6 候选，License 经 GitHub API 核实，主选 nanoGPT、备选 CLIP）。

- **Nexus Runtime 位置定稿**：仓内独立目录 `nexus/`——独立 pyproject、独立 venv、
  独立进程/systemd 服务，不进 `backend/` 依赖树；与旧 Backend 通过 HTTP/SSE 通信。

- **/research API 下线时间表设计定稿**：见 §6。

- 变更一次性提交并推送（用户授权）。

### 4.2 Nexus Runtime P0 实施（2026-09-03 第三批）

P0 已在 `nexus/` 独立环境实现并本地验证通过（证据：单测 18/18 passed、
`uvicorn` 本地启动后 `/health` 返回 200、无 LLM Key 时 chat 端点 503
fail-closed、`web_search` 经 SSH 隧道真实调用 47.99.97.154 SearXNG 返回
arXiv 结果）：

- **独立环境**：`nexus/pyproject.toml` + `uv.lock` + 独立 venv，
  deepagents 0.7.12 / langgraph 1.x 只进本环境，未触碰 backend 依赖树。

- **工具链**：`web_search`（SearXNG 主通道 + DDG 降级，双失败返回
  `WEB_SEARCH_UNAVAILABLE` 不编造）、`search_arxiv_papers`（3s 限速 +
  1 天缓存，fail-closed）、`plan_reproduction`（nanoGPT MIT 预设，
  官方 CPU 命令）、`run_reproduction`（Repro Worker 未配置时必返
  `REPRO_WORKER_UNAVAILABLE`，绝不假造执行）。

- **服务**：FastAPI `/health`、`POST /api/v1/nexus/chat`（非流式）、
  `POST /api/v1/nexus/chat/stream`（SSE：token → tool\_call/tool\_result →
  done）；`NEXUS_API_KEY` 可选 Bearer 鉴权；会话经 InMemorySaver +
  thread\_id 续聊（重启即清，P0 预期内）。

- **测试**：`nexus/tests/` 18 个用例全 mock HTTP，未调用真实付费 LLM。

- **未完成（下一批）**：Repro Worker 容器与 `run_reproduction` 真实对接、
  真实 DeepSeek 端到端手工冒烟（需真实 Key）、服务器部署（需另行授权）。
  运行指南与已验证/未验证清单见 [nexus/README.md](../../nexus/README.md)。

### 4.3 权限门控落地（2026-09-03 第四批，D10 实施）

技术决策补丁 v1.1 核查结论的 P0 遗留 X1（全局 Nexus Session 在权限层无处安放）按
开发者决策落地为 D10，同批更正了 X2 的错误结论（见该文档头部修订记录）：

- **权限值**：`PlatformPermission.NEXUS_USE = "platform.nexus.use"`
  （`backend/app/models/access_control_model.py`）；迁移
  `20260903_1400_0068_nexus_use_platform_permission.py` 在 PostgreSQL 上
  `ALTER TYPE platformpermission ADD VALUE 'NEXUS_USE'`（经独立 AUTOCOMMIT
  连接执行——PG 12+ 中 ADD VALUE 的新值不能在加值的同一事务中使用，而同
  迁移的回填 INSERT 立即用到它；SQLite 无需 DDL），并**回填为所有存量用户
  插入默认授权行**（`migration_batch_id = '0068_nexus_use_default_grant'`）。

- **默认授权（同日修订）**：所有用户默认持有 `platform.nexus.use`——注册
  （`user.py user_register`）、登录（`user.py user_login` 补授存量用户）、
  泛雅同步（`platform.py _sync_platform_permissions`）经
  `ensure_default_nexus_grant` 自动授予。**显式撤销优先于默认授权**：该函数
  与 0068 回填均跳过已有行（含软撤销行），管理员撤销持久有效、不被任何流程
  复活。

- **强制点**：`nexus_proxy.py` 三个反代端点（`/health`、`/chat`、`/chat/stream`）
  全部改走 `require_nexus_use` 依赖（`require_platform_permission` 链，
  fail-closed，403 返回 `NEXUS_PERMISSION_DENIED`）；未触达 Runtime 前即拒绝。

- **授权入口**：`platform_admin_service.list/grant/revoke_user_platform_permissions`

  - `admin_platform.py` 三端点（软撤销保留审计行、re-grant 复用旧行满足唯一约束、
    `platform.admin` 不可经端点授予以防 USER\_MANAGE 持有者自我提权），写
    `PlatformAdminAuditEvent` 审计。

- **前端**：`counter.js` 新增 `canUseNexus`；`PrimaryNav.vue` 按权限渲染 Nexus
  入口；`NexusPage.vue` 深链直入时整页"暂无权限"态（仅被撤销/未回填用户可见）。

- **验证**：`backend/tests/test_nexus_proxy.py`（新增无权限 403 不触达上游、
  platform.admin 放行等，20/20 通过）、`backend/tests/test_platform_permissions.py`
  （授予/撤销/复授/审计/403/422/404 + 注册默认授予/存量登录补授/撤销不被登录
  复活/迁移 0068 回填尊重撤销，10/10 通过）、关联回归（platform\_admin\_service /
  access\_control / course\_access）29 通过、前端契约测试 88/88、`npm run build`
  通过。本地为 SQLite + 随机测试密钥环境；PostgreSQL `ALTER TYPE` + 回填分支
  待服务器部署时实测（`alembic upgrade head` 属部署动作，需另行授权）。

### 4.4 X2 口径更正（2026-09-03）：CS 知识库存在真实生产检索路径

经逐一核对代码（`DisciplineKnowledgePortImpl` 装配链、`/api/v1/discipline-knowledge/*`
路由、`discipline_corpus` FTS+pgvector 实现、审计表部署记录），补丁核查结论 §二 X2
中"所有已落地的向量检索实现都是 course-scoped""根本不存在 CS-scoped 的生产检索路径"
**不成立**，正确口径为：

- **概念层**：`backend/app/platform/knowledge/discipline_kb.py`
  （`cs-knowledge/1.0`，112 节点 / 106 关系，进程内 BM25），经
  `/api/v1/discipline-knowledge/search` 暴露（仅登录鉴权、无课程校验），
  前端一级入口「学科知识库」；TeachingAgent 经 `DisciplineKnowledgePortImpl`
  默认消费（`TEACHING_AGENT_DISCIPLINE_KB_ENABLED=True`）。

- **语料层**：`backend/app/platform/knowledge/discipline_corpus.py`——SQLite
  FTS5（635 万段落索引）+ pgvector HNSW 向量召回（130,351 段已嵌入，
  bge-small-zh-v1.5 / 512 维，表 `discipline_corpus_embedding` 无 course\_id），
  RRF 融合；2026-09-01 起在服务器启用（见功能现状审计表）。

- 仍然成立的只有：课程课件证据链（`course-lancedb/1.0` +
  `ActiveBundleCourseRetrievalPort`）是 course-scoped。Nexus 集成 CS KB 时
  直接消费上述两条路径即可，§5 Gate 应按此事实执行；注意学科 KB 结果定位为
  `is_supplementary`（补充参考），不进入课程证据闭包与掌握度。

## 5. 决议状态（2026-09-03 全部处置完毕）

原 5 项遗留已全部经用户答复处置：

1. **SearXNG 容器部署**：已获明确授权并完成部署与验收（见 §2 与
   [deploy/searxng/README.md](../../deploy/searxng/README.md)）。
2. **Demo 论文候选**：已列候选清单并定主选（nanoGPT）备选（CLIP），见 D4。
3. **Nexus Runtime 位置**：定稿为仓内独立目录 `nexus/`（见 §4.1）。
4. **旧 research API 下线时间表**：设计定稿，见 §6。
5. **Nexus LLM Key**：默认沿用 DeepSeek（`LLM_PROVIDER=deepseek` 模式，环境变量
   在 Nexus Runtime 侧独立注入，不与旧 Backend 共享 .env），随 Nexus 第一个实施
   变更时确认。

## 6. 旧 /research API 与科研工作台下线时间表（设计定稿，2026-09-03）

按 Nexus 里程碑驱动（不用日历日期，避免与材料节点耦合），四阶段：

| 阶段           | 触发条件                                           | 动作                                                                                                                                                | 回退方式                   |
| ------------ | ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------- |
| S0 兼容冻结（已完成） | —                                              | `research/` 标 Legacy、README 顶部废弃标注、AGENTS.md §2.2/§5.2 同步；只修 P0 缺陷，不新增能力                                                                          | —                      |
| S1 双轨期       | Nexus 后端 P0（论文研究 + 快速复现 + Web Search 主链路）本地可运行 | 新增 `/api/v1/nexus/*` 路由；前端新增单一 Nexus 入口，主导航移除科研工作台四面板入口（页面深链暂保留）；`/research/*` 路由行为不变，响应加 `Deprecation: true` 头                                   | 前端导航项恢复                |
| S2 切换期       | Nexus 真实链路手工验收通过（演示脚本完整走通一次）                   | 删除前端四面板页面与 `/research` API client；后端 `/research/*` 返回 `410 Gone` + 迁移说明 JSON                                                                      | 前后端各 revert 一个提交       |
| S3 下线        | S2 稳定 ≥ 1 个迭代                                  | 删除后端 `/research` 路由注册与 service；`research_*` 数据表**保留不 drop**（按既有 retention 策略自然过期，不做数据迁移）；`providers/research` 中被 Nexus 真实调用的部分迁入 `nexus/`，其余随模块删除 | git revert；表数据未动，天然可回退 |

设计约束：

- S2 之前 `/research` 不做任何行为变更，保证比赛演示期间旧链路随时可用；

- `providers/research` 的迁移以"Nexus 真实调用"为准，不做提前抽象迁移；

- `research_*` 表不 drop 是硬约束（AGENTS.md §4.2.3：不静默删除仍有消费者的数据）。

