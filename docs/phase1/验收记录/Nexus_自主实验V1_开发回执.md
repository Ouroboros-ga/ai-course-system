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
