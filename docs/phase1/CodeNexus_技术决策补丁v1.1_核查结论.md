# CodeNexus 技术决策补丁 v1.1 —— 核查结论清单

> 核查对象：`CodeNexus_技术决策补丁_v1.1 (1).md`
> 核查基准：本地工作区 `dev-liu` @ `95e26789`（文档 §1 确认的施工基线）
> 核查方法：① 逐条对照《转型方案 v1.2》审查提出的 24 项疑问（A1–A7 / B1–B5 / C1–C6 / D1–D6）；
> ② 将文档中的结论、接口、配置、目录、流程逐项与代码实况比对；③ 外部事实经 GitHub API 复核。
> 核查时间：2026-09-02

---

## 0. 结论摘要

| 分类 | 数量 | 说明 |
|---|---|---|
| 已确认一致 | 17 项 | 文档结论与代码事实吻合，或文档已正确修正 v1.2 的错误 |
| 存在冲突 | 7 处 | P0 4 处、P1 3 处，**全部应以代码现状为准** |
| 尚未回答 / 不完整 | 7 项 | P0 1、P1 4、P2 2 |
| 超出当前工程范围 | 4 项 | 文档假设了仓库中不存在的能力或设施 |

上一轮 24 项疑问中：**完整回答 17 项，部分回答 6 项，未回答 1 项**（C6 的共享面细分，见 U5）。
补丁整体质量显著高于 v1.2，尤其 §6 主动修正了"langgraph 不能升级"的未验证论断、§10 把 Reproduction Orchestrator 提为一等模块、§23 建立 License 红线——这三处是真正的进步。

---

## 一、已确认一致（文档章节 ↔ 代码证据）

| 原疑问 | 补丁章节 | 文档结论 | 代码证据 | 判定 |
|---|---|---|---|---|
| A1 基准分支脱节 | §1 | 施工基线改为 `dev-liu`，`feature/xh202620` 仅作历史参考 | `git branch --show-current` = `dev-liu` | ✅ |
| A3 迁移成本被低估 | §3 | 五表保留/不删除/不迁移/不改表语义 | 仅 `20260811_2230_0053_research_harness_workspace.py` 涉及 `research_*`；`0054`–`0066` 均未触碰（grep 验证） | ✅ |
| A4 复用清单掺水 | §4 | 改为 Confirmed / Must-rediscover 两栏，只确认 arXiv | `providers/research/paper_search.py` 仅 `ArxivPaperSearchProvider` | ✅ |
| A6 算力与验收脱节 | §15 + §27 | 论文选择前移为 P0 Gate，给出 8 条筛选标准 | 无冲突（属决策补全） | ✅ |
| A7 能力无优先级 | §26 | P0/P1/P2 重标，并声明"框架存在 ≠ 必须产品化" | 无冲突 | ✅ |
| B1 依赖硬冲突 | §6 + §7 | 明确"不能加入现有依赖环境"，定义独立 Python env / pyproject / lockfile / process | `pyproject.toml:16` `langgraph>=0.6,<0.7`；无 langchain-core；deepagents 0.7.12 要求 langchain-core>=1.6.1 | ✅ |
| B2 未论证不能升级 | §6 | 主动撤回"技术上绝对无法升级"，改为"P0 不承担迁移风险" | 修正正确 | ✅ |
| B3 自研工作量低估 | §10 | Reproduction Orchestrator 列为一等模块，明确自研边界 | 无冲突 | ✅ |
| B5 复用优先级矛盾 | §12 | 分两类：已生产可用领域能力 → 保留现有；新增通用基础设施 → 成熟开源 | 无冲突 | ✅ |
| C1 沙箱权限空白 | §13 + §14 + §29 | Judge0 ≠ Repro Sandbox；专用 Worker 拓扑；docker.sock 只给 control plane | `deploy/judge0/docker-compose.yml` 头部注释明确移除 privileged、需安全评审 | ✅ |
| C2 存储归属矛盾 | §16 + §17 | 区分 Business DB ≠ Runtime Operational Store，给 13 行归属表 | `deploy/postgres/compose.yml:11,24` 支持新 database + initdb | ✅ |
| C3 Mode 作用域 | §18 | `mode = per-run input`，Run 中锁定，历史可见/能力受当前 mode 控制 | 无冲突 | ✅ |
| C4 RAG 无判据 | §19 | 10–20 条 Golden Set，4 项观察指标 | 无冲突 | ✅ |
| C5 Freeze 粒度 | §20 | 10 项冻结字段 + L1/L2 分级 + 三个布尔标记 | 无冲突 | ✅ |
| D1 无 License 仓库 | §23 | 两个无 License 仓库移出 Implementation Reference Pool，列 5 条禁止 | GitHub API：`1a1a11a/2026_paper_reproduce` 0★ 无 License；`AI9Stars/AutoReproduce` 45★ 无 License | ✅ |
| D2 paper-qa 接入未验证 | §21 + §22 | 默认走 Independent Spike + Sidecar，不强行装进 Runtime | paper-qa 2026.8.12 依赖 fhaviary[llm]/fhlmi/tantivy | ✅ |
| D3 版本策略 | §8 | pre-1.0 定位准确，禁 follow main，pin + uv.lock + 契约测试 | `backend/uv.lock` 存在（421 KB），§8 的 `commit uv.lock` 可执行 | ✅ |

---

## 二、存在冲突（7 处）

### X1 [P0] §2 全局 Nexus Session 在权限层无处安放

- **文档 §2**：`active_course_id = null` 时 Nexus 仍可用；Course RAG Tool Gate = `active_course_id != null` + 用户拥有 `course.view`。
- **代码冲突**：
  - `backend/app/models/access_control_model.py:38-44` —— `PlatformPermission` 枚举只有 6 项（`platform.admin` / `course.create` / `course.audit` / `user.manage` / `safety.manage` / `capability.manage`），**没有任何 Nexus / AI 助手使用权限**。
  - `backend/app/services/course_access_service.py:113` —— `CourseAccessContext.course_id: int`，**非 Optional**。
  - `backend/app/services/course_access_service.py:306-324` —— `course_permission()` 依赖从 path/query 取 `course_id`，取不到直接 `HTTPException(500, "权限依赖缺少 course_id")`。
- **冲突原因**：Course Access v1 是纯 course-scoped 设计，没有"全局能力"这一层。文档在**产品层**定义了 `active_course_id = null`，但**权限层**没有对应的承载物。
- **以谁为准**：**以代码现状为准。** 文档 §2 的产品模型不能靠现有权限层直接落地。
- **修改建议**：
  1. §2 增加一条硬决策：全局 Nexus 的鉴权走**新增** `platform.nexus.use`（需 migration + 授权管理入口），或明确"Nexus 入口必须绑定默认课程"。二者必须选一，不能悬空。
  2. 在 §11 "Backend 侧只暴露稳定 HTTP Contract" 处补一条具体契约：`POST /api/v1/nexus/sessions` 的鉴权方式与返回的能力视图，明确它走 `require_platform_permission` 而非 `course_permission`。
  3. 注意与 AGENTS.md §4.1.6 的对齐：`User.role` 不得作为兜底授权来源，因此"登录即可用 Nexus"不是合规选项。

### X2 [P0] §5 CS Knowledge Base 在 retrieval 层没有生产路径（Gate 会失败）

- **文档 §5**：产品上视为已完成，要求 Phase 3 前置 Gate 跑通 `query("binary search") → real production retrieval path → structured results`，并记录 active provider / index location / embedding model / dimension 等 7 项。
- **代码冲突**：
  - `backend/app/platform/agents/providers/retrieval/__init__.py` 导出清单中，**只有 Course 域端口**：`ActiveBundleCourseRetrievalPort` / `ActiveBundleKnowledgeGraphPort` / `ActiveBundleScopePort`，其余全是 `RetrievalDemo*` / `UnavailableSandboxPort`。
  - `backend/app/platform/agents/providers/retrieval/active_bundle.py:237` —— `ActiveBundleCourseRetrievalPort.__init__` 默认 provider 为 `SqlLanceCourseKnowledgeProvider()`，**course-scoped**。
  - `backend/app/platform/knowledge/lancedb_provider.py:50` —— `schema_version = "course-lancedb/1.0"`，索引命名空间也是 course 前缀。
  - `backend/app/core/config.py:188` —— `VECTOR_STORE_PROVIDER: str = "lancedb"`，与 AGENTS.md / research README 声称的 pgvector 口径不一致（research README §4 说 research 记忆走 pgvector）。
- **冲突原因**：所有已落地的向量检索实现都是 course-scoped。文档 §5 假设"存在多个候选路径，需要重新发现哪个是生产路径"，实际情况更可能是**根本不存在 CS-scoped 的生产检索路径**。
- **以谁为准**：**以代码现状为准。** §5 的 Gate 大概率直接失败，且失败原因不是"选错了 provider"。
- **修改建议**：
  1. 把 §5 的 Gate 从"重新发现 Contract"改为**二元判定**：先确认 `CS Knowledge Base 是否存在可检索索引`。判定不成立时的三条出路需预先写明：(a) CS RAG 降为 P1；(b) 由 Nexus 自建 CS 索引——但按 §12 这属于**新增通用基础设施**，须走 Mature Upstream 而非"复用现有"；(c) P0 只保留 Course RAG + Web。
  2. §26 P0 清单里的 `CS RAG` 应加条件标注：`CS RAG（以 §5 Gate 通过为前提）`。
  3. 顺带修正口径冲突：在 §5 明确 `lancedb` 与 `pgvector` 各自的适用域（course 知识 vs research 记忆），避免后续智能体再踩。

### X3 [P0] §26 P0 的 "Web" 能力未接通（文档只处理了 arXiv，漏了 Web）

- **文档 §26**：P0 能力清单含 `Web`；§12 的复用分类未提及 Web；§4 的 Must-rediscover 清单也未列 Web。
- **代码冲突**：
  - `backend/app/platform/agents/tools/web_research.py:1` —— 文件 docstring 自述 `Compatibility shim`，仅转发到 provider。
  - `backend/app/platform/agents/providers/research/web_research.py` —— 只有 `CallableWebResearchPort`（第 19 行）与 `make_session_scoped_web_research_port`（第 65 行），均为**注入型回调包装**；全文件无 `httpx` 调用、无搜索引擎 API、无 api_key 配置。
- **冲突原因**：Web 检索只定义了 Port 与装配函数，真实 provider 从未装配。与 §4 已识别的 arXiv 问题同类，但文档只修了 arXiv。
- **以谁为准**：**以代码现状为准。**
- **修改建议**：
  1. §4 的 `Must rediscover before reuse` 清单增加 `web_research`。
  2. §12 明确把 Web 归到"新增的通用基础设施 → Mature Upstream + Thin Adapter"，而不是默认它已存在。
  3. §26 P0 的 `Web` 加条件标注：`Web（需先确认 provider 或引入成熟搜索能力）`。

### X4 [P0] §14 "不应运行在主 Backend 业务容器" —— 实际没有业务容器，且 backend 以 root 跑在宿主机

- **文档 §14**：Repro Worker "不应运行在主 Backend 业务容器 / Judge0 worker 中"；§29 禁止"在 Backend host shell 运行未知 repo 代码"。
- **代码冲突**：
  - `deploy/systemd/smartcarb-backend.service:10-16` —— `User=root`，`WorkingDirectory=/opt/smartcarb/current/backend`，`ExecStart=/opt/smartcarb/shared/venvs/backend-py312/bin/python -m uvicorn ... --workers 2`。
  - 即 **backend 是 systemd 直接跑在宿主机上，不在任何容器里**；`deploy/docker-compose.yml` 只有 postgres / redis / neo4j / paddleocr / nginx。
- **冲突原因**：文档按"backend 跑在容器里"的常见部署假设写，与实际 systemd 宿主机部署不符；且 `User=root` 放大了 §29 的隔离难度。
- **以谁为准**：**以代码现状为准**（拓扑描述需改，安全结论需加强）。
- **修改建议**：
  1. §14 把"主 Backend 业务容器"改为"主 Backend 宿主机进程（systemd，root 运行）"。
  2. **明确比赛是否提供独立第二节点**——这是 §14 "优先专用 Linux VM"能否成立的前提。若只有单台 `120.26.104.247`，则单机部署下必须写明最低隔离方案：Repro Worker 在容器内运行 + 不挂载任何生产凭证 + 独立非 root 用户 + 受限网络，并把这四条写进 §29 的 P0 底线（当前 §29 只说"禁止"，没说单机下怎么做到）。
  3. `backend` 以 root 运行这一事实本身建议单列一个安全改进项（与 Nexus 转型解耦，但会影响 §29 的可执行性）。

### X5 [P1] §16 Artifact 存储归属指向了一个不存在的域

- **文档 §16**：`Artifact metadata → Existing Artifact / Storage domain 优先`；`Artifact binary/file → Object Storage，通过 object_key`；`Reproduction Report → Artifact storage`。§12 又把 `已有 Artifact` 列为"已经真实生产可用的领域能力"。
- **代码冲突**：仓库**没有通用 Artifact 域**。仅有：
  - `backend/app/models/document_artifact_model.py`
  - `backend/app/platform/document_intelligence/persistence/json_artifact_store.py`
  - `backend/app/platform/document_intelligence/source_artifact.py`
  - `object_key` 分散在各**媒体域**（`endpoints/asr.py`、`avatar.py`、`media_release.py`、`media_timeline.py`、`labs.py`、`course_build_editor.py` 等）。
- **冲突原因**：`object_key` 是**媒体资产**的既有约定（AGENTS.md §4.1.7 的语境也是媒体），不是通用 Artifact 服务。Nexus 要产出的 md / LaTeX / DOCX 无处可落。
- **以谁为准**：**以代码现状为准。**
- **修改建议**：
  1. §16 的 Artifact 两行拆为：媒体类资产 → 复用现有 `object_key` 媒体域；**Nexus 文档类 Artifact → 新建轻量 Artifact 记录 + 复用对象存储**（属 Nexus Runtime operational store 管辖，见 §16 表的同类项）。
  2. §12 的"已有 Artifact"限定为前者，避免被读成"文档生成能力已有"。

### X6 [P1] §17 独立 database/schema 可行，但缺可操作步骤与迁移归属

- **文档 §17**：Nexus Runtime 可连"同一 PostgreSQL 实例下独立 database/schema，或独立 PostgreSQL"，并说 P0 更看重权限隔离 / migration 可控 / crash-resume 实测。
- **代码状态**：`deploy/postgres/compose.yml:11` `POSTGRES_DB` 由私有 env 注入，`:24` 挂载 `./initdb` 到 `docker-entrypoint-initdb.d`（只读）→ **技术路径可行**。
- **冲突性质**：非冲突，是**缺失**。
- **修改建议**：
  1. 补一段可操作步骤：在 `deploy/postgres/initdb/` 增加脚本创建独立 database（如 `nexus_runtime`）与受限角色。
  2. 明确迁移归属：Nexus 独立库需**独立的 alembic 版本目录**，不得混入 `backend/alembic/versions/`（当前 head 为 `20260818_1200_0066_align_release_cues_node_fk.py`，与 Nexus 无关），否则 §16 "migration 可控"无法验证。

### X7 [P1] §3 的决策前提成立，但文档未记录验证结论

- **文档 §3**：五张 research 表"保留 / 不删除 / 不迁移 / 不改表语义"。
- **代码状态**：已实测——`backend/alembic/versions/` 中**只有** `20260811_2230_0053_research_harness_workspace.py` 涉及 `research_*` 表；`0054`–`0066` 共 13 个后续迁移均未触碰。
- **冲突性质**：**一致**，但结论未落到文档。
- **修改建议**：把上述实测结论（含 alembic head = `0066`）写进 §3，后续智能体无需重复验证。

---

## 三、尚未回答 / 回答不完整（7 项）

| 编号 | 级别 | 位置 | 缺口 | 建议 |
|---|---|---|---|---|
| U1 | P0 | §1 | Baseline Report 给了命令但**没给当前实测值**，智能体无从判断"是否异常" | 直接写入当前基线：`active branch = dev-liu`；`HEAD = 95e26789`；`feature/xh202620 = f0fd2989`；`merge-base = 9c52bd1c`；diff 规模 318 文件 / +20724 −25398。另注：当前工作区存在未提交改动（SmartCarb 技术文档等），开工前需确认是否 stash |
| U2 | P1 | §18 | Run 内 mode 锁定、历史可见，但**未定义 Artifact 的可用性边界**——General Run 中能否下载/引用 Research Run 产出的报告？ | 补一句：历史 Artifact 在 General Run 中"可见且可下载/引用"，但不得被 General 的 Tool 修改 |
| U3 | P1 | §26 + §28 | P0 含 `Persistent Checkpoint`，Spike 3 只测 `kill → restart → resume`，**未测跨版本 checkpoint 兼容**（deepagents 为 pre-1.0，升级后旧 checkpoint 能否读出） | Spike 3 增加一项：升级 deepagents 小版本后旧 thread 的可恢复性；并在 §8 升级规则里加入"checkpoint 迁移检查" |
| U4 | P1 | §9 | Model Probe 给了门槛（单 Tool ≥95% / 2-step Loop ≥90% / schema 有效 ≥95%），但**没给样本量与重复次数**，不达标时的降级路径只有一句"允许独立模型 Provider" | 补：每档 ≥20 次重复；不达标时的决策树（换模型 / 降级为单 Tool / 停 Research Mode），并明确"独立 Provider"的密钥与配额从哪来 |
| U5 | P2 | §2 | "用户在 Nexus 中手动选择课程"——**课程列表 API 未指明** | 补一条 backend HTTP Contract：`GET /api/v1/nexus/courses` 返回当前用户有 `course.view` 的课程 |
| U6 | P2 | §15 + §27 | §15 说"总运行 ≤ 5 分钟"，§27 Gate R1 说"人工无法在 5 分钟内稳定完成则不进入自动化"——**两处 5 分钟口径是否含环境构建未统一** | 明确：5 分钟指**命令执行时间**，不含首次环境构建；首次构建单独给上限（建议 15–20 分钟） |
| U7 | P2 | §16 | `Nexus Product Session metadata → Existing Backend **或** 明确的 Nexus metadata store` —— "或"字未决 | 二选一。建议归 Existing Backend（便于产品侧查询与审计），Runtime 只存 thread/checkpoint |

---

## 四、超出当前工程范围的内容（4 项）

| 编号 | 位置 | 说明 | 建议 |
|---|---|---|---|
| S1 | §19 | Golden Set 要求的"Course 明显无关""内部知识均无答案"两类样本，在 **X2 未解决前无法构造**（没有 CS 检索就无法判定"内部知识无答案"） | 标注为"依赖 §5 Gate 通过后补充" |
| S2 | §23 | License 清单标了 `repo2docker → BSD-3-Clause`，但**未像 PaperPilot 那样标注"使用前再次核验"**；而 §20 的 L2 依赖它 | 给 repo2docker 加同样的核验标记；或明确 L2 为 P1 时再核验 |
| S3 | §14 + §29 | `authenticated job API`、`artifact whitelist`、Repro Worker control plane 均为**新建设施**，仓库无任何对应实现，不属于"复用现有能力" | 在排期上按新建计，不要归入 §12 的"Reuse Existing" |
| S4 | §20 + §26 + §27 | L2（Environment Rebuildability）在 §20 定义为 P0 非强制、§26 列入 P1、但 **§27 的 Gate R0–R5 序列里没有 L2 的位置** | 明确 L2 属 P1 且不在 R0–R5 内，避免智能体在 R4 阶段误做 L2 |

---

## 五、最小修改清单（按优先级）

1. **§2 补权限决策**（X1）——新增 `platform.nexus.use` 或强制绑定默认课程，二选一。这是全局 Nexus 能否成立的前提。
2. **§5 改为二元 Gate**（X2）——先判定 CS KB 索引是否存在，并预设三条出路；§26 的 `CS RAG` 加条件标注。
3. **§4 / §12 / §26 补 Web**（X3）——Web 与 arXiv 同类，只修了一半。
4. **§14 修正拓扑 + 单机隔离底线**（X4）——backend 是 systemd 宿主机 root 进程，不是容器；单机部署下的最低隔离要写进 §29。
5. **§16 拆 Artifact 归属 + §17 补迁移归属**（X5 / X6）——避免指向不存在的域。
6. **§1 写入实测基线值**（U1）——省掉每个智能体重复跑一遍。
7. **§3 写入 alembic 验证结论**（X7）——同样是一次性结论，值得固化。

---

## 六、值得保住的部分

补丁中以下五处是真正的工程判断，修订时不要削弱：

1. **§6** 主动撤回 v1.2 中未经验证的"LangGraph 不能升级"，改为诚实的风险取舍表述。这是全文档最专业的一处。
2. **§7** 把"独立 Runtime"从模块分目录严格化到独立 Python env / lockfile / process。
3. **§9** Model Capability Probe 前置于 Harness 实现，并给出量化门槛。
4. **§23** License 红线给出明确的禁止/允许边界，直接消灭了参考池里最危险的一项。
5. **§27** Gate R0–R5 的"先手工复现、再自动化、最后才引入 Agent Repair"顺序——这是 Quick Reproduction 唯一现实可行的推进路径。
