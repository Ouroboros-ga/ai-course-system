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
