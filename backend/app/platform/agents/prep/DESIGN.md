# 助教智能体（Prep Agent）设计文档

> Phase 4 实施基线。本文档固化三链路统一架构：共享基础设施，不共享业务状态机。

> 2026-07-31 实现状态：Incremental 与 PPT Mapping 已接入
> `AgentGateway`；运行事件与运行状态当前仍使用 Null Port，尚无 SQL
> `AgentRunStore`、事件表或 SSE 断线续传端点。下文相关章节是目标设计，
> 不应据此声明当前已具备持久化进度流或恢复能力。

> 2026-07-31 批量编辑补充：场景 2/4 使用一次课程级 LLM 规划，输入为全部未锁定
> 草稿目录层级与讲稿原文；它们不是逐 20 节点的独立分块。超过 500 个可编辑目标时
> 失败关闭，避免截断或部分应用。单点场景仍保留 SQL 证据检索与待审核 Proposal。

## 一、定位与核心原则

**定位**：Prep Agent 是教师侧的备课智能体，覆盖首次课程生成、增量草稿修改、PPT 映射优化三类场景。

**核心原则**：

> 统一的是运行机制、治理和依赖装配，不统一三个 Workflow 的业务状态与执行路径。

- 三个 Workflow 共享：Runtime、ProviderContainer、StructuredLLMPort、AgentRunStore、事件系统、审计、错误体系
- 三个 Workflow 不共享：State、Dependencies、执行模式、超时、持久化入口、领域业务 Service

## 二、Capability（用户可见功能）

### 6 个场景

| # | 场景 | 目标对象 | 范围 | 执行模式 | Workflow |
|---|------|---------|------|---------|----------|
| 1 | 初始化课件解析与生成讲解稿 | outline + scripts | 全量新建 | QUEUED | InitialBuildGraph |
| 2 | 知识点一键全部优化 | outline.title | 全量增量 | INLINE | IncrementalEditGraph |
| 3 | 知识点选中优化 | outline.title | 单个增量 | INLINE | IncrementalEditGraph |
| 4 | 所有讲解稿一键优化 | script.content | 全量增量 | INLINE | IncrementalEditGraph |
| 5 | 讲解稿节点选中优化 | script.content/style | 单个增量 | INLINE | IncrementalEditGraph |
| 6 | PPT映射OCR匹配优化 | ppt_mapping | 全量增量 | INLINE | PptMappingOptimizationGraph |

场景 2 与场景 4 由教师点击一键动作即完成授权：系统在完整覆盖校验后直接更新草稿，
同时保存状态为 `accepted` 的 PatchProposal 审计记录，不进入待审批列表。场景 3 与
场景 5 仍生成 `pending` PatchProposal，由教师显式接受或拒绝。

### 场景 2-5 的参数区分

场景 2-5 使用同一个 Workflow（IncrementalEditGraph），通过调用参数区分：

| 场景 | outline_node_id | instruction 示例 | LLM 行为 |
|------|----------------|-----------------|---------|
| 2 | None + action=organize_structure | 固定受控指令 | 每个未锁定节点恰好一个 outline.title operation |
| 3 | "node_xxx" | "优化这个知识点" | 生成单个 outline.title operation |
| 4 | None + action=optimize_scripts | 固定受控指令 | 每个未锁定讲稿恰好一个 script.content operation |
| 5 | "node_xxx" | "优化这个讲解稿" | 生成单个 script.content operation |

全量动作由受控 `action` 字段区分，不能依赖 LLM 猜测指令意图；单节点自然语言命令
仍由指令与选中节点共同限定目标。

## 三、架构总览

```text
AgentGateway
    │
    ├── graph_kind=initial
    │       ↓ (durable Worker resolves the registered runtime)
    │   InitialBuildGraph
    │       ↓
    │   InitialCoursePrepPort.build()
    │       ↓
    │   InitialCoursePrepService.build()  ← 完整应用服务，含持久化
    │       ↓
    │   ControlledPrepWorkflow.run(on_stage)
    │       ↓
    │   返回 DraftAssetResult（已持久化）
    │
    ├── graph_kind=incremental
    │       ↓ (INLINE)
    │   IncrementalEditGraph
    │       ↓
    │   IncrementalPrepPort.plan() / plan_batch()
    │       ↓
    │   CoursePrepAgentService.plan()  ← 只返回 AgentPlan，不持久化
    │       ↓
    │   返回 CoursePrepAgentResult（endpoint 层保存 PatchProposal）
    │
    └── graph_kind=ppt_mapping
            ↓ (INLINE)
        PptMappingOptimizationGraph
            ↓
        PptMappingOptimizationPort.optimize_mappings()
            ↓
        PptMappingOptimizationService  ← 新建，直接更新 CoursePptMapping
            ↓
            返回优化结果摘要
```

### 共享 vs 不共享

| 共享 | 不共享 |
|------|--------|
| StructuredLLMPort | State |
| Prompt Registry | Dependencies |
| AgentRunStore | Runtime Definition |
| AgentRunEventStore | Execution Mode |
| SSE | Timeout |
| 审计 | 持久化入口 |
| 错误体系 | 领域业务 Service |

## 四、State 设计

### 设计原则

1. **不使用大而全的统一 PrepState**：每个 Workflow 有独立 State
2. **不与 RuntimeMeta 重复**：公共字段只存在于 `meta` 中
3. **包装模式下 State 保持简洁**：中间结果不进入 State（在 Service 内部）

### PrepCommonState（共享基类）

```python
class PrepCommonState(TypedDict, total=False):
    meta: RuntimeMeta
    graph_kind: PrepGraphKind
```

### InitialPrepState

```python
class InitialPrepRequestState(TypedDict):
    teacher_id: str
    course_id: str
    corpus_snapshot_id: str
    build_task_id: str | None

class PrepProgressState(TypedDict, total=False):
    stage: str
    progress: int
    message: str | None

class InitialPrepResultState(TypedDict, total=False):
    outline_version_id: str
    script_version_id: str
    graph_candidate_batch_id: str
    warnings: list[str]

class InitialPrepState(PrepCommonState, total=False):
    request: InitialPrepRequestState
    progress: PrepProgressState
    result: InitialPrepResultState
```

### IncrementalPrepState

```python
class IncrementalPrepRequestState(TypedDict):
    teacher_id: str
    course_id: str
    instruction: str
    outline_node_id: str | None

class IncrementalPrepContextState(TypedDict, total=False):
    editable_target_ids: list[str]
    excluded_locked_targets: list[str]
    allowed_evidence_ids: list[str]

class IncrementalPrepResultState(TypedDict, total=False):
    summary: str
    operations: list[dict]
    evidence: list[dict]
    planner: str

class IncrementalPrepState(PrepCommonState, total=False):
    request: IncrementalPrepRequestState
    context: IncrementalPrepContextState
    result: IncrementalPrepResultState
```

### PptMappingState

```python
class PptMappingRequestState(TypedDict):
    teacher_id: str
    course_id: str
    material_version_id: str

class PptMappingResultState(TypedDict, total=False):
    total_mappings: int
    updated_count: int
    suggestions: list[dict]

class PptMappingState(PrepCommonState, total=False):
    request: PptMappingRequestState
    result: PptMappingResultState
```

## 五、Workflow 设计

### 总览

| Workflow | 节点数 | 包装对象 | 持久化 | LLM 阶段 |
|---------|--------|---------|--------|---------|
| InitialBuildGraph | 1 | InitialCoursePrepService.build() | Service 内部 | 有界 Evidence Map/Reduce + 大纲 + 讲稿 + 校验 + 确定性编译 |
| IncrementalEditGraph | 1 | CoursePrepAgentService.plan()/plan_batch() | endpoint 层 | 1 Prompt，批量为单次课程级上下文 |
| PptMappingOptimizationGraph | 1 | PptMappingOptimizationService | Service 内部 | 1 Prompt |

### Workflow 1：InitialBuildGraph

```text
执行模式：QUEUED（Worker）
超时：900s（每次外部 LLM 调用另受 240s 上限约束）
并发：3
节点：execute_initial_build
    ↓
InitialCoursePrepPort.build(
    teacher_id, course_id, corpus_snapshot_id,
    build_task_id, on_stage=stage_emitter.callback,
    replace_unreviewed_initial=teacher_restart_flag,
)
    ↓
返回 DraftAssetResult
```

**持久化**：Service 内部完成（outline/scripts/ppt/graph 全部持久化）。Graph 不触碰持久化。

**材料证据整理（2026-08-09）**：`InitialCoursePrepService` 先在页内把 OCR/解析碎块合并成稳定证据单元，保留服务端 `source_block_ids`；`ControlledPrepWorkflow` 以正文 24,000 字、完整载荷 36,000 字为单批上限执行 Map，并发 2，随后只对摘要和证据单元 ID 做层级 Reduce。模型不接收原始块 ID；工作流全部成功后，Service 才将证据单元 ID 展开为真实 `DocumentBlock.block_id` 并持久化。Map 截断递归二分，材料整理总调用预算 64。Reduce prompt 与 JSON Schema 均要求每个 segment 的 `examples`、`exercises` 各不超过 10 项；Reduce 专用线格式会在正式 `EvidenceSegmenterResult` 校验前对这两个非事实列表稳定去重、去空并裁剪，避免模型修复重试仍超限导致整课失败。segment 数量、身份、证据 ID 与其他字段不做宽松归一化；任何剩余错误仍不写入课程草稿。

**材料证据整理 v2（2026-08-09）**：层级 Reduce 的**中间层改为瘦合并**——只输出 `title/topic`（`LeanEvidenceReduceResult`），`examples/exercises` 延后到最后一级才生成；二者无下游消费者（大纲只用证据 ID，讲稿用证据原文），此前逐级携带导致中间层响应 `finish_reason=length` 并烧掉调用预算。最后一级仍走完整线格式并保持既有去重/裁剪归一化。预算同步从 40 提升到 64。并发执行改为"首个异常即取消在途 sibling"（`ControlledPrepWorkflow._run_concurrent`），避免预算耗尽后残留 LLM 请求继续运行。

**材料证据整理 v3：证据 ID 程序回填（2026-08-09）**：LLM 在 Map/Reduce 阶段曾幻觉出不存在的 `evg_...` ID，硬门会正确拒绝但直接终止任务。为从根上消除该风险，**所有 Initial 阶段的 LLM 输出与输入都不再包含 `evidence_id / evidence_ids / evidence_refs / paragraph_evidence`**（wire schema 全都不带这些字段，`EvidenceReference.llm_payload()` 也不再下发 evidence_id），证据归属一律由 `PrepLLMAdapter` 按确定性输入范围回填：

- Map：每个输出段回填**整个输入批次**的证据 ID；
- Reduce：每个合并段回填**参与合并分段的确定性并集**；
- 大纲候选/prerequisite：回填**全部输入分段证据的并集**，并按粗到细顺序截断到 ≤100（对齐 `PatchOperationDraft.evidence_refs` 上限）；
- 讲稿：`evidence_ids` 取自其绑定的大纲候选（≤100），`paragraph_evidence` 按段落数回填同一证据集以保持对齐校验；
- 校验：每个 finding 回填该讲稿的证据集。

由此代价是证据粒度绑定到"输入分段/材料组"，不再由模型声明"哪句话精确来自哪条证据"；审计仍保留（服务端展开 `block_id`）。讲稿/校验 prompt 的输入证据改为程序侧粗到细有界抽样（`PREP_INITIAL_SCRIPT_EVIDENCE_MAX_CHARS`，默认 24,000 字符），避免大纲节点全量引用后把整本材料塞进每次讲稿请求。增量链路（`plan_incremental` 的 AgentPlan operations）仍保留模型侧 `evidence_refs`，受既有白名单校验与 fail-closed 约束，作为后续统一项。

### Workflow 2：IncrementalEditGraph

```text
执行模式：INLINE
超时：120s
并发：10
节点：execute_incremental_plan
    ↓
IncrementalPrepPort.plan(course_id, instruction, outline_node_id)
    ↓
返回 CoursePrepAgentResult（summary + operations + evidence）
```

**持久化**：单节点命令由 endpoint 创建 pending PatchProposal；全量一键动作在完整
校验后直接应用，并创建 accepted PatchProposal 作为审计记录。Graph 不持久化。

### Workflow 3：PptMappingOptimizationGraph

```text
执行模式：INLINE
超时：60s
并发：5
节点：optimize_ppt_mappings
    ↓
PptMappingOptimizationPort.optimize_mappings(course_id, material_version_ids)
    ↓
返回 PptMappingOptimizationResult
```

**持久化**：Service 内部直接更新 CoursePptMapping（status=draft）。每份当前 PPT
材料版本独立匹配并携带 material_version_id，页码不跨文件复用；所有材料的 LLM
计算完成后一次提交。不创建 PatchProposal。不修改 teacher_locked=True 的映射。

## 六、Port / Provider / Tool 映射

### 核心特征：Prep 不需要 LLM-facing Tools

| 对比 | Edu | Prep |
|------|-----|------|
| LLM 选择工具 | 是 | **否**（Workflow 确定性） |
| ToolCatalog | 需要 | **不需要** |
| ToolInvoker | 需要 | **不需要** |
| Dependencies | Workflow + LLM 共用 | **仅 Workflow 确定性调用** |

Prep 只有 Port + Provider，没有 LLM-facing Tool。

### 层次关系

```text
Dependencies (Port 组合)
    ↓
Port (协议)
    ↓
Provider (实现)
    ↓
Service 或 DB/LLM
```

### 共享 Port（CommonPrepDependencies）

| Port | 职责 | Provider 实现 |
|------|------|-------------|
| StructuredLLMPort | 底层结构化 LLM 调用 | SharedLLMStructuredProvider（已有） |
| AgentRunStorePort | 运行状态持久化 | SqlAgentRunStorePort / NullAgentRunStore |
| AgentRunEventPort | 事件流持久化 + SSE | SqlAgentRunEventPort / NullAgentRunEventPort |

结构整理使用稀疏 `StructurePlan`：模型只返回确实需要调整的节点，空
`operations` 表示 `no_change`。服务端补齐 before/target/policy 字段并继续
执行树结构、锁定节点、证据引用和原子事务校验。每次运行的状态、事件和
LLM 诊断写入 `agent_run_records`、`agent_run_event_records`、
`agent_llm_diagnostic_records`；诊断不保存 prompt、模型原文或课程全文。

### Initial 专用 Port

| Port | 职责 | Provider 实现 |
|------|------|-------------|
| InitialCoursePrepPort | 首次备课应用服务入口 | InitialCoursePrepProvider（包装 InitialCoursePrepService） |

### Incremental 专用 Port

| Port | 职责 | Provider 实现 |
|------|------|-------------|
| IncrementalPrepPort | 增量修改入口（不持久化） | IncrementalPrepProvider（包装 CoursePrepAgentService） |

### PptMapping 专用 Port

| Port | 职责 | Provider 实现 |
|------|------|-------------|
| PptMappingOptimizationPort | PPT 映射优化入口 | PptMappingOptimizationProvider（包装 PptMappingOptimizationService） |

### Provider 实现清单

| Provider | 文件 | 包装对象 |
|---------|------|---------|
| InitialCoursePrepProvider | providers/prep/initial_course_prep.py | InitialCoursePrepService |
| IncrementalPrepProvider | providers/prep/incremental_prep.py | CoursePrepAgentService |
| PptMappingOptimizationProvider | providers/prep/ppt_mapping_optimization.py | PptMappingOptimizationService |

### DB 操作不提取为 Port

包装模式下 Graph 不直接调用 DB 操作。Service 内部的 DB 读写保持不变，不提取为 Port，避免在 Graph 层创建平行 DB 接口。

## 七、Worker 策略

### 执行模式分配

| Workflow | 执行模式 | Worker | 理由 |
|---------|---------|--------|------|
| InitialBuildGraph | QUEUED | PrepWorker | 分钟级长任务（4 阶段 LLM） |
| IncrementalEditGraph | INLINE | 无 | 秒级（单轮 LLM < 30s） |
| PptMappingOptimizationGraph | INLINE | 无 | 秒级（单轮 LLM < 30s） |

### 崩溃恢复策略

**当前版本诚实定义为"从头重试"**，不声称阶段恢复。

- Worker 崩溃 → 任务重新从头执行
- 依赖 build_task_id 幂等
- 不会重复创建 Proposal（Service 内部幂等检查）
- 不会覆盖已审核内容（Service 内部检查）
- AgentRunStore 负责描述运行状态，TaskQueue 负责确保任务被执行

### Queue 与 AgentRunStore 职责分离

| 组件 | 职责 |
|------|------|
| AgentRunStore | 描述运行状态（status/progress/result） |
| TaskQueue | 确保任务被执行（lease/heartbeat/retry/dead-letter） |

不让一张表同时当病历和救护车。

## 八、Prompt 设计

### PromptSpec 对象化

```python
@dataclass(frozen=True)
class PromptSpec:
    name: str
    version: str
    system_template: str
    output_schema_version: str
```

每次 LLM 调用记录：prompt_name、prompt_version、output_schema、output_schema_version、model_profile。

### Prompt 清单

首次备课仍是 5 个业务阶段；证据阶段内部使用 Map 与 Reduce 两个 PromptSpec，其后是大纲、讲稿、证据校验和确定性编译。增量修改与 PPT 映射优化保持独立 Prompt。

| # | PromptSpec | 阶段 | 链路 |
|---|-----------|------|------|
| 1 | prep.evidence_segmenter v2.1 | 有界证据 Map（模型不返回证据 ID） | Initial |
| 2 | prep.evidence_reducer v1.3 | 层级证据 Reduce（中间层瘦合并、末级补全 examples/exercises、不返回证据 ID） | Initial |
| 3 | prep.outline_planner v2.1 | 目录规划（最多 24 知识点/64 节点，不返回证据 ID） | Initial |
| 4 | prep.script_writer / batch v1.2 | 讲稿撰写（不返回证据 ID / paragraph_evidence） | Initial |
| 5 | prep.evidence_verifier v1.2 | 证据校验（不返回证据 ID） | Initial |
| 6 | prep.incremental_planner v2.0 | 增量规划 | Incremental |
| 7 | prep.ppt_mapping_optimizer v1.1 | PPT映射优化 | PptMapping |

`compile_patch` 阶段是确定性编译，无 Prompt。

## 九、LLM 适配层

### PrepLLMAdapter

不是 Port（不定义能力协议），是 Adapter（接口转换）。让 Service 的构造函数接受统一 LLM 依赖，而非直接依赖 llm_client。

```text
注入路径：
    bootstrap.py
        → structured_llm = SharedLLMStructuredProvider()
        → prep_llm_adapter = PrepLLMAdapter(structured_llm)
        → ControlledPrepWorkflow(llm=prep_llm_adapter)
        → CoursePrepAgentService(llm=prep_llm_adapter)
        → PptMappingOptimizationService(llm=prep_llm_adapter)
```

### 方法清单

| 方法 | 对应 PromptSpec | 调用方 |
|------|----------------|--------|
| segment_evidence() | prep.evidence_segmenter | ControlledPrepWorkflow |
| reduce_evidence() | prep.evidence_reducer | ControlledPrepWorkflow |
| plan_outline() | prep.outline_planner | ControlledPrepWorkflow |
| write_script() | prep.script_writer | ControlledPrepWorkflow |
| write_scripts_batch() | prep.script_writer | ControlledPrepWorkflow |
| verify_script() | prep.evidence_verifier | ControlledPrepWorkflow |
| plan_incremental() | prep.incremental_planner | CoursePrepAgentService |
| optimize_ppt_mappings() | prep.ppt_mapping_optimizer | PptMappingOptimizationService |

### Service 构造函数接缝改造

**允许修改**：Service/Workflow 的构造函数签名 + 底层 LLM 调用接缝

**不修改**：业务流程、State 语义、Prompt 语义、校验规则、持久化行为

```python
# 改造模式（向后兼容）
class ControlledPrepWorkflow:
    def __init__(self, llm: PrepLLMAdapter | None = None) -> None:
        self._llm = llm or _DefaultLLMAdapter()  # 未注入时用原有 llm_client
```

## 十、事件与可观测性

### StageEmitter

把 ControlledPrepWorkflow 的 on_stage 回调适配到 Agent Runtime 事件系统。不是 Port，是 Adapter。

### 事件类型

```text
STAGE_STARTED    ← 阶段开始
STAGE_PROGRESS   ← 阶段进度更新
STAGE_COMPLETED  ← 阶段完成
STAGE_FAILED     ← 阶段失败
```

### SSE 断线续传

```text
AgentRunEventStore.append(event)  ← 先落盘
    ↓
EventPublisher.publish(event)     ← 再广播
    ↓
SSE 消费（支持 Last-Event-ID 断线续传）
```

### 进度存储

进度写入独立 `progress` 字段，不写入 `result`。`result` 只在完成时写入最终输出。

## 十一、文件结构

```text
prep/
├── __init__.py
├── DESIGN.md                       ← 本文档
├── enums.py                        # PrepGraphKind（3 个值）
├── prompts.py                      # 6 个 PromptSpec
├── llm_adapter.py                  # PrepLLMAdapter（7 个方法）
├── stage_emitter.py                # StageEmitter
├── validation.py                   # PrepPlanValidatorPort
│
├── common/
│   ├── __init__.py
│   ├── state.py                    # PrepCommonState
│   └── dependencies.py             # CommonPrepDependencies
│
├── initial/
│   ├── __init__.py
│   ├── state.py                    # InitialPrepState
│   ├── dependencies.py             # InitialCoursePrepPort + InitialPrepDependencies
│   ├── workflow.py                 # InitialBuildGraph
│   ├── profile.py                  # InitialPrepProfile（QUEUED, 600s, concurrency=3）
│   └── composition.py              # build_initial_graph_factory
│
├── incremental/
│   ├── __init__.py
│   ├── state.py                    # IncrementalPrepState
│   ├── dependencies.py             # IncrementalPrepPort + IncrementalPrepDependencies
│   ├── workflow.py                 # IncrementalEditGraph
│   ├── profile.py                  # IncrementalPrepProfile（INLINE, 120s, concurrency=10）
│   └── composition.py              # build_incremental_graph_factory
│
└── ppt_mapping/
    ├── __init__.py
    ├── state.py                    # PptMappingState
    ├── dependencies.py             # PptMappingOptimizationPort + PptMappingDependencies
    ├── workflow.py                 # PptMappingOptimizationGraph
    ├── profile.py                  # PptMappingProfile（INLINE, 60s, concurrency=5）
    └── composition.py              # build_ppt_mapping_graph_factory
```

## 十二、Runtime Definition 配置

| Runtime Definition | 执行模式 | 超时 | 并发 | Worker |
|-------------------|---------|------|------|--------|
| prep.initial | QUEUED | 600s | 3 | PrepWorker |
| prep.incremental | INLINE | 120s | 3 | 无 |
| prep.ppt_mapping | INLINE | 60s | 5 | 无 |

## 十三、实施边界

### 允许修改

- Service/Workflow 的构造函数签名（接受可选 `llm` 参数）
- 底层 LLM 调用接缝（`llm_client.chat` → `self._llm.*`）
- bootstrap.py 装配逻辑

### 不修改

- ControlledPrepWorkflow 内部 5 阶段顺序
- CoursePrepAgentService.plan() 的主要业务规则
- InitialCoursePrepService.build() 的持久化规则
- PatchProposal 数据模型
- 任何 Prompt 文本内容
- endpoint 层的 Proposal 持久化逻辑

## 十四、验收标准

1. 现有 tests/agents/ 测试全部通过
2. tests/test_course_prep_agent.py 测试通过
3. tests/test_controlled_prep_workflow.py 测试通过
4. 新增 3 个 Workflow 可独立编译
5. Service 构造函数向后兼容（未注入 llm 时用原有逻辑）
6. bootstrap.py 注册 3 个 Runtime Definition 不阻塞应用启动

## 十五、教师助教动作 v2（2026-08）

### 统一入口

教师界面的按钮和聊天文字都先归一为一个 `PrepAction`，再进入固定的 Port/Workflow；
模型不能自行选择数据库工具、删除接口或检索接口。

| 动作令牌 | 教师意图 | 固定执行链路 |
|---|---|---|
| `optimize_node_title` | 优化当前课程节点标题 | `IncrementalPrepPort.plan_action` → 标题提案 |
| `organize_structure` | 一键整理全部未锁定课程结构 | `IncrementalPrepPort.plan_action` → 结构提案/原子应用 |
| `optimize_node_script` | 优化当前节点的讲解脚本 | `IncrementalPrepPort.plan_action` → 脚本提案 |
| `optimize_all_scripts` | 一键优化全部未锁定讲解脚本 | `IncrementalPrepPort.plan_action` → 5 节点分组、最多 3 组并发 |
| `match_ppt` | 一键匹配 PPT 与知识点 | `PptMappingOptimizationPort.optimize_mappings` |

按钮携带显式令牌；聊天文本通过 `prep/actions.py` 的透明规则识别令牌，并保留教师的
补充要求作为该动作的 Prompt 输入。单节点标题/讲解动作没有选中节点时返回
`needs_clarification`，不得猜测节点。`OCR` 本身不是 PPT 意图，只有 PPT、课件、映射、页码等
明确语义才进入 PPT 流程。

聊天中明确包含“一键/全部/全量/批量”等全课程授权措辞的结构整理或讲解脚本优化，
会复用对应按钮的批量锁、原子应用与 `accepted` 审计提案；单节点聊天动作仍生成
`pending` 提案供教师核对。两种入口共享同一动作令牌、Port 和 Planner。

### 安全与回退语义

- 新动作链路在模型未配置、结构化输出无效、覆盖不完整或语义校验不通过时 fail-closed：
  不生成“看似成功”的规则标题或占位脚本；草稿保持不变。
- 标题必须是 2–40 字的教学概念，不能是图号、页码、OCR 枚举或完整句子。
- 结构整理只允许改标题、移动、排序或删除既有的未锁定节点；不增加/拆分节点。
  删除父节点前必须移动全部子节点，含锁定后代或锁定讲解脚本的分支不能删除。
- 应用阶段先比对 Proposal 的 `before` 快照。结构变更先模拟最终父子关系并检查环，
  再以临时排序号和最终兄弟排序两阶段写入；任一校验失败则整个提案不应用。
- PPT 映射保留独立的“无可靠候选页”结果，不能用低置信度匹配替代。

### 证据与性能

单节点和脚本动作先读取当前课程的确认 `EvidenceSpan`，并在已激活知识包时经
`ActiveBundleCourseRetrievalPort` 查询向量证据；向量检索不可用时只降级到课程内的
词法证据，不伪造证据 ID。全量讲解脚本按每组 5 个、最多 3 个并发请求执行；每组必须完整
返回本组所有脚本，任何一组失败都不会应用批量修改。
# 学习数据边界（2026-08-07）

统一学习链当前已由学习 facade 和学生/课程投影承载，但 Prep Agent 不接入该链路。
Prep 只消费课程建设上下文、草稿和证据引用，不新增 LLM-facing learning Tool，不读取或写入
`LearningEvent`、`StudentLearningProjection`、`LearningEvidenceContext`、认知或推荐记录。
相关 `LearningContextPort` / `LearningProjectionPort` 等接口仅作为未来 Teaching/Coding 适配
契约，状态为 `planned/unimplemented`。

Prep Agent 不新增 LLM-facing learning Tool，不读取或写入学生学习事件、投影、认知或
推荐记录。统一学习数据的 planned Port/Provider 仅供 Teaching/Coding 运行时未来适配；
Prep 保持确定性 Dependencies 与 PatchProposal 边界。

统一学习数据契约字段（`LearningContextPort`、`LearningProjectionPort`、
`LearningEvidenceContextPort`）及 `StudentStateTool` / `CognitionTool` /
`LearningEventTool` 的请求、返回、权限和 `unknown/pending/degraded/not_available`
语义见 `docs/phase1/TeachingAgent运行边界与课程解析降级.md`；它们当前均为
`planned/unimplemented`。Prep Agent 不消费这些接口，也不增加任何 LLM-facing learning
tool，不能写学生学习数据。
