# Nexus 自主实验 V1 执行任务书

> **For agentic workers：**按 T0–T7 的复选步骤逐项实施、验证并更新回执；遵守本仓库 AGENTS.md，默认在当前任务内顺序执行。本任务书不授权安装新依赖、提交、推送或部署，不要求每个内部开发步骤向用户确认。2026-09-07，本地代码基线 `a60d4e87`，任务状态均为 NEXT。

**Goal：**用户提供论文/仓库并确认一次，Nexus 在独立可销毁沙箱内自主准备数据、安装环境、试跑、排错和重试，返回真实结果与可再次使用的实验配方。

**Architecture：**保留一个 Nexus Deep Agents 主管；经既有审批服务启动有 run_id 的实验执行图，复用 LangGraph 的工具循环与 checkpoint。Deep Agents 原生 Sandbox 文件工具通过薄 Adapter 调用专用运行服务；运行服务用 SWE-ReX 管理独立 Docker 实验容器。旧 preset Worker 继续服务 nanoGPT，不在它的进程工作目录里开放自由命令。

**Tech Stack：**现有 Deep Agents 0.7.12（以 uv.lock 为准）/LangGraph/Postgres/HTTPX/FastAPI；优先集成 SWE-ReX 的 Docker 后端，环境构建按仓库声明复用 repo2docker；既有附件、对象存储、Console 和审批。新增开源依赖必须锁定已验证版本，不使用浮动 latest。

## 全局约束与批次范围

1. 产品原则以[持续研究任务书§1.1](Nexus_持续研究V1_开源集成与开发任务书.md)为准：一次确认授权目标、数据/访问和资源范围，允许自动安装、修改依赖/路径/启动脚本、重建任务容器和重试；不逐命令审批。
2. 科研严谨落实到来源和实际结果：安装成功、程序跑通、指标达标、干净B验证分别记录。无指标时可以交付运行成功，不能编造论文复现成功。
3. 不要求完成综述或填写 Evidence/Claim 系统才能配置环境；最小输入为目标和论文/仓库引用。无 preset 不再整体拒绝。
4. 不写第二套 Harness、文件编辑工具、shell会话/PTY引擎、包管理器、通用容器调度系统。Nexus 只负责请求与身份传递、实验记录、授权范围、结果汇总和现有产品接线。
5. Backend/Nexus/执行控制服务保持依赖隔离。平台安装权限与用户实验授权不同；实验内已获授权的 pip/conda 等操作不再次询问用户。
6. 首版验收范围为 CPU、公开且允许复现用途的代码/数据、Python 项目；有网络的安装/数据准备是必需能力。GPU、付费API、私有仓库不假称可用。此范围由平台实际配置声明，不等于未来只支持这些。
7. 容器须可写任务文件并联网取得声明范围内依赖；不把“安全”实现成无法安装。任务环境没有生产凭据、Docker socket 和宿主业务挂载，不互读其他任务；隔离及资源限制由部署层落实，不靠审查shell字符串假装完成。
8. 首版不新做交互终端，不改 v6 布局。正式 Word/LaTeX 和干净B仍是必做后续交付，不能因本批先交付 Markdown 而翻绿；见原 NX-O1/N4。
9. 保护当前脏文件，尤其 `frontend/src/app/pages/nexus/NexusPage.vue`；执行时先核对差异。不得顺手重构 Teaching、课程权限、主数据库或旧 Worker。

## Research Ask / Auto补充契约（NEXT，纳入本批）

完整界面/请求/切换语义以[前端规格§2.1](Nexus_AI_前端开发规格与UX落地说明.md)为准：只在Research展示。Ask与Auto同样自主研究、规划、检索和多格式输出；唯一差别是实验代码沙箱的执行权限。Ask不调用实验沙箱；Auto确认一次后按本任务书运行。平台固定文档渲染不属于实验沙箱权限。

新字段research_execution_mode=ask|auto，默认Ask，未知拒绝；模型不能改。原ExperimentScope.mode继续表达setup/smoke/reproduce。General无此开关且不因伪造auto获得执行权。新建run冻结启动模式，已有run不因对话切Ask自动取消；Ask仍可读日志、下载报告和让用户取消run，但不能追加新的实验命令。

## 1. 已核对的接线点与开源分工

| 实际代码 | 本批使用方式 |
| --- | --- |
| `nexus/src/nexus/agent.py` | 当前关闭execute/文件修改/task；只为已批准的实验图装配原生Sandbox工具，不改变General工具面 |
| `nexus/src/nexus/proposals.py`、`approvals.py` | 现有提案与审批核销；增加 `kind=autonomous_experiment`，保留旧preset精确指纹语义 |
| `nexus/src/nexus/tools/reproduction.py` | 现有no_preset分支、执行及run登记；新类型走独立执行图，不能制造虚拟preset |
| `nexus/src/nexus/main.py` | 既有提案/审批端点及异步入口；同步更新真实消费者 |
| `deploy/repro-worker/worker.py` | 当前容器内subprocess的preset实现，保留；新自由命令不发到其 `/jobs` |
| `backend/app/api/v1/endpoints/nexus_proxy.py`、`nexus_internal.py` | 现有身份、运行、下载与代理契约 |
| `backend/app/services/nexus_run_service.py` | 复用run列表、标题、历史及备注投影；运行核心状态仍归Nexus域 |
| `frontend/src/api/nexus.js`、`nexusAdapter.js`、`nexusCapabilities.js` | 复用现有API与运行状态投影 |
| `frontend/src/app/pages/nexus/components/NexusExperimentWorkspace.vue` | 现有Console显示实际尝试、日志、阶段和结果 |

本地安装包 `deepagents/backends/sandbox.py` 已有 `BaseSandbox`：文件读写/查找/编辑可基于执行及文件传输原语派生。**优先适配这个现成接口，不新增一套 nexus_read/write/edit 工具。** `.venv`仅用于读取核验，不能修改第三方源码来接线。

| 核心 | 采用决策 | 自研仅限 |
| --- | --- | --- |
| Deep Agents / LangGraph | 沿用锁定版，承担模型—工具—观察—继续运行 | 实验专用图装配、任务状态映射 |
| [SWE-ReX](https://swe-rex.com/latest/usage/) / [Docker后端](https://swe-rex.com/latest/api/deployments/docker/) | 首选执行核心；官方提供部署、持久shell会话、输出与退出码接口 | HTTP/身份/结果适配、资源配置、任务生命周期接线 |
| [repo2docker](https://repo2docker.readthedocs.io/en/latest/) | 有支持的仓库配置时作为构建器；不能覆盖的安装流程在基础镜像的任务容器内由原生执行工具完成 | 选择构建路线并记录镜像digest，不自写依赖文件解析/解析器和包求解器 |
| 既有附件/Artifact/对象存储 | 继续复用 | 本任务来源与产物引用，不另建文件平台 |

“生产级”在本项目的含义是选成熟项目承担核心并验证所用版本的真实行为；上游宣传与示例不自动证明生产可用。T0记录兼容版本，T1用真实容器验证。SWE-ReX不能满足关键需求时记录具体失败，再评估等价OSS；不能转而默默自研运行内核。首版不同时集成多个云后端，也不引入第二个顶层OpenHands/ODR主管。

## 2. 固定契约：一次授权与实际尝试分开

以下为本批新增契约，不表示已存在。所有owner/session由服务端注入，模型不能传用户ID或控制服务地址。

```python
# nexus/src/nexus/experiment_contracts.py
from typing import Literal
from pydantic import BaseModel, Field

class Resources(BaseModel):
    cpu: float = Field(gt=0)
    memory_mb: int = Field(gt=0)
    disk_mb: int = Field(gt=0)
    wall_time_s: int = Field(gt=0)

class ExperimentScope(BaseModel):
    objective: str
    repo_url: str
    repo_revision: str
    source_refs: list[str]
    data_refs: list[str]
    network_profile: str  # 服务端已配置的源策略，不是LLM自由填写ACL
    resources: Resources  # 服务端给默认值并核对可用容量
    mode: Literal['setup', 'smoke', 'reproduce']
    allow_environment_repair: bool = True

class SandboxResult(BaseModel):
    operation_id: str
    status: Literal['running', 'succeeded', 'failed', 'cancelled', 'unknown']
    exit_code: int | None = None
    output_tail: str = ''
    output_truncated: bool = False

# JSON可序列化记录；调用方不得把该字段集合冒充完整DB设计。
# run: run_id, owner, session_id, scope_hash, approval_id,
#      sandbox_id, graph_thread_id, status, attempt_no, last_operation_id
# attempt: operation_id, attempt_no, actual_command, config_changes,
#          started_at, finished_at, exit_code, log_ref, artifact_refs
```

授权hash包含scope；实际命令、安装版本变化写attempt，不回写授权hash。目标数据集或论文指标标准改变必须显式区分/征询用户；依赖修复不算越界。`reproduce`没有指标依据时只能记录待核验，不阻止先配置/试跑。

控制服务仅内网使用，由Runtime调用，API凭据不注入实验容器。最小接口：

| 新控制接口（非公开用户API） | 请求/响应及幂等 |
| --- | --- |
| `PUT /sandboxes/{run_id}` | 服务端实验scope与scope_hash→sandbox_id/status；同run同scope重复返回原实例，hash不同409 |
| `POST /sandboxes/{run_id}/operations` | operation_id、command、timeout_s→SandboxResult；先登记再执行，同ID不得运行两次 |
| `GET /sandboxes/{run_id}/operations/{operation_id}` | 查结果/日志游标；HTTP超时不等同进程已停止 |
| `PUT /sandboxes/{run_id}/files/{path:path}` | 受限大小文件上传；path限定任务工作区，遍历/symlink逃逸拒绝 |
| `GET /sandboxes/{run_id}/files/{path:path}` | 同范围下载，明确截断/过大结果；正式交付仍经Artifact |
| `POST /sandboxes/{run_id}/cancel` | 先取消运行操作，再回收实例；重复返回同一终态 |
| `GET /sandboxes/{run_id}` | 生命周期/活跃operation/资源与日志摘要，用于对账 |

操作ID与run ID来自持久化执行意图，不在重试时重新随机生成。首次运行记录、授权核销与待提交状态在Nexus侧原子落盘；提交控制服务失败可按同ID重试。取消、超时及控制服务重启都不能触发未知命令重放。

## T0：锁定开源接入点与现有问题（N0必要项）

**文件：**新增本批唯一回执 `docs/phase1/验收记录/Nexus_自主实验V1_开发回执.md`；核对 `nexus/uv.lock`、`agent.py`、`approvals.py`、`proposals.py`、`tools/reproduction.py`；需要修复时只改对应文件和现有测试。

- [ ] 记录HEAD、脏文件、当前preset/审批/Console的调用链；从此前审查逐项核实，已经修复的不重做，未复测的不默认通过。
- [ ] 读取锁定Deep Agents的BaseSandbox、异步执行、文件传输签名；核验SWE-ReX Docker配置、取消、日志、重连能力；记录选定的准确包版本、commit和许可证。无安装授权时完成只读核验，安装需求集中列入回执，不反复问用户。
- [ ] 定位SWE-ReX实际容器资源/网络/命名配置入口及是否支持操作状态恢复，标注官方API路径。缺接口可用Docker官方查询API做薄适配，不另写shell运行器。
- [ ] 修复本批依赖的审批混版、归属登记、异常锁释放；运行相关既有测试。记录失败来自功能还是环境，不删除失败测试。

运行（仓库根）：`nexus/.venv/Scripts/python.exe -m pytest nexus/tests/test_approvals.py nexus/tests/test_proposals.py nexus/tests/test_reproduction.py -q`

**完成物：**明确一个采用版本和接口映射的回执、必要修复及结果。未安装SWE-ReX不能将其标为实测通过。

## T1：让原生文件工具真正接入独立沙箱（N2）

**新增：**`deploy/repro-runtime/pyproject.toml`、该独立项目的lockfile、`service.py`、`swerex_adapter.py`、`README.md`、`tests/test_swerex_adapter.py`、`tests/test_service.py`；`nexus/src/nexus/experiment_sandbox.py`、`experiment_contracts.py`、`nexus/tests/test_experiment_sandbox.py`。目录只在实现真实接线时创建，不先堆空骨架。

**接口：**`experiment_sandbox.py`实现已安装版BaseSandbox的execute/文件传输原语，经HTTP调用§2；服务端Adapter将它们映射到SWE-ReX部署与runtime。生产执行路径禁止回落宿主subprocess。长命令由operation ID查询，超时后继续查看或取消，不盲重发。

- [ ] 先写Adapter契约测试：原生write/edit/read/grep产生的实际命令全部进入FakeTransport；传输超时后同operation_id查询，不生成新命令。
- [ ] 实现薄Adapter；复用BaseSandbox的文件工具，不复制其实现。主聊天offload继续用StateBackend，实验文件路由到实验后端，避免把聊天压缩文件误落到沙箱根路径。
- [ ] 经安装授权后配置独立执行控制服务环境；用SWE-ReX Docker后端启动任务实例。控制服务掌握容器管理，实验实例不挂Docker socket；禁止把旧Worker直接加宿主socket作为捷径。
- [ ] 真实容器运行以下语义，核对返回值与宿主文件不可见；创建、执行、传输、取消、清理必须全部实际工作。

```python
# 测试fixture: sandbox是正式Adapter，隔离容器由SWE-ReX创建。
def test_native_file_tools(sandbox):
    assert sandbox.write('/workspace/probe.txt', 'before').error is None
    assert sandbox.edit('/workspace/probe.txt', 'before', 'after').error is None
    result = sandbox.execute('cat /workspace/probe.txt')
    assert result.exit_code == 0
    assert 'after' in result.output
```

- [ ] 核对SWE-ReX返回属性与BaseSandbox返回类型，以上代码若与锁定版本差异，只修改Adapter/测试契约，禁止盲升级主框架。
- [ ] 验证两个任务互不读写、长进程cancel后无残留、资源限额实际生效、重启控制服务不重复创建。安装及数据源可访问；通往宿主业务网的请求失败。

运行：Runtime测试使用Nexus venv；执行控制服务测试使用其独立venv。`nexus/.venv/Scripts/python.exe -m pytest nexus/tests/test_experiment_sandbox.py -q`；在 `deploy/repro-runtime` 已获授权并安装完成后运行 `uv run pytest tests/test_swerex_adapter.py tests/test_service.py -q`。

**交付门：**此时模型还不必介入，但必须能通过正式Adapter完成真实容器文件修改与执行。没有Docker环境记集成待验收，不退化为宿主执行。

## T2：新增自主实验提案，一次确认可覆盖排错（N1/N3授权）

**修改：**`proposals.py`、`approvals.py`、`main.py`、`tools/reproduction.py`、`backend/app/api/v1/endpoints/nexus_proxy.py`；新增 `nexus/tests/test_autonomous_approval.py`。

**接口：**在既有proposal创建接口增加判别字段 `kind`，缺省仍为preset；自主类型消费ExperimentScope，不要求preset_id。沿现有request-approval/decide调用创建run；新增字段的存储升级按显式迁移进行，迁移文件编号读取当前head后分配，不写启动时DDL。

- [ ] 先测试“批准scope→安装命令改变→仍只有一个批准记录”，以及scope改变不能继续；保存既有preset指纹不匹配拒绝的测试。
- [ ] 实现 `scope_hash` 与实际attempt分离。核销后启动run的ID持久化，已核销重试返回原run，不能因审批展示TTL过期打断正在运行的任务。
- [ ] 新增research_execution_mode请求字段与服务端会话偏好恢复，Research默认Ask、unknown返回400。启动必须Research+Auto+本人批准；Ask直接调用含preset在内的实验入口或携旧票据也返回403 EXPERIMENT_EXECUTION_DISABLED且零提交。后端和工具各自校验，不让模型改变模式或宣布批准。
- [ ] 用原审批卡显示目标、资源/最长时间、自动安装与排错范围。用户不需要看scope_hash/Claim表，也不用逐一确认初始命令。

```python
# approval_flow为测试夹具，调用真实proposal/approval服务，使用合成身份。
def test_repair_does_not_consume_second_approval(approval_flow):
    run = approval_flow.start_once(mode='smoke')
    approval_flow.record_attempt(run, command='python train.py')
    approval_flow.record_attempt(run, command='pip install -r requirements.txt')
    assert approval_flow.approval_count(run) == 1
    assert approval_flow.retry_start(run).run_id == run.run_id
```

运行：`nexus/.venv/Scripts/python.exe -m pytest nexus/tests/test_autonomous_approval.py nexus/tests/test_approvals.py nexus/tests/test_proposals.py -q`。

## T3：无preset也能从论文/仓库开始（最小SR1/N1）

**新增：**`nexus/src/nexus/experiment_intake.py`、`nexus/tests/test_experiment_intake.py`；修改 `tools/reproduction.py`、`tools/__init__.py` 和 `agent.py`；复用附件/论文读取模块。

**接口：**新增Research工具 `prepare_experiment(target: str, objective: str) -> dict`，输出同一提案引用、可读摘要、缺少的用户输入；不直接执行。内部来源记录复用现有附件与研究结果，来源无全文时不冒充已读。

- [ ] no_preset路径测试：给明确仓库与“配置并试跑”，返回自主提案，不回答仅支持nanoGPT，也不要求用户先提供指标/主张。
- [ ] 明确论文输入则读取可得论文，按作者链接找仓库；初始repo固定revision，License沿既有规则核验。缺少资料先自主查找，真正无权获取的数据才要求用户提供。
- [ ] 读取README与环境/数据入口，区分setup/smoke/reproduce；默认资源来自服务端可用配置。解析结果不确定的依赖版本留给沙箱试验，不虚构“已配置成功”。
- [ ] 默认展示目标＋公开数据来源＋资源摘要；只有用户目标真正歧义且无法合理推断时询问，不把每个识别字段都做确认表单。

```python
async def test_unknown_preset_can_prepare(intake):
    proposal = await intake.prepare('fixture://repo-a', '配置环境并试跑')
    assert proposal['kind'] == 'autonomous_experiment'
    assert proposal['scope']['mode'] == 'smoke'
    assert proposal['scope'].get('claim_refs') is None
    assert intake.worker_submit_count == 0
```

运行：`nexus/.venv/Scripts/python.exe -m pytest nexus/tests/test_experiment_intake.py nexus/tests/test_reproduction.py nexus/tests/test_modes.py -q`。fixture URL只在测试Reader中处理，不进入正式工具的来源白名单。

## T4：接入现成Agent循环，自主安装、试跑和修复（N3/SR5核心）

**新增：**`nexus/src/nexus/experiment_agent.py`、`nexus/tests/test_experiment_agent.py`；修改 `agent.py`、`main.py`、`tools/reproduction.py`。

**接口：**`build_experiment_agent(backend, checkpointer, model)`返回Deep Agents编译图；批准后执行器传入run绑定的Backend，模型拿不到宿主路径或控制凭据。它是同一Nexus的实验执行图，不是新产品入口或第二个顶层主管。保留Todo/Compact，原生文件与execute工具仅在此图启用。

- [ ] 先用脚本化模型驱动真实graph，模拟“读取README→安装→缺包→查错误→修复→重跑”。断言调用正式Adapter且审批次数为1，不以检查prompt代替行为测试。
- [ ] 避免修改全局openai HarnessProfile导致General或Research Ask开放execute；实例级装配/缓存键区分General、Research Ask/Auto及run实验图。Ask仍保留多步骤研究和非执行子任务、Artifact工具，只排除实验调用（含子任务间接绕行）。
- [ ] 提示约束只描述任务：自行选择安装步骤，观察退出码/日志，必要时修依赖与命令继续尝试；不每步请求批准，不为了得到PASS修改指标/数据或删除失败记录。
- [ ] 环境路线：仓库有repo2docker支持的配置时调用其构建能力；构建在专用执行设施，不能给仓库代码宿主Docker socket。普通requirements/脚本项目允许在预置Python基础容器内安装，沿用pip/conda能力，不自写依赖求解。下载公开数据及重建环境属于同次授权。
- [ ] 长运行由独立run生命周期驱动，HTTP/SSE断开不杀任务；只保留一个graph执行者。持久化执行意图后再调用外部operation，恢复先查询结果再继续模型。
- [ ] 服务端实施已确认的时间/磁盘/算力上限；按真实剩余资源继续排错，不预设“修两次失败就交还用户”。持续同一错误无进展时换策略，无法继续时交付日志和可恢复配方。

```python
async def test_repair_loop_uses_real_tools(experiment_flow):
    result = await experiment_flow.run(script='missing_dependency_then_fix')
    assert result.approval_count == 1
    assert result.executions >= 3
    assert result.observed_failure_before_repair
    assert result.final_exit_code == 0
    assert result.used_framework_file_tools
```

运行：`nexus/.venv/Scripts/python.exe -m pytest nexus/tests/test_experiment_agent.py nexus/tests/test_agent_tools.py nexus/tests/test_modes.py -q`。脚本化模型仅证明循环协议；实际LLM是否会选择正确修复须T7另验。

## T5：持久运行、Console与取消直接复用（最小SR4）

**新增：**`nexus/src/nexus/experiment_store.py`、`nexus/tests/test_experiment_recovery.py`；修改 `main.py`、两个Backend nexus端点、`nexus_run_service.py`、既有前端API/Adapter/Capabilities及Console组件。涉及界面前先读根 `design.md`。

**接口：**Nexus域存run/attempt及控制服务句柄，LangGraph存图状态；Backend沿现有run服务提供归属投影。继续使用现有 `/repro/jobs/{job_id}`、cancel、report及run列表用户接口，内部按provider分派，标识不能与preset job碰撞；不让前端直连控制服务。

- [ ] 给run状态写恢复测试：Nexus重启时已有operation运行中，只接管查询，不再次submit；控制服务失联显示reconciling，不冒称failed/cancelled。
- [ ] 控制服务将run/operation登记持久化在Nexus运行域专用表，租约与容器标签/运行标识可对账。复用Postgres原子写与LangGraph恢复机制；不要另建通用任务调度框架。进程崩溃后先确认旧执行是否存活，未知不得重放。
- [ ] 事件投影attempt编号、真实阶段、命令摘要、运行时长、日志尾、退出码、结果；现有阶段条可以重复Running并展示尝试记录，不能假装首次就成功。Building/Verifying未发生则skipped。
- [ ] 用户Cancel直接沿现有API停止当前操作和沙箱，进程回收确认后终态cancelled；模型排错时终止自己的卡住命令不触发“取消整个实验”的第二次确认。
- [ ] 增加Research输入框Ask/Auto选择器，General隐藏；与浮窗共享服务端会话偏好及本次请求effective值。Ask不阻止查看工作台/下载/用户Cancel，禁止启动/复跑；Ask下可用“切换Auto并批准执行”合并操作，避免两层确认。
- [ ] 刷新/切换工作台读服务端快照；切Ask只约束新请求，活跃run继续并显示说明，不允许Ask消息追加沙箱命令。聊天Stop不伪装Cancel。现有名字、备注、下载和跨用户隔离回归。

```python
async def test_resume_does_not_repeat_install(recovery_flow):
    run = await recovery_flow.start_running_install()
    await recovery_flow.restart_nexus()
    await recovery_flow.resume(run)
    assert recovery_flow.provider_operation_count(run) == 1
    assert recovery_flow.console_status(run) in {'running', 'completed'}
```

运行：`nexus/.venv/Scripts/python.exe -m pytest nexus/tests/test_experiment_recovery.py nexus/tests/test_run_operations.py -q`；Backend独立环境跑 `backend/tests/test_nexus_repro_jobs.py`、`test_nexus_lb1_lb2.py`、`test_nexus_lb3_lb4_lb5.py`；前端目录运行 `node src/api/__tests__/apiContracts.test.cjs` 与 `pnpm build`。

## T6：交付环境配方与真实结果（接既有Artifact）

**修改：**`nexus/src/nexus/repro_report.py`、`artifact_client.py`、相关实验模块；新增 `nexus/tests/test_experiment_report.py`。不新建独立Evidence/Claim产品或第二套对象存储。

- [ ] 收集固定repo SHA＋实际补丁、依赖锁/镜像digest、数据来源/hash、执行命令、参数、seed、日志引用与实际指标；保存后才回收可变工作区。不能只交一段模型建议的安装命令。
- [ ] 配方和结果关联本run；报告区分 `environment_ready`、`execution_succeeded`、`metric_verdict`、`clean_verification`，没有指标就是not_evaluated，B未执行就是not_run。
- [ ] 用户得到“做了什么、修了什么、跑出什么、如何再跑”的Markdown报告和可下载配方/日志；产物经现有owner/session校验，拒绝越权或越工作区文件导出。
- [ ] 同时冻结供NX-O1使用的内容版本，预留多格式产物引用；正式Word/LaTeX由SR6/NX-O1复用Pandoc等成熟转换器另行完成，不能以本批有.tex文本认定完成。

```python
def test_exit_zero_is_not_paper_success(report_factory):
    report = report_factory(exit_code=0, metrics=None, clean_b=None)
    assert report['execution_succeeded'] is True
    assert report['metric_verdict'] == 'not_evaluated'
    assert report['clean_verification'] == 'not_run'
    assert report.get('reproducible') is not True
```

运行：`nexus/.venv/Scripts/python.exe -m pytest nexus/tests/test_experiment_report.py nexus/tests/test_repro_report.py nexus/tests/test_tools_artifact.py -q`。

## T7：用户体验与真实能力验收

**文件：**更新T0回执、P2当前进度及相关模块README；合成仓库fixture只放 `deploy/repro-runtime/tests/fixtures/`，不放真实学生内容。

- [ ] 样例A：无preset的合成Python仓库，带requirements和公开可替代的合成数据，注入缺包或路径错误。脚本化模型走正式图＋真实容器完成修复，用于验证协议与执行真实性。
- [ ] 样例B：另一种环境声明的合成仓库验证repo2docker构建；若该构建路线尚未通过，明确该路线未交付，不能把基础镜像安装等同repo2docker已集成。
- [ ] 经授权的真实模型人工验收：选择两个已核验License、固定revision、CPU可运行的公开论文配套仓库或作者提供的最小实验，记录实际名称与选择依据。不能是nanoGPT别名；一个走README/requirements，另一个验证不同环境/数据入口。真实模型自主读错误并修复，预先写好修复命令不算自主性实证。
- [ ] 模式验收：Research Ask可多轮检索规划和输出Markdown/已支持格式，实验提交为0；直接接口/旧票据/子任务绕行拒绝；General隐藏开关，auto字段不能提权。Auto→Ask后禁止新run，旧run不暗中取消，用户Cancel可用；浮窗/刷新一致，文档渲染不受实验禁用影响。
- [ ] UI全链：用户提供材料→Auto一次启动确认→自动下载/安装/修复/运行→Console有日志→刷新继续→下载报告与配方。记录人工确认次数；授权范围内的缺包/路径修复必须为1次启动确认。
- [ ] 失败链：缺私有数据时先完成可独立环境准备再说明所缺；下载中断自主重试；资源上限到达保留结果；用户取消实际回收；恢复不重复执行；跨用户请求拒绝。
- [ ] 范围外付费/资源扩张不自动执行；此用例的追加决定不计作普通排错审批。无数据/原指标不明时交付真实边界，不能改成假PASS。
- [ ] 更新CURRENT仅标已验收范围：“CPU公开仓库的一次确认自主配置与运行V1”；完整Paper Research、GPU、A/B、Word/LaTeX未通过各自验收前保留NEXT。

每项回执记录：实际命令/环境、通过/失败、fake或真实模型、真实容器或模拟、未验证项和对应源码。不能用套件数量代替任务行为。自动化测试不调用真实付费LLM；线上写入/部署和新依赖安装遵守单独授权。

## 3. 排期、执行纪律与结束条件

**执行顺序：T0→T1→T2→T3→T4→T5→T6→T7。** T1真实沙箱是核心，不把大部分时间花在研究字段/审批表设计上。T2/T3可在T1接口冻结后独立开发；完整持续研究及正式输出与本链按接口衔接，不要求先完成。

预计拆成四次可验收交付：①T0/T1开源运行核心接通；②T2/T3一次确认和无preset入口；③T4/T5自主排错＋恢复Console；④T6/T7真实结果和体验验收。不给未经试验的“一夜必完成”承诺。

变更范围仅本任务书列出的直接模块/测试/显式迁移/文档；无需逐文件让用户确认。依赖安装、远程部署等若无授权，先完成兼容调查、精确变更清单与独立可做的本地工作，再集中说明真正缺少的授权。不能为了不中断而安装未批准依赖或将mock标成实测。

实现步骤中的测试代码为行为契约；执行者需在列明测试文件中实现调用真实业务代码的fixture，不能让fixture自身伪造成功计数。每个任务做相关测试后检查差异；未经授权不commit/push，不改现有stash及无关dirty文件。

最终完成条件：用户提供新仓库，系统不依赖写死preset；确认一次后在真实独立沙箱中自主完成至少一次环境故障修复与继续运行，过程可恢复可取消，结果与产物能下载且如实说明验证范围。仅有接口、mock、安装成功或一份计划均不能关闭本批。
