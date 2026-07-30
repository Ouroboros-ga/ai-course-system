# 助教智能体（Prep Agent）设计文档

> Phase 4 实施基线。本文档固化三链路统一架构：共享基础设施，不共享业务状态机。

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
| 4 | 所有讲解稿一键优化 | script.content/style | 全量增量 | INLINE | IncrementalEditGraph |
| 5 | 讲解稿节点选中优化 | script.content/style | 单个增量 | INLINE | IncrementalEditGraph |
| 6 | PPT映射OCR匹配优化 | ppt_mapping | 全量增量 | INLINE | PptMappingOptimizationGraph |

### 场景 2-5 的参数区分

场景 2-5 使用同一个 Workflow（IncrementalEditGraph），通过调用参数区分：

| 场景 | outline_node_id | instruction 示例 | LLM 行为 |
|------|----------------|-----------------|---------|
| 2 | None | "优化所有知识点标题" | 生成 outline.title 类 operations |
| 3 | "node_xxx" | "优化这个知识点" | 生成单个 outline.title operation |
| 4 | None | "优化所有讲解稿" | 生成 script.content 类 operations |
| 5 | "node_xxx" | "优化这个讲解稿" | 生成单个 script.content operation |

Graph 不区分"知识点优化"和"讲解稿优化"——这是 LLM 根据指令文本理解的职责。

## 三、架构总览

```text
AgentGateway
    │
    ├── graph_kind=initial
    │       ↓ (QUEUED, Worker)
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
    │   IncrementalPrepPort.plan()
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
| InitialBuildGraph | 1 | InitialCoursePrepService.build() | Service 内部 | 4 Prompt + 1 确定性编译 |
| IncrementalEditGraph | 1 | CoursePrepAgentService.plan() | endpoint 层 | 1 Prompt |
| PptMappingOptimizationGraph | 1 | PptMappingOptimizationService | Service 内部 | 1 Prompt |

### Workflow 1：InitialBuildGraph

```text
执行模式：QUEUED（Worker）
超时：600s
并发：3
节点：execute_initial_build
    ↓
InitialCoursePrepPort.build(
    teacher_id, course_id, corpus_snapshot_id,
    build_task_id, on_stage=stage_emitter.callback,
    replace_unreviewed_initial=False,
)
    ↓
返回 DraftAssetResult
```

**持久化**：Service 内部完成（outline/scripts/ppt/graph 全部持久化）。Graph 不触碰持久化。

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

**持久化**：endpoint 层创建 PatchProposal。Graph 不持久化。

### Workflow 3：PptMappingOptimizationGraph

```text
执行模式：INLINE
超时：60s
并发：5
节点：optimize_ppt_mappings
    ↓
PptMappingOptimizationPort.optimize_mappings(course_id, material_version_id)
    ↓
返回 PptMappingOptimizationResult
```

**持久化**：Service 内部直接更新 CoursePptMapping（status=draft）。不创建 PatchProposal。不修改 teacher_locked=True 的映射。

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
| AgentRunStorePort | 运行状态持久化 | SqlAgentRunStore / NullAgentRunStore |
| AgentRunEventPort | 事件流持久化 + SSE | SqlAgentRunEventStore / NullAgentRunEventPort |

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

首次备课 5 个阶段，其中 4 个 LLM Prompt、1 个确定性编译阶段；增量修改 1 个 LLM Prompt；PPT 映射优化 1 个 LLM Prompt。

| # | PromptSpec | 阶段 | 链路 |
|---|-----------|------|------|
| 1 | prep.evidence_segmenter v1.0 | 证据分段 | Initial |
| 2 | prep.outline_planner v1.0 | 目录规划 | Initial |
| 3 | prep.script_writer v1.0 | 讲稿撰写 | Initial |
| 4 | prep.evidence_verifier v1.0 | 证据校验 | Initial |
| 5 | prep.incremental_planner v1.1 | 增量规划 | Incremental |
| 6 | prep.ppt_mapping_optimizer v1.0 | PPT映射优化 | PptMapping |

`compile_patch` 阶段是确定性编译，无 Prompt。

## 九、LLM 适配层

### PrepLLMAdapter

不是 Port（不定义能力协议），是 Adapter（接口转换）。让 Service 的构造函数接受统一 LLM 依赖，而非直接依赖 llm_client。

```text
注入路径：
    bootstrap.py
        → structured_llm = SharedLLMStructuredProvider(llm_client)
        → prep_llm_adapter = PrepLLMAdapter(structured_llm)
        → ControlledPrepWorkflow(llm=prep_llm_adapter)
        → CoursePrepAgentService(llm=prep_llm_adapter)
        → PptMappingOptimizationService(llm=prep_llm_adapter)
```

### 方法清单

| 方法 | 对应 PromptSpec | 调用方 |
|------|----------------|--------|
| segment_evidence() | prep.evidence_segmenter | ControlledPrepWorkflow |
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
| prep.incremental | INLINE | 120s | 10 | 无 |
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
