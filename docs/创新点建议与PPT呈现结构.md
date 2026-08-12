# 基于泛雅平台的 AI 互动智课系统 —— 创新点提炼与 PPT 呈现建议

> 适用场景：服务外包大赛 / 企业命题（A12 超星·泛雅）项目简介 PPT、项目详细方案、技术文档。
> 文档目的：从**真实代码架构**与**当前部署环境**出发，提炼可用于 PPT 与技术文档的创新点，并给出每个创新点的 PPT 呈现结构（标题 / 技术要点 / 对比图示 / 业务收益）。
> 数据来源：项目源码（`backend/app/platform/agents/`、`backend/app/domain/`、`deploy/`、`design.md`）、两份命题方 PDF、`.github/workflows/ci.yml`、`.env.example`。
> **诚实性约定**：本文所有"可量化指标"均标注来源；凡属**协议层 / 默认关闭 / 规划声称**且未在测试中验证的能力，单列于文末《诚实性声明与避坑清单》，**请勿在 PPT 中冒充已上线能力**。

---

## 0. 行业常规方案基准（PPT 对比的"那一边"）

命题方给出的"常规方案"画像（来自两份 PDF），就是我们做差异对比的锚点：

| 维度 | 行业常规 / 赛题基线 | 来源 |
|---|---|---|
| 系统形态 | 在泛雅平台之上做"课件解析→脚本生成→语音合成→问答→进度适配"的标准流程编排 | PDF2 开放 API 规范 §2 |
| 问答实现 | 单体接口 `/api/v1/qa/interact`，靠传入 `historyQa` 数组做上下文关联，理解程度仅 `none/partial/full` 三档 | PDF2 §2.2 |
| 安全实践 | MD5 签名防重放（5 分钟窗口）+ RBAC + HTTPS + AES-256 存储 + 日志保留 6 个月 | PDF2 §1.4 / §4 |
| 技术指标 | 问答 ≤5 秒、解析 ≤2 分钟/份、知识点识别 ≥80%、答案准确率 ≥85%、并发 ≥10 人 | PDF1 任务要求 |
| 部署形态 | 服务器端 8 核 / 16G / 500G，单套常规设备 | PDF1 系统资源要求 |
| 评分权重 | **技术创新性 ★★★（最重）** > 场景适配性 ★★ > 功能完整性 ★★ > 落地可行性 ★ | PDF1 评分要点 |

**核心叙事逻辑**：超星开放 API 定义的是"标准契约（what）"——接口、签名、数据格式；而本系统是在这一标准契约之上，自建了"可治理的智能体工程实现层（how）"。所有创新点都围绕"在标准壳之上做了哪些远超常规的深度突破"展开。

---

## 1. 核心创新点（主推 3 个，对齐赛题"创新要点不超过 3 个"）

> 建议 PPT 用这 3 个作为主弹药，每个占 1–2 页；其余支撑点作 1 页汇总。

### 创新点 1：从"单点大模型调用"到"可治理的多智能体教学引擎"

**代码层技术突破**
- **三智能体物理分离**：`backend/app/platform/agents/` 下 `edu/`（教学问答）、`prep/`（备课）、`coding/`（代码诊断）各自拥有独立的 `state.py`（frozen dataclass）/ `profile.py` / `composition.py`，互不耦合。
- **LangGraph 图编排**：`edu/workflow.py` 的 `build_teaching_workflow()` 编排 **20 个节点**（validate_request → detect_intent → resolve_concept → … → validate_response → record_learning_event）；`coding/workflow.py` 为 **3 节点**（sandbox → diagnosis → response）。LLM 仅在少数节点调用，可控分支、治理闸门、降级、审计全部下沉到节点。
- **Fail-closed 降级**：每个节点独立 `try/except`，异常时走 `_degrade()` 并记录 `degraded_services`，`BaseAgentRuntime.run()` 永不对调用方抛异常——单点 LLM 故障不拖垮全链路。
- **Tool 自校验 + 治理闸门**：每个 Tool 节点前插入 `ToolGovernance`（`_governance_check`），权限校验下沉到工具本身，而非依赖调用方传参。
- **Port / Provider / Contracts 隔离**：`contracts/` 下 **10 个 Protocol** 定义协作边界，Agent 间**不共享可变状态**（Edu 读 Coding 诊断仅经 `CodingDiagnosisPort` 只读接口，且"must never be converted into LearningEvidence"）。`providers/container.py` 按 Mode A 每方法自建 Session，绝不持有全局活 Session。
- **按 course/student 创建 Runtime**：`BaseAgentRuntime` 由 `AgentProfile` 按 `AgentRunContext` 构建初始状态，**非全局共享 LLM 客户端**。
- **并发隔离**：`runtime/concurrency.py` 的 `AgentConcurrencyLimiter` 按 **agent 类型**建 `asyncio.Semaphore`，超限在 **1.0s 宽限窗**内取不到才抛错，避免无限阻塞。

**行业对比（差异与优势）**
- 常规方案：单体 LLM 接口 / 单一 Prompt / 直接调大模型，无治理、无降级、无审计闸门。超星 API 把问答抽象为单接口传 `historyQa`。
- 本系统：可控分支 + 治理闸门 + 降级 + 审计内建到图节点，回答**可控、可审计、可降级**，天然契合教育场景的合规与稳定性要求。

**可量化指标**
- 20 节点教学工作流 / 3 节点代码诊断工作流（源码可数）
- 10 个 Port 契约（README 3.1）
- 1.0s 并发宽限窗（`concurrency.py:96`）

**PPT 呈现结构**
- **标题**：从"单点大模型调用"到"可治理的多智能体教学引擎"
- **技术要点**：① 三 Agent 物理分离；② LangGraph 20 节点图编排；③ 节点级 Fail-closed 降级；④ ToolGovernance 自校验；⑤ Port/Contracts 隔离、Runtime 按课程/学生创建
- **对比图示**（建议画左右架构图）：
  - 左（常规）：`客户端 → 单一 Prompt → LLM`，标注"无治理 / 无降级 / 黑盒"
  - 右（本系统）：`请求 →[ScopeValidator]→[意图识别]→[知识解析]→ … →[教师策略]→[响应]`，每个节点标注"治理闸门 + 降级 + 审计"
- **业务收益**：① 回答可控可审计，满足教育合规；② 单点 LLM 故障不影响全链路；③ 多 Agent 可独立演进、独立测试

---

### 创新点 2：从"拼上下文"到"可证据追溯的知识图谱与掌握度引擎"

**代码层技术突破**
- **教育知识图谱结构化校验**：`domain/education_graph/validation.py` 实现 **14 种关系 × 节点类型矩阵**（`_TYPE_MATRIX`），`validate_relation` 区分硬约束（REJECT）与软约束（NEEDS_REVIEW，不自动删高价值证据）；`detect_prerequisite_cycle` 用**白/灰/黑三色 DFS** 检测先修环。图谱内置 **8 种教育关系**（README 2.1）。
- **不可变快照 + 版本对比 / 回滚**：`services/graph_production_service.py` 的 `publish_snapshot` / `get_active_snapshot` / `diff_snapshots` / `rollback_snapshot`（置 `ROLLED_BACK`），`prev_snapshot_id` 链式版本，Schema 含 `DRAFT/PUBLISHED/SUPERSEDED/ROLLED_BACK` 状态。
- **证据驱动的掌握度**：`domain/learning/mastery_state.py` 的 `MasteryState` 强制 `evidence_refs` 非空（UNKNOWN 除外），掌握结论必须可回溯到证据。
- **结构化推理信号（隐私安全）**：`services/conversation_service.py:150` 的 `derive_question_inference_signals()` 按 concept 聚合近 `lookback_days` 提问，计算 `avg_inquiry_depth`、`inferred_weak = avg_depth < 阈值`——**只返回 trace_id 列表，不返回原始问题全文**。

**行业对比（差异与优势）**
- 常规方案：超星 API 问答靠 `historyQa` 传入做上下文关联，理解程度仅 `none/partial/full` 三档粗粒度；主流 RAG 是"向量检索拼上下文"的黑盒。
- 本系统：图谱把知识点关系**结构化、可校验、可回滚**；弱项定位来自**结构化投影信号**而非依赖黑盒 LLM 或泄露原文；掌握度结论**必须挂证据**。

**可量化指标**
- 8 种教育关系 / 14× 关系校验矩阵
- 11 类 gold benchmark 含 **Recall@k / MRR / nDCG**（`tests/benchmarks/product1/gold/README.md`）
- 不可变快照 + 链式版本回滚

**PPT 呈现结构**
- **标题**：从"拼上下文"到"可证据追溯的知识图谱引擎"
- **技术要点**：① 8 关系 + 14× 校验矩阵 + 三色环检测；② 图谱快照不可变、可 diff、可回滚；③ 掌握度强制 evidence_refs；④ 推理信号仅返回 trace_id（隐私安全）
- **对比图示**（建议画"黑盒 vs 白盒"）：
  - 左（常规 RAG）：`问题 → 向量检索 → 拼上下文 → LLM → 答案`（标注"关系不可见 / 不可回滚 / 弱项靠猜"）
  - 右（本系统）：`问题 → 知识图谱(关系矩阵+环检测) → 证据约束掌握度 → 结构化推理信号 → 答案`（标注"关系可审 / 版本可回滚 / 弱项可定位"）
- **业务收益**：① 精准定位学生薄弱点；② 课件知识关系可审计、可回溯；③ 图谱版本出错可一键回滚

---

### 创新点 3：从"合规加密"到"默认最小化"的隐私与安全工程

**代码层技术突破**
- **审计数据最小化**：`domain/safety/audit.py` 的 `AuditEvent` 将 `user_content_snippet` **截断至 100 字符**（`__post_init__:99`），`metadata` 禁存密钥/全文；`AuditSink` 抽象层解耦落库。
- **三域数据隔离**：Runtime/Audit 域、Conversation 域、学习分析域**相互隔离**；学习分析只消费 `derive_question_inference_signals` 的结构化投影（仅 trace_id），**不直接读对话原文**。
- **独立保留周期**：Conversation 默认 **90 天**保留与过期清理。
- **代码执行沙箱隔离**：学生代码经独立 **Judge0 沙箱**执行，绝不进入主应用进程（`coding/workflow.py` 明确"诊断仅为教学上下文、永不写入 LearningEvidence"）。沙箱 **非 privileged**，仅 `cap_add: SYS_ADMIN` + `no-new-privileges`。
- **签名防重放 + Fail-closed 灰度**：`core/signature_middleware.py` 用 MD5 签名 + `SIGN_TIMEOUT_MINUTES`（默认 **5 分钟**窗口）防重放；`feature_flags` 新管线默认 `v1_only`，非法 flag 值 **fail-closed**。

**行业对比（差异与优势）**
- 常规方案（超星 API §4）：MD5 签名 + RBAC + HTTPS + AES-256 存储 + 日志保留 6 个月——属"合规加密"层面。
- 本系统：在合规之上做**数据最小化工程**——审计不存全文、三域物理隔离、代码沙箱隔离执行、开关 fail-closed。把"隐私保护"从"加密存储"升级为"默认不收集/不留存敏感原文"。

**可量化指标**
- 审计 snippet **100 字符**截断
- Conversation **90 天**保留窗口
- 签名防重放 **5 分钟**窗口
- 沙箱 **非 privileged**、pids 硬限制

**PPT 呈现结构**
- **标题**：从"合规加密"到"默认最小化"的隐私工程
- **技术要点**：① 审计截断 100 字符 + 三域隔离；② 推理仅消费 trace_id 投影；③ Judge0 独立沙箱、代码不进主进程；④ 签名防重放 5 分钟窗口 + fail-closed 灰度
- **对比图示**（建议画"数据流向"对比）：
  - 左（常规）：`对话原文 → 加密存储 → 长期留存`（标注"全文留存 / 单域"）
  - 右（本系统）：`原文 → 截断审计 + 三域隔离 → 90 天过期 / 沙箱执行代码`（标注"最小化 / 隔离 / 可销毁"）
- **业务收益**：① 满足《个人信息保护法》最小化原则；② 学生代码安全执行、主机不被拖垮；③ 审计可过合规检查、降低数据泄露面

---

## 2. 支撑创新点（简版，建议 PPT 用 1 页汇总或按需展开）

### 创新点 4：可重入数据库迁移 + 业务级非破坏回滚
- **技术要点**：`alembic` **48 个**迁移脚本；回填类迁移用 `migration_batch_id` 标记，回滚 `DELETE WHERE migration_batch_id` 干净撤销；`course_build_service.rollback_to_release` / `media_release_service.rollback_to_release` **非破坏**——旧版标 `ROLLED_BACK/SUPERSEDED`，基于历史内容新建 version+1 激活。
- **行业对比**：常规 `create_all` 裸建表 / 手工 SQL，无版本、无审计、无精确回滚。
- **量化**：48 迁移脚本；batch 标识回滚。
- **PPT 对比图示**：左"手工 SQL / 裸建表（无回滚）" vs 右"版本化迁移 + batch 回滚 + 业务级非破坏回滚"。
- **业务收益**：线上结构变更可审计、可精确回退，发布更稳。

### 创新点 5：Shadow / Canary / Evidence 质量护栏
- **技术要点**：`tests/{shadow,canary,evidence}/`；Canary 覆盖 **6 条**影子路径（doc/evidence/graph/learning/memory/safety），硬性不变量 `llm_calls=0`、quality gate PASS；gold benchmark **11 类**含 `Recall@k / MRR / nDCG / memory_privacy`；CI 门禁（ruff + pytest `--timeout=60` + API 契约测试 + 构建）。
- **行业对比**：纯手工发布、无回归护栏。
- **量化**：6 金丝雀路径；11 类基准；CI 后端 15min / 前端 10min 超时。
- **PPT 对比图示**："发布流水线"图：代码 → lint → 契约测试 → 金丝雀比对(llm_calls=0) → 构建，标注"每合入主干必过护栏"。
- **业务收益**：合入即验证、回归可防、AI 行为变更可比对。

### 创新点 6：声明式容器编排 + 资源硬隔离
- **技术要点**：`deploy/docker-compose.yml` 多栈编排（backend + paddleocr + postgres + redis + neo4j + frontend/nginx），`depends_on.condition: service_healthy` 控启动顺序；Judge0 独立栈经 `127.0.0.1:2358` 解耦；paddleocr 资源封顶 **2 CPU / 3G**（预留 1G）；Judge0 各组件 CPU/内存/pids 硬限制（`0.5/1.5/0.5/0.25 CPU`，`512/1536/512/128M`，pids `256/256/256/128`）；nginx 反代 `proxy_read_timeout 600s`、`client_max_body_size 110m`、平台同步接口内网 IP 白名单。
- **行业对比**：手动部署 / 单体容器无资源限制，易单服务拖垮主机。
- **量化**：资源硬限制数值（见上）；健康检查间隔（paddleocr 15s/60s/5；Judge0 30s/60s/3）。
- **PPT 对比图示**："单机容器拓扑"图 + 资源封顶标注；左"无限制单体" vs 右"按服务封顶 + 独立沙箱栈"。
- **业务收益**：一条 `docker compose up -d` 拉起全栈；单服务资源越界不影响主机；沙箱隔离降安全风险。

### 创新点 7：统一前端设计体系与智能体面板
- **技术要点**：`design.md` v0.4 为唯一视觉权威；`tokens.css` + `base.css` 与令牌 **1:1**；**三层滚动模型**（AppShell `100dvh; overflow:hidden` → main 滚动 → 页面内部 `min-height:0`）；**禁用原生 `<button>`，强制 `SfxButton`**；页面过渡 `--duration-fast:120ms` + `prefers-reduced-motion` 降级 **0.01ms**；`stageActions` 机制；助教智能体面板独立滚动；§11 已删除组件清单（明确禁止恢复散落组件）。
- **行业对比**：无设计令牌、散落组件、原生 button 混用、整页滚动抖动。
- **量化**：令牌 1:1 映射；120ms 过渡 + 无障碍降级。
- **PPT 对比图示**：左"散落组件/原生 button/整页滚动" vs 右"设计令牌 1:1 / SfxButton 统一 / 三层滚动 / 智能体面板"。
- **业务收益**：视觉一致、可维护、无障碍合规、智能体交互体验统一。

---

## 3. 可量化指标汇总表（供 PPT 直接引用，均标注真实性）

| 指标 | 数值 | 真实性标注 | 来源 |
|---|---|---|---|
| 教学智能体工作流节点数 | 20 | ✅ 可验证（源码） | `edu/workflow.py` |
| 代码诊断工作流节点数 | 3 | ✅ 可验证 | `coding/workflow.py` |
| Port 契约数量 | 10 | ✅ 可验证 | README 3.1 |
| 教育知识图谱关系类型 | 8 | ✅ 可验证 | README 2.1 |
| 关系校验矩阵 | 14× 节点类型 | ✅ 可验证 | `education_graph/validation.py` |
| 算法可视化白名单 | 11 种 | ✅ 可验证 | `visualization/algorithm_registry.py` |
| 金丝雀影子路径 | 6 条 | ✅ 可验证 | `tests/canary/` |
| Gold benchmark 类别 | 11 类（含 Recall@k/MRR/nDCG） | ✅ 可验证 | `tests/benchmarks/product1/gold/` |
| Alembic 迁移脚本 | 48 个 | ✅ 可验证 | `backend/alembic/versions/` |
| 审计 snippet 截断 | 100 字符 | ✅ 可验证 | `safety/audit.py` |
| Conversation 保留周期 | 90 天 | ✅ 可验证 | `conversation_service.py` |
| 并发宽限窗 | 1.0s | ✅ 可验证 | `runtime/concurrency.py` |
| 签名防重放窗口 | 5 分钟 | ✅ 可验证 | `signature_middleware.py` |
| OCR 资源上限 | 2 CPU / 3G（预留 1G） | ✅ 可验证 | `docker-compose.yml` |
| Judge0 资源上限 | 0.5/1.5/0.5/0.25 CPU，512/1536/512/128M | ✅ 可验证 | `judge0/docker-compose.yml` |
| CI 超时（后端/前端） | 15min / 10min | ✅ 可验证 | `.github/workflows/ci.yml` |
| 单测超时 | 60s | ✅ 可验证 | `ci.yml` |
| 赛题对标：问答响应 ≤5s / 解析 ≤2min | 赛题基线 | ⚠️ 架构支撑，未测 p95 | PDF1 |
| 赛题对标：知识点准确率 ≥80% / 答案 ≥85% | 赛题基线 | ⚠️ 有 benchmark 框架，未出实测报告 | PDF1 + gold |

> ⚠️ **重要**：端到端延迟（p95/p99）、QPS、并发上限具体值、测试覆盖率百分比、镜像体积/构建耗时、回滚耗时（秒）——**在代码与文档中均未找到实测记录**，请勿在 PPT 编造。建议以"架构可支撑赛题指标"表述，或标注"实测进行中"。

---

## 4. PPT 整体编排建议（页级大纲，约 10–12 页）

1. **封面**：题目 + 一句话定位（"在标准泛雅 API 之上，自建可治理的 AI 智课引擎"）。
2. **场景与痛点**：引用 PDF1 痛点（静态课件、互动缺失、个性化不足）+ 赛题技术指标。
3. **行业常规方案基准**：用 §0 表格，点明"超星开放 API = 标准契约层"，引出"我们要在 how 上突破"。
4. **核心创新 1**：多智能体教学引擎（§1 创新点 1 结构）。
5. **核心创新 2**：知识图谱与掌握度引擎（§1 创新点 2 结构）。
6. **核心创新 3**：隐私最小化工程（§1 创新点 3 结构）。
7. **支撑创新汇总**：迁移回滚 / 质量护栏 / 容器编排 / 前端体系（§2 四合一页）。
8. **量化指标墙**：用 §3 表格做成"指标卡片墙"，突出可验证数字。
9. **落地与部署**：Docker Compose 一键拉起、资源硬隔离、CI 门禁（对齐赛题"落地可行性 ★"）。
10. **路线图 / 演进**（诚实呈现规划能力，见 §5）。
11. **结尾**：呼应评分要点（技术创新性 ★★★ 为主轴）。

---

## 5. 诚实性声明与避坑清单（务必读，避免 PPT 夸大翻车）

以下能力**已在代码中定义/协议化/默认关闭**，但**未作为运行时已启用的量化能力验证**，建议放入"路线图/演进"页，而非"已落地成果"页：

| 能力 | 真实状态 | PPT 建议 |
|---|---|---|
| 检查点恢复（Checkpoint） | `runtime/checkpoint.py` 仅 `CheckpointPort` 协议 + `NullCheckpointPort`，**未接实现** | 列为"规划中"，不要说"已支持断点续跑" |
| BKT / IRT / DKT 掌握度 | `MasterySource` 仅接口，真实实现为 `rule_baseline` | 表述为"掌握度框架已落地，先进算法待接入" |
| 真实 GraphRAG 构图 | `GRAPHRAG_ENABLED=false` **默认关闭** | 表述为"图谱检索可启用"，不要冒充"已全量构图" |
| Judge0 真实启用 | `JUDGE0_ENABLED=False` **默认禁用**（bootstrap 已注入真实沙箱，但需开启） | 表述为"沙箱已集成、可启用"，不要说"当前在处理真实代码" |
| 规划文档声称的"备课时间 −37% / 文献效率 +58% / 成功率 90%" | 属 `docs/赛题差距分析与重构建议.md` **规划声称**，未在测试/日志中找到可验证证据 | **不要在 PPT 写为已达成效果**；可写"目标/预期" |
| 端到端 p95/p99 延迟、QPS、覆盖率 | 无 coverage 报告 / 无基准实测 | 以"架构支撑赛题指标"表述，或标注"实测进行中" |

**一句话原则**：PPT 讲"我们做了什么工程"（可验证的架构、隔离、护栏、回滚、令牌体系）比讲"我们达到了什么夸张数字"更可信、更经得起答辩追问。把"已落地"与"规划中"分清楚，恰恰是专业性的体现。
