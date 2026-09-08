# Nexus 自主实验 V1 开发回执（T0：锁定开源接入点＋N0 可信度收尾）

> 基线 dev-liu / `a60d4e87`；工作区另有 8 个他人在制品文件（README、DOCUMENTATION_INDEX、
> P2 计划、v1.3 设计、前端规格、NexusPage.vue、nexus.js、工作台组件），本批未触碰。
> 本回执只记录 T0；未安装任何新依赖（`nexus/uv.lock` 零改动，下有铁证）。

## T0-1 开源接入点冻结（只读，未安装）

- Deep Agents **0.7.12**（`nexus/uv.lock:192`，wheel hash `sha256:5df1818b…`）：
  `deepagents.backends.sandbox.BaseSandbox`（`sandbox.py:1411`，ABC）——子类必须实现
  `execute(command, *, timeout) -> ExecuteResponse`、`upload_files()`、`download_files()`、
  `id`；自带 ls/read/write/edit/grep/glob（均构建于 `execute` 之上）与 sync/async 双形态、
  capture-offload（默认关闭）。官方 docstring 明示：BaseSandbox **不缩小 execute 的信任边界**，
  隔离必须由后端（SWE-ReX Docker）提供——T1 适配不得把 Adapter 当隔离证明。
- SWE-ReX：PyPI 最新 **1.4.0**（2025-08-14）、**MIT** 许可、requires_python ≥3.10，
  基础依赖 fastapi/uvicorn/requests/pydantic≥2/pexpect/bashlex/python-multipart/rich，
  无已知漏洞记录（PyPI vulnerabilities 为空）。T1 候选 pin 1.4.0，须先过真实容器验证
  （Docker 后端创建/取消/日志/重连/资源限额）才能采用；未安装，未写入任何 lockfile。
- repo2docker：T0 未核验（T1 与构建路线一起记录版本/commit/许可）。
- 采用结论：T1 薄 Adapter 映射 `execute/upload/download` 到 SWE-ReX 部署＋runtime；
  文件工具复用 BaseSandbox 实现，不复制；`enable_capture_offload` 保持默认关闭
  （沙箱镜像 shell 假设未经核验）。

## T0-2 P1-A：核销冻结快照＋锁定提案

改动（`nexus/src/nexus/`）：
- `proposals.py`：新增 `lock_proposal_for_execution`（内存 check-set；PG 单条
  `UPDATE ... WHERE draft+version+hash+user RETURNING` 原子转换；PG 异常 fail-closed，
  不回退内存防脑裂）；`mark_proposal_executed` 接受 draft|approved→executed；
  非 draft 的 patch/二次 request-approval 本就 409（语义不变）。
- `approvals.py consume_approval`：核验通过后立即 CAS 锁定，把锁定行 full body
  冻结为 `frozen_proposal` 附在核销返回值上（不新增表列）。
- `tools/reproduction.py execute_approved_reproduction`：提案票据只消费
  `frozen_proposal`（缺失 fail-closed 拒执行）；`_record_run_linkage` 新增
  `frozen_snapshot` 参数，不再 `get_proposal` 读现行值。
- 说明：consume 与 lock 是两次 CAS（跨表无单事务），任一 miss 即拒绝——不存在
  混合快照的提交路径；这是 fail-closed 设计，不是"事务不够"。
- 失败语义：Worker 提交失败后票据已消费＋提案已锁定（approved），用户须建新提案
  （参数可复用）；旧行为中"消费了但没锁"的不一致态消除。

## T0-3 P1-B：linkage 不可读≠无 linkage

- `main.py _fetch_run_linkage` 改为 `(linkage, status)` 三态：ok / not_found
  （404/未配置/无 user→ legacy preset 判定不变）/ unavailable（超时/非 200/坏 JSON）。
- `repro_report.build_report` 新增 `basis=="unknown"` 分支→ verdict **INCOMPLETE**
  ＋ metric_note 写明不可读原因；comparison 为空。
- 报告端点：unavailable 时出无比较报告、产物照常、**不回写** metric（pending 停留，
  回写 INCOMPLETE 会伪装成一次真实比较）；not_found 沿用 legacy；ok 沿用原逻辑。
- 现有 `test_proposals.py` 的 linkage 替身已同步为新签名（ok）。

## T0-4 P1-C：异常释放锁＋失败可重试

- `main.py chat()`：拿写者之后（astream＋aget_state＋plan 投影＋touch）全部进
  try/finally 统一释放；失败记 failed。
- `_acquire_thread_writer`：failed 条目直接丢弃、同键视为新执行（不再回放空结果，
  不再永久 409）；running→409、done→回放不变（stream/非流式共用）。
- `_agent_stream` 原有释放路径不动（except/正常＋finally 兜底 discard）。

## T0-5 H1/R1a 准备链遗留

- R1（引用映射）✅ 关闭：`write_research_report` 在 id 解析后校验正文 `[n]`——
  越界→`CITATION_NUMBER_INVALID`，零正文引用→`CITATION_BODY_MISSING`；
  旧测试中"测写入失败"的用例正文已补合法 `[1]`（意图不变，注释写明原因）。
- R2（撤销重验）✅ 关闭：写入前对 resolved 证据的去重附件逐一重读（Backend 内部
  端点），任一不可用→`EVIDENCE_SOURCE_REVOKED`（写路径零触达）；后端未配置时跳过
  （此时 collect 本就不可用）。已生成报告按 Artifact 生命周期保留，不删除。
- R3（问题参与选择）✅ 部分关闭：`collect` 按问题词频确定性排序（稳定排序，
  无命中退化原文顺序，预算语义不变）＋证据 `truncated` 块级标记；多篇预算再平衡
  与 locator 补登入口转 SR2（需预算策略产品决策＋新端面，T0 不扩面），理由记此。
- H2（恢复错误语义）✅ Runtime 侧关闭：`plan` 与 `sessions/messages` 读取失败改
  503 `CHECKPOINT_READ_FAILED`（真正无计划仍 200 null/[]）；前端消费（保留缓存＋
  标失败＋可重试）待页面_owner_实现，契约记此（事件已带 session_id，见 LB3 测试）。
- H1（计划串会话）⏭ 不碰页面：Runtime 侧已由 LB3 事件归属覆盖（测试为证）；
  消费者修复待页面_owner_，契约同上。
- 未动项：`abstract_only` 500 字符启发式、证据卡摘录长度、“最多修正一次”计数器——
  非 N0 门，转 SR2/SR4。

## 回归证据（命令＋结果）

- `nexus/.venv/Scripts/python.exe -m pytest nexus/tests -q`（仓库根等价
  `uv run pytest tests -q -p no:cacheprovider`）：**161 passed**
  （含新增 `test_n0_credibility.py` 9 项：冻结/锁、不可读 INCOMPLETE＋零回写、
  legacy PASS 保持、异常释放锁＋同键重试、引用越界/缺失、撤销、问题排序、
  截断标记、503 恢复语义）。
- Backend nexus 域：`test_nexus_lb1_lb2/test_nexus_lb3_lb4_lb5/test_nexus_attachments`
  **37 passed**（P1 改动未波及 Backend，契约面不变）。
- 前端契约：89 项中 88 通过；唯一失败为 CourseLayout 他线旧断言（XH 合并引入，
  本批未动该域）；新增 N0 源码映射断言 12 条全过。
- `git diff --stat -- nexus/uv.lock backend/pyproject.toml` 为空（无新依赖铁证）。

## 未验证项

- 真实 PG 下的提案锁 CAS 并发（本地 SQLite/内存全覆盖；PG 原子语句与 approvals
  同模式，线上核验待部署后）。
- 真实 Worker/LLM 行为：合成覆盖冻结/判定/锁语义；真实执行质量属 T7。
- 前端 H1/H2 消费侧：待页面_owner_按上述契约实现（503/事件 session_id）。

## T1-a（2026-09-08）：契约＋薄 Adapter（零安装、零新依赖）

新增（未提交）：`nexus/src/nexus/experiment_contracts.py`（任务书 §2 原样：
Resources/ExperimentScope/SandboxResult pydantic＋Run/Attempt TypedDict）、
`nexus/src/nexus/experiment_sandbox.py`（`HttpSandboxBackend(BaseSandbox)`）、
`nexus/tests/test_experiment_sandbox.py`（7 项契约测试）。

- 映射面：`execute/upload_files/download_files/id` ↔ 控制服务 HTTP
  （PUT ensure 同 run 幂等；POST operations 带调用方 operation_id
  `run-op-NNNN` 单调；GET 查询/游标；PUT/GET files 工作区限定；POST cancel；
  GET lifecycle）。aexecute/aupload/adownload 真异步实现（非 to_thread）。
- 超时≠停止：截止内轮询同 id，截止到返回当前尾部（exit None＋truncated），
  调用方凭 `last_operation_id`＋`query_operation` 续查；POST 计数恒 1（测试锁定）。
- fail-closed：未配置/不可达抛 `ExperimentSandboxError`（码 NOT_CONFIGURED/
  UNAVAILABLE/REJECTED/BAD_RESPONSE/ID_MISMATCH/ENSURE_FAILED）；模块无
  subprocess/os 执行原语引用（AST 断言）；客户端拒 `..` 逃逸/超 5MB 文件。
- 回归：`test_experiment_sandbox.py` 7/7；nexus 全套件 **168 passed**；
  前端契约 88/89（唯一失败仍为 CourseLayout 他线旧断言）；`uv.lock` 零改动。

## T1-b（2026-09-08）：SWE-ReX 真实容器＋控制服务（服务器侧验证通过）

> 授权：swe-rex==1.4.0 pin＋服务器侧真容器验证。生产常驻另行决策；
> 验证部署已全量拆除（无残留进程/容器），仅缓存镜像与代码。

- 独立项目 `deploy/repro-runtime/`（独立 pyproject/uv.lock/venv，不进
  nexus/backend 依赖树）：`service.py` 控制服务＋`swerex_adapter.py` 薄适配
  ＋`Dockerfile`/`Dockerfile.task`＋三套测试。另补 `aiohttp>=3.10`
  （swe-rex 1.4.0 未声明但 Docker 后端 import 必需——实测确认的上游打包缺口，
  uv.lock 锁定 exact）。
- API 全部按已安装 1.4.0 源码实测编写（拒绝凭记忆）：
  `DockerDeployment(image/pull/python_standalone_dir=None/port/docker_args/
  startup_timeout)`＋`start/stop/runtime/is_alive`；`RemoteRuntime.execute
  (Command(command/timeout/shell=True))`、`read/write/upload_file`、
  `BashAction/BashObservation` 形态；包目录实为 `swerex`（非 `swe_rex`）。
- 关键发现与决策（均有实证）：
  1. 任务容器启动时 pip 现装 swe-rex 太慢且抖动（首轮 ensure 超时）→
     预构建任务镜像 `repro-task:1.4.0`
    （`sha256:4f2ba29b…`，python:3.12-slim＋swe-rex 预装），启动 2 秒级；
     生产沿用"预构建＋pull=never＋记 digest"路线。
  2. 容器内绑 127 使宿主端口映射 RST→容器内绑 0.0.0.0，对外收敛由
     docker `-p 127.0.0.1:8401` 保证（宿主外不可达）。
  3. 取消走优雅 stop 会排队挂起（容器内服务被长执行占住）→ kill-first：
     daemon 面强制回收＋20s 上限优雅收尾；取消全程约 3 秒。
  4. 服务容器内无 docker CLI→控制服务改跑宿主 venv（任务仍在容器，
     隔离模型不变）；另补 `apt python3.10-venv`（宿主最小变更，已记录）。
- 黑盒 6/6（8.4s）＋宿主断言全过：创建/执行/传输/取消/清理；双任务隔离
  （跨读 404＋不同容器）；长 sleep 取消约 3 秒且零残留；资源生效
  （memory=2g、pids=512、privileged=false、无任何挂载、bridge 网络）；
  重启对账 unknown＋409 不复用＋已完成操作保留；网络基线：
  metadata 与宿主网关均 UNREACHABLE（任务镜像无 curl，用 python 探针实证；
  PyPI 出向可用——首轮 pipx 下载行为实证）。
- 本地：adapter 7＋service 8（含快照对账）全绿；test_live_docker 无 env 默认跳过。
- 未竟：任务网络显式 allowlist 策略（当前 bridge 默认＋基线记录，加固属 T2 部署项）；
  sessions 长会话语义（T4 按需）；服务常驻化（systemd/ supervision，生产决策）。

## 线上验证（2026-09-08，部署 0b6c2633，一次性验证账号 `nx_verify_t0_*`）

- 发布＋Runtime rsync（diff 干净）＋重启＋健康检查（Research 18 工具，四项全 ok）。
- T0 冒烟 17/17：提案 v1→改 v2→批复→批准→执行→成功→报告 EXPLORATORY→
  详情快照自洽（proposal_version==2、parameters.batch_size==8、
  冻结步骤含 `--batch_size=8`、metric_policy exploratory）——P1-A 冻结链
  走真实 PG 生效；P1-B linkage-ok 路径 intact。
- P1-B unavailable 与 P1-C 500 路径无法在线上确定性触发，以离线合成为准（如上）。

## T2（2026-09-08）：自主提案 kind＋Ask/Auto 门＋一次确认语义（未提交）

改动（`nexus/src/nexus/`，未装新依赖，`uv.lock` 零改动）：
- `proposals.py`：`kind` 判别（缺省 preset；`autonomous_experiment` 消费
  ExperimentScope、不要求 preset，`plan_hash` 即 `scope_hash`，steps 为空——
  实际命令写 attempt）；`scope_hash_for`/`validate_autonomous_scope`/
  `budget_for_scope`；`create/patch/request-approval` 全分支＋`public` 视图；
  DDL 增 `kind/scope/scope_hash` 列，老表 `ADD COLUMN IF NOT EXISTS` 补齐
  （与 approvals 同模式；旧行归一 preset）。
- `approvals.py`：审批行增 `proposal_kind/scope_hash/frozen_scope` 列（同上
  补齐）；自主绑定建票（`plan_hash`=scope_hash、预算由 scope 资源派生）；
  消费核验追加 scope_hash 交叉比对；核销返回值冻结体带 kind/scope。
- `experiment_runs.py`（新增）：run 登记（run_id=approval_id，幂等返回原行；
  重试不查审批 TTL）＋`record_attempt`（operation_id 确定性派生
  `run-op-NNNN`，终态拒绝追加）；PG `nexus_experiment_runs`＋内存降级。
- `execution_mode.py`（新增）：ask|auto 归一（未知拒）、显式值保存会话偏好
  （PG `nexus_session_prefs`＋内存）、未传默认 Ask（不偷升级）、偏好查询端点；
  `can_execute` 仅 Research+Auto。
- `request_scope.py`：`set_experiment_gate(mode, execution_mode)` 上下文；
  `agent.py`：`_tools_for_mode(mode, execution_mode)`（Research+Ask 不绑定
  `run_reproduction`；General 传 auto 也不放行）＋`build_agent` 传 effective；
  `main.get_agent` 缓存键 `(mode, model, execution)`（旧二元桩回退兼容）。
- `tools/reproduction.py`：执行门（有门信息强制 Research+Auto；旧 preset
  无门信息兼容直调，自主无门信息 fail-closed）；`run_reproduction` Ask 拒
  `EXPERIMENT_EXECUTION_DISABLED` 零提交；`execute_approved_reproduction`
  接门参＋自主票据转交；新增 `execute_autonomous_experiment`（门→核销锁
  定→run 登记→`mark_proposal_executed`，不碰旧 Worker）；自主审批卡只显
  目标/资源/最长时/自动排错范围（scope_hash 不下发）。
- `main.py`：`ChatRequest.research_execution_mode`（未知 400；未传默认 Ask；
  显式合法存偏好）；chat/stream 注门＋回 effective；提案端点 kind/scope；
  `repro/execute` 接门参（`EXPERIMENT_EXECUTION_DISABLED`→403 等新码映射）；
  会话偏好 PUT/GET 端点；lifespan 建 run/prefs 表；审批列表自主摘要。
- `backend/.../nexus_proxy.py`：chat 双链路＋execute 未知执行模式 400；
  提案 create/patch 转 kind/scope；execute 透传门字段；偏好查询/保存反代
  （全部 `require_nexus_use` 门下，D10 门计数 32→34）。

回归证据（命令＋结果）：
- nexus 全套件 **181 passed**（含新增 `test_autonomous_approval.py` 13 项：
  单批准排错/改 scope 失效/preset 指纹保持/模式默认与拒绝/Ask 双零提交/
  General 无权/模型无参改门/审批卡脱 hash/HTTP 全链＋门/偏好往返）。
- Backend nexus 域 7 文件：82 passed＋11 skipped；3 项 internal“无 token 503”
  在 7 文件同跑时 401——基线同组合同样失败（既有用例间顺序污染，非本批回归；
  单跑/3 文件跑全过）。
- 前端契约 88/89（唯一失败为 CourseLayout 他线旧断言，XH 合并引入）；
  D10 门数 32→34（本批新增 2 个同门控偏好端点，断言已同步）。
- `git diff --stat -- nexus/uv.lock backend/pyproject.toml` 为空（无新依赖铁证）。

未验证项：
- 真实 PG 下新列 CAS/幂等（语句与 approvals 同模式，线上核验待部署后）。
- 线上 Ask/Auto 真实冒烟（待部署后一次性验证账号走读＋偏好＋门拒绝）。
- UI 选择器属 T5；正式 Word/LaTeX 与干净 B 仍按任务书为后续交付。

## 线上验证（2026-09-08，部署 f8379d3e，一次性验证账号 `nx_verify_t2_e5bde8c6`）

- 发布＋前端构建（v6 NexusPage chunk 正常产出）＋Runtime rsync（diff 干净）
  ＋双服务重启＋健康检查（Research 18 工具，四项全 ok；工具面实证 Ask 无
  `run_reproduction`、Auto 有）。
- T2 冒烟 18/18（合成账号，无真实数据）：自主提案 kind/scope_hash 32 位→
  请求审批→本人批准→Ask 执行 403 `EXPERIMENT_EXECUTION_DISABLED`→未知模式
  400→Auto 执行建 run（run_id=approval_id）→重试同 run 且 deduped→改 scope
  出 v2 后旧票据 409 `APPROVAL_PROPOSAL_CHANGED`→偏好默认 ask/未知 400/保存
  auto→chat 未知模式 400（零 LLM 消耗）→preset 提案/审批/Ask 执行 403
  （零 Worker 提交）→待办列表/前端 Nexus 页 200。
- 真实 PG 下验证通过：提案锁 CAS、run 幂等、偏好落盘（同账号同会话恢复 auto）。
  上两项“未验证”关闭；剩余未验证仅 UI 选择器（T5）与正式输出物。

## T3（2026-09-08）：无 preset 入口 prepare_experiment（未提交）

新增 `nexus/src/nexus/experiment_intake.py`（任务书 §2 形状不变：scope 经
T2 自主提案落盘）、`nexus/tests/test_experiment_intake.py`（13 项）；修改
`tools/reproduction.py`（no_preset 分支加法指引 `suggested_tool`）、
`tools/__init__.py`（注册）、`agent.py`（Research-only＋提示词一句）。

- `prepare(target, objective)`：GitHub 直达／论文引用→web_search 找仓库
  （作者页无机器可读代码字段，搜“<标题> github”是诚实机制）／空目标或
  不可达→need_input（问题 ≤3，非逐字段表单）；只准备不执行。
- 初始 repo 固定 revision（GitHub branch SHA；取不到记 note，T4 记录实际
  SHA）；License 取 API SPDX（verified），未知如实进 missing_inputs，不阻止
  试跑（执行前核验交 T4 门）；环境声明只记“识别到/未识别到”，版本留给沙箱
  试验；data_refs 默认为空（reproduce 才进 missing）；默认资源即服务端声明
  值（cpu 2／mem 4096／disk 10240／wall 3600，容量核对属 T4）。
- fixture:// 仅测试 Reader 识别：默认 Reader 下拒 `TARGET_UNSUPPORTED`；
  注入 Reader 才试读（不可达→need_input）。Ask 保留准备工具（仅执行被禁），
  General 不可见；模型无模式入参（沿 T2 门）。
- 回归：nexus 全套件 **194 passed**（新增 13 项：任务书示例形态夹具＋
  preset 指纹保持＋论文找仓＋License 两态＋三 mode 推断＋歧义/不可达问询＋
  摘要形状＋正式拒 fixture＋工具面/SCOPE 门＋no_preset 指引＋Research 面）；
  `uv.lock` 零改动；Backend/前端无改动。

未验证项：
- 真实 GitHub API 的 revision/SHA/License 形态（本地合成覆盖；在线验证待
  部署后用已核验 License 的公开仓库走读）。
- 真实模型是否按提示词选用 prepare（属 T7；脚本化覆盖见 T4）。

## T4（2026-09-08）：自主安装/试跑/修复循环（未提交）

新增 `nexus/src/nexus/experiment_agent.py`、`nexus/tests/test_experiment_agent.py`
（3 项）；修改 `experiment_runs.py`（状态/线程/取消列＋老表 ALTER）、
`config.py`（`repro_control_url/token` 加法）、`tools/reproduction.py`
（核销后调度后台图）、`main.py`（lifespan 注册实验 profile）；
`agent.py` 经论证零改动（隔离靠构造＋测试锁定，见下）。

- 实例级装配（实测结论）：`excluded_tools` 合并为并集语义，per-model 覆盖
  无法重新开放 execute；实验图改走独立 provider 键 `nexus-experiment`
  （`_ExperimentChatOpenAI` 只改 LangSmith `ls_provider`，API 模型/端点不变；
  独立 profile 仅禁 task＋禁子代理）。全局 openai profile（主聊天三模式）
  一字未动；Ask hostile execute 照拒（测试锁定）。
- `build_experiment_agent(backend, checkpointer, model)`：原生文件/execute
  经 run 绑定 Backend 进沙箱；Todo＋Compact 保留；提示约束只描述任务
  （自行定安装步骤、看退出码修依赖继续、不逐步报批、不改指标凑 PASS）。
- 长运行：`execute_bound_run`（单 run 单执行者锁；意图先落盘，attempt 只在
  完成后追加→恢复不重放；后台持有图执行，HTTP 断开不杀；取消旗启动/结束
  检查，执行中取消由控制服务完成，T5 接 Console 链）；`reproduction` 核销
  后 fire-and-forget 调度（内部全捕获，即返 running）。
- 环境路线：`select_environment_route` 按工作区声明选择并记首个 attempt；
  repo2docker 命中 fail-closed（`ROUTE_NOT_DELIVERED`，T7-B 验收时接构建器，
  不等同基础镜像安装）；requirements/脚本走预置容器 pip/conda。
- 控制服务未配置 → run 落 failed（`SANDBOX_NOT_CONFIGURED`），不静默 running；
  常驻部署待生产决策（沿 T1-b 未竟）。
- 回归：nexus 全套件 **197 passed**（新增 3 项：脚本化“读→装→缺包→查错→
  修复→重跑”走真图＋真 Adapter＋假容器，审批恒 1、execute≥3、先败后成、
  末退出码 0、原生文件工具；实例隔离；Ask 敌意拒绝）；`uv.lock` 零改动；
  Backend/前端无改动。

未验证项：
- 真实容器＋真实模型的修复循环（假容器只仿 shell；T7-A/B 用合成仓库＋
  真容器＋脚本化模型先验协议，再用真实模型验收）。
- 跨进程单执行者（进程内锁＋状态机已备；多副本部署时需认领 CAS，T5）。

## 线上验证（2026-09-08，部署 432c195d，一次性验证账号 `nx_verify_t2_790e4ff5`）
- 发布＋前端构建通过＋Runtime rsync（diff 干净）＋双服务重启；健康全 ok，
  工具面实证 `prepare_experiment` 进 Research Ask/Auto、General 无；
  重启后 error/warning 日志零条目（新列 ALTER＋ensure 干净）。
- T2 回归冒烟 18/18（e2e-t2.py）：自主全链、Ask/Auto 门、scope 漂移失效、
  偏好往返、preset 零提交回归全过（T4 调度器上线后行为不变：即返 running，
  后台无控制服务时 run 落 failed，不静默）。
- T3/T4 线上行为：prepare 走聊天工具面（已在 health 工具面实证）；
  真实 GitHub 走读与真容器循环待 T7（需 License 已核验仓库＋控制服务常驻，
  另行授权）。

## T5（2026-09-08）：持久运行、Console 与取消复用（未提交）

新增 `nexus/src/nexus/experiment_store.py`（控制台读模型＋恢复接管）、
`nexus/tests/test_experiment_recovery.py`（5 项）、
`backend/tests/test_nexus_runs_provider.py`（10 项）；修改 Runtime
`main.py`（console/cancel 端点）、`experiment_runs.py`（attempt operation_id
入参）、`experiment_agent.py`（执行器记真实 op id＋cancel_bound_run）、
`tools/reproduction.py`（核销后登记 autonomous linkage）；Backend
`nexus_proxy.py`（provider 分支/合并/取消/上下文投影）、`nexus_internal.py`
（授权取消分派＋job_id 放宽）、`nexus_run_service.py`（cancelled 终态）；
前端 `nexus.js`/`nexusAdapter.js`/`NexusPage.vue`/
`NexusExperimentWorkspace.vue`/`reproShared.js`（选择器＋合并批准＋工作台
复用）；契约测试＋2（T5 选择器/工作台），D10 门数 34→35。

- 恢复：重启后只接管查询（adopt_running_operation，零 submit）；attempt
  只在完成后追加（真实 op id），恢复按 id 续查；控制失联 console 显示
  reconciling，存储仍为 running；取消旗＋回收确认后 cancelled（不可达
  503，不伪装）。
- Backend：autonomous linkage（job 为空）进同一 run 表；列表/详情按
  provider 分派合并 Runtime console（attempt 投影）；用户取消直达 Runtime；
  Agent 取消仍走一次性授权；备注/重命名/隔离回归。
- 前端：Research 输入框 Ask/Auto 分段（General 隐藏；服务端偏好真相源，
  保存失败本地缓存如实提示）；Ask 下“切换 Auto 并批准执行”一次完成；
  活跃 run 注明继续运行＋保留取消；工作台渲染 attempts（阶段条仅 Worker）；
  Stop 与取消分离保持；Ask 复跑禁用＋原因。
- 回归：nexus **202 passed**；Backend nexus 域 92＋11 skipped（3 项 internal
  无 token 断言为基线同组合既有用例间污染，已在 T2 轮 stash 对照）；
  前端契约 90/91（唯一失败为 CourseLayout 他线旧断言）；`vite build` 通过；
  eslint 12 条均为存量（对照未动区域一致，无新增）；`uv.lock` 零改动。

未验证项：
- 线上真实 PG 的 ALTER（runs 新列经 lifespan ensure；待部署后看日志＋冒烟）。
- 真实控制服务下的恢复/取消全链（需常驻部署，另行授权）。
- 真实模型＋真实用户的 Ask/Auto 交互验收（属 T7）。

注意：本轮 `NexusPage.vue` 与另一在制品会话改动落入同一文件不同区域
（对方在 capabilities/suggestions 区，本批在 Ask/Auto 与 run 接线区），
提交时需按 hunk 拆分，勿整文件照单收。

## T5-1（2026-09-08）：真火打通后的两处修正（未提交）

真火点火（合成账号 `nx_verify_fire_331785ed`，setup 小目标）一次跑通：
批准→后台图在 8 秒内驱动 7 个真实 operation（路由 ls、原生 ls/read/
glob、目标 `echo hello-autonomous` 输出正确、复核 ls），全 exit 0，
Runtime 日志零错误。常驻链路（审批→调度→Adapter→控制→容器→回写）打通。

线上实证发现的两处问题（均已修，均有回归测试）：

1. **取消后被改写（bug，已修）**：用户取消与图内错误竞态时，图的异常
   收尾把 `cancelled` 改写成 `failed`（第二轮冒烟 `nx_verify_t5_f2d02ccf`
   实证）。修：新增 `set_terminal_status`（终态互斥＋取消旗收敛），异常
   路径与所有终态落盘经它走；循环内每次落盘前查旗，置位即收尾 cancelled。
2. **attempt 记录不全（gap，已修）**：只记了 `execute`，漏掉经 funnel 产生
   control operation 的原生文件工具（实证：7 个 op 只记 3 个 attempt）。
   修：`write_file/read_file/edit_file/ls/glob/grep/delete` 的工具调用同样
   记录（成功 0/失败 1，命令摘要），与 control operation 1:1 对账。
3. **并行归因错位（gap，已修）**：`last_operation_id` 在并行批量下把多个
   结果记到同一个 op（实证：op-0010 被记 4 次）。修：Adapter 记提交日志，
   执行器按命令文本精确匹配＋已认领去重，对不上返回空串不冒充。

回归：nexus 全套件 **207 passed**（新增 5 项：终态守卫、文件工具映射、
生产记录全覆盖、启动前取消零提交、顺序归因精确）；`uv.lock` 零改动。

## 线上验证（2026-09-08，部署 2e388895）

- 发布＋Runtime rsync（diff 干净）＋三服务重启＋健康全绿＋零 error 日志。
- 取消修正实证（`nx_verify_t5_d4909af3`）：用户取消后 console 保持
  **cancelled**（此前会被改写成 failed），11 个 attempt 全保留。
- 归因修正实证（`nx_verify_fire_79b7a801`）：新 run **succeeded**，
  6 个 attempt 与 op-0001~op-0006 精确 1:1、全 exit 0。
- 成功态容器暂留（T6 回收）：两次点火各留 1 个空闲任务容器（无 CPU
  占用，镜像共享磁盘），报告产物化后回收的逻辑归 T6。
- T5 在此关闭。剩余未验证：真实模型＋真实用户的 Ask/Auto 交互验收
  （T7）、正式 Word/LaTeX 与干净 B（SR6）。

## T6（2026-09-08）：交付环境配方与真实结果（未提交）

新增 `nexus/src/nexus/experiment_report.py`、
`nexus/tests/test_experiment_report.py`（10 项）；修改 `main.py`
（`POST /repro/runs/{id}/report`）、`nexus_proxy.py`（`POST
/runs/{id}/report` 反代，D10 门数 35→36）、`nexus.js`、`NexusPage.vue`
（`@report`＋`requestAutoReport`）、`NexusExperimentWorkspace.vue`
（终态自主 run 的"生成报告"按钮，Ask 下禁用并给原因）；
`test_nexus_runs_provider.py`（＋1 报告代理）、契约测试（＋T6 断言）。

- 配方：repo 修订（SHA 才算 pinned，否则如实标注）＋实际命令序列＋
  镜像 digest＋网络/资源＋数据声明＋日志引用；seed 未跟踪如实 null。
- 判定四分量：environment_ready / execution_succeeded / metric_verdict /
  clean_verification；无指标 not_evaluated、B 未做 not_run；绝不合成
  reproducible=true（任务书示例断言原样落地）。
- 修了什么：失败 attempt 与其后命令如实并列，不编造因果、不删失败记录，
  不出现 PASS 宣称。
- 交付：Markdown 报告＋Markdown 配方经既有 artifact_client 写入并关联
  run（owner 校验沿用）；两个产物都落盘后才调控制 cancel 回收（写入失败
  抛 502 且不回收）；内容版本 `experiment-report/1` 冻结供 NX-O1 复用。
- License：提案未持久化 License 结论，报告如实 unknown＋备注（执行前核验
  门与持久化归 T7，本批不放行 gate 也不伪装 verified）。
- 回归：nexus 全套件 **218 passed**；Backend nexus 域 94＋11 skipped
  （3 项系已知基线顺序污染）；前端契约 90/91（仅他线 CourseLayout）；
  `vite build` 通过；`uv.lock` 零改动。

未验证项：
- 线上真实 PG 的报告链（待部署后一次性账号走"执行→报告→下载→回收"）。
- 真实 GitHub 仓库的配方修订固定（T7 用已核验 License 仓库走读）。

## 线上验证（2026-09-08，部署 cd54d1ff，一次性验证账号 `nx_verify_t6_daa4a5fa`）

- 发布＋Runtime rsync（diff 干净）＋三服务重启＋健康全绿＋零 error 日志。
- 全链：setup 运行 succeeded → `POST /nexus/runs/{id}/report` 200 →
  metric_verdict=not_evaluated＋2 产物＋content_version=experiment-report/1
  → 产物下载 1239 字节非空 → 控制侧该 run 已 cancelled（落盘后回收实证）。
- 冒烟残留清理：4 个点火/取消演练沙箱＋1 个 e2e-t2 烟囱沙箱全部 cancel，
  任务容器零残留（均为合成 run，无真实数据）。
- T6 在此关闭。本批（T0–T6）完成一次确认自主实验闭环：提案→审批→执行→
  修复→恢复→报告，端到端可跑。转 T7（真实能力验收）与 SR6（正式输出）。

## T7（2026-09-09）：执行前核验门＋License 持久化＋真实仓库只读走读（未提交）

新增 `nexus/src/nexus/license_policy.py`（纯函数门：修订 SHA 固定＋
SPDX 白名单 MIT/Apache-2.0/BSD/ISC/CC0/Unlicense/PSF；未固定→
REVISION_NOT_PINNED，未核验→LICENSE_UNVERIFIED，白名单外→
LICENSE_NOT_ALLOWED）；新增 `nexus/tests/test_t7_license_gate.py`（8 项）。
修改 `proposals.py`（license 列持久化＋换仓重置 unknown＋冻结携带）、
`approvals.py`（frozen_license 列＋核销冻结）、`experiment_intake.py`
（核验结论落盘）、`tools/reproduction.py`＋`experiment_agent.py`
（核销后＋图启动前双门，fail-closed；图首消息带 pinned checkout 指令）、
`experiment_report.py`（报告取持久化 License，旧行回退 unknown）、
`main.py`（T7 三码→409）。`uv.lock` 零改动。

- 旧测试适配（门收紧的诚实更新）：`test_autonomous_approval`
  （_scope 修订固定＋MIT verified；HTTP 直建无结论→Auto 409
  LICENSE_UNVERIFIED，已核验提案经模块建＋HTTP 审批/执行 200 幂等）、
  `test_experiment_agent`（脚本两处 scope 修订固定＋MIT verified）。
- 回归：nexus 全套件 **226 passed**（218＋T7 新增 8）；
  前端契约 94/95（唯一失败仍为 CourseLayout 他线旧断言，与本批无关）；
  Backend 未动（跨环境 HTTP 代理，无直接 import）。
- 真实仓库只读走读（生产 `GitHubReader`，真实网络，只读 GET，无执行，
  无写入/部署；2026-09-09 本地实证）：
  - A `karpathy/micrograd`：License MIT verified，
    revision `7bc720e951fe422b8f8814aa5aa1b64121d26b4c`（master，
    与 GitHub branches API 一致），env `setup.py`，README 2048 字节
    （截断上限）；`prepare` 建自主提案 success（mode smoke，
    revision_pinned true，missing_inputs []），门 GATE_OK。
    选择依据：tiny 标量 autograd（CPU 纯 Python，README 示例无 torch
    可跑，`pip install micrograd`＋`from micrograd.engine import Value`），
    非 nanoGPT 别名，走 README/setup.py 路线。
  - B `pallets/flask`：License BSD-3-Clause verified，
    revision `d318b683471101618febed18996405ad26462110`（main，
    与 branches API 一致），env `pyproject.toml`（flit_core，
    与 A 不同环境入口），README 1639 字节；`prepare`＋门同样 GATE_OK。
    选择依据：BSD-3-Clause CPU Web 框架，pyproject 声明，
    smoke 经 import＋test client，与 A 形成双路线对照。
- Ask/Auto 门（代码＋单测层面）：Ask 直调/携票据仍 403
  EXPERIMENT_EXECUTION_DISABLED 零提交（旧测试保持）；Auto＋已核验
  提案建 run 成功，报告含持久化 MIT（`test_verified_proposal_…`
  实证先写产物后回收顺序不变）；HTTP 直建（未核验）Auto 409，
  不建 run——“一次确认”语义不变，确认的是已核验提案。

未验证项（需部署授权后另行线上实证，不在本批本地冒充）：
- 真实容器＋脚本化模型的合成仓库修复全链（T7-A/B：requires
  requirements 缺包/路径错误合成 fixture＋真容器；fixture 只放
  `deploy/repro-runtime/tests/fixtures/`，本次未建）。
- 真实模型（DeepSeek）自主读错修复（预写修复命令不算自主性实证）＋
  真实用户 Ask/Auto UI 全链（提供材料→Auto 一次确认→Console→刷新→
  下载报告/配方，确认次数记录；失败链/资源上限/跨用户拒绝）。
- repo2docker 构建路线仍 fail-closed（`ROUTE_NOT_DELIVERED`，未交付，
  不等同基础镜像安装；本次 B 选 pyproject 但走 base_container，
  repo2docker 未翻转）。
- 线上真实 PG 的 license/frozen_license 列补齐（lifespan ensure 已备，
  待部署后看日志＋冒烟）；正式 Word/LaTeX 与干净 B 仍归 SR6（见下节）。

## 线上验证（2026-09-08，部署 ac148ab2，一次性验证账号 `nx_verify_t7_*`）

- 发布＋Runtime rsync（DIFF-CLEAN，`license_policy.py` 到位）＋三服务
  active＋近 15 分钟零 warning 日志；current 指 `releases/ac148ab2`。
- 门生效实证（`nx_verify_t7_6d8950ec`）：直建未固定修订提案→审批→批准→
  Auto 执行 **409 `REVISION_NOT_PINNED`**（零 run、零容器，fail-closed）。
- 真实模型 Ask（同账号）：200 且命中 micrograd 关键词，零实验提交。
- 真实模型 Auto intake（`nx_verify_t7b_19facecf`，session t7b）：
  模型自主调 `prepare_experiment`（target micrograd，status success），
  落盘 `pp_9706ee542f77`（v1 draft，MIT verified，revision `7bc720e`
  pinned，smoke，missing_inputs 空），回显如实声明未执行、批准由用户
  决定——自主性实证（工具选择＋参数＋诚实陈述皆为模型行为）。
- 真实仓库执行（`nx_verify_t7c_4ba2b3ad`，intake→`pp_5fe140c393d9`→审批→
  Auto 执行 `apv_9d1c5fe8c4e6`）：门通过，run 启动，真模型驱动真容器
  完成 8 个 operation（多次 DeepSeek 200），随后一次 DeepSeek 调用返回
  **401 `invalid api key ****b27d`** → 图 fail-closed 落 failed（8 条
  attempt 保留，退出码均为 0；无伪造成功）。
- 失败 run 报告回收（同账号重登）：`POST /runs/{id}/report` 200，
  environment_ready=true，metric not_evaluated，2 产物（1869＋1342 字节），
  下载 1869 字节，落盘后回收触发。注意诚实缺口：报告
  execution_succeeded=true（按末 attempt exit 0 拼装）而 run status=failed
  （图侧 LLM 401）——判定口径差异如实记录，SR6 不以此冒充复现成功。
- 外部阻塞：DeepSeek key（尾号 b27d）现已持续失效（chat 亦 502），
  真实模型执行成功态待密钥轮换后重验；本次未读、未输出任何密钥，
  仅记录日志中的尾号与 401 事实。沙箱残留已随报告回收（best-effort）。
- T7 代码验收在此关闭；剩余真实模型成功态＋UI 全链待密钥恢复后补测。

## SR6（2026-09-09）：正式 Word/LaTeX 与干净 B（已提交，未完全关闭）

实现（`0d3ed981`＋5 个 fix：`d660efe8`/`db90f920`/`1bb54c53`/`45c3a65f`/
`ebb3c15c`/`28a7392a`/`59018542`/`0e15b886`，零新依赖，`uv.lock` 零改动）：

- `document_output.py`（新建）：冻结报告 Markdown→标准库手组最小合法
  OOXML（段落/标题/列表/表格/代码/引用）与自包含 main.tex（ctexart＋
  xelatex 标识）；docx 结构自检（zip＋部件＋段落数），tex 三重自检
  （结构/转义/括号，附反例测试锁住）；工具链存在才编译（禁
  shell-escape），缺席如实 TOOLCHAIN_MISSING。转换不改写事实。
- `experiment_clean.py`（新建）：全新沙箱（`{run}-clean-{nonce}` 单次
  使用）重放冻结配方 shell 步骤、逐条比对退出码；文件工具摘要
  （`glob` 等非 shell 形）跳过留痕不计数（`ls` 保留）；verdict 持久化
  （passed/failed＋规则版本 `sr6-clean/2`，口径变化旧结论过期重验）；
  异步 verifying＋后台落盘＋锁＋重启自愈；Ask 禁止（Auto 门）。
- 报告自动带出干净结论（无→not_run）；`formats` 端点写 word＋latex 双
  产物（content 版本 `experiment-report/1` 同源）；`clean-verify` 端点；
  Backend 新增 `word` 产物类型（base64 二进制分支，`docx` 仍拒绝，
  旧契约不变）＋双反代（D10 门数 36→38）；前端工作台指标页动作行＋
  双处理函数（Ask 下干净验证禁用，详情轮询直通 cleanStatus）。
- 回归：nexus **252 passed**；Backend runs/provider＋artifacts 新测全过
  （2 项 fails_closed 401 系干净树对照确认的基线顺序污染，非本批）；
  前端 96/97（唯一失败仍为 CourseLayout 他线旧断言）。

## 线上验证（2026-09-09，部署 0e15b886，一次性验证账号复用 T6/T7 号）

- 发布＋Runtime rsync（DIFF-CLEAN）＋三服务 active＋零 error 日志。
- formats 全过（`apv_9d1c5fe8c4e6`）：200，derived_from
  experiment-report/1，word 4828 字节（PK 头可下载）＋latex 4199 字节
  （`%` 头可下载），docx 自检 ok（52 段落）＋tex 自检 ok，compile
  如实 TOOLCHAIN_MISSING（服务端无 xelatex/pdflatex；编译证明待工具链）。
- clean-verify 门：未知模式 400、Ask 403（`CLEAN_EXECUTION_DISABLED`）。
- clean-B 全链（`apv_886a1557fe06`，echo/ls 快步骤）：触发 verifying→
  轮询→**passed**（deduped）→报告自动带出 passed（`clean_verification`
  键）。新鲜沙箱、nonce op id、逐条退出码一致、用后回收。
- 途中抓到的真问题（均已修，均有回归测试，均如实记录）：
  1. hunk 拆分遗漏 `content_b64` 模型字段→线上 422（`d660efe8` 修；教训：
     共享文件按 hunk 内容 PC 双检，不只看行数）。
  2. 代理透传签名键被 Runtime forbid 拒→只透传声明字段（`db90f920` 修）。
  3. 同步重放在 60s 代理后必超时→改异步 verifying（`1bb54c53`）。
  4. 重放 op id 跨次复用→控制面 409 误杀→per-replay nonce（`ebb3c15c`）。
  5. 超时 cancel 把沙箱打成终态→后续重放永久 409→单次 id＋超时不毒化
     （`ebb3c15c`＋`0e15b886`）；规则口径变化→结论版本 gating（`59018542`）。
  6. 文件工具摘要（`glob …`）非 shell 命令→跳过留痕不计数（`28a7392a`；
     否则所有用文件工具的 run 必误判 failed）。
- micrograd run（`apv_9d1c5fe8c4e6`）的干净验证：机制侧 6 步匹配（含
  exit=127 的复现）＋第 9 步诚实分歧（记录 0/重放 127，命令在干净环境
  不存在）→ failed 结论正确落盘；此后该 run 的 apt 步骤在冷容器持续
  超时（未知≠通过，未伪装）。另有约 40 个调试期孤儿沙箱（空转、无 CPU，
  共享镜像层），待控制面重启/ prune 时回收。
- 未关闭项：LaTeX 编译证明（需 TeX Live 工具链，apt 安装另需授权）；
  真实模型执行成功态（DeepSeek key 尾号 b27d 持续 invalid，待轮换）；
  真实用户 UI 全链手工走读（按钮已上线，随密钥恢复后补测）。
