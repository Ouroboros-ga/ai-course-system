# CS 语料 RAG 上线验收（CR6）

> **状态：工具与发布编排已落地并自测通过；真实部署、小批/全量上线与登录验收
> 均未执行。** 需先取得批准 SHA、模型下载授权与目标环境窗口。本文既是执行
> 清单也是回执：未执行项一律不勾选，**工具通过不等于上线验收通过**。
> 日期：2026-09-08；基线 dev-liu 工作区（未提交）；迁移链
> `0068 -> dk20260908v1 -> dk20260908v2 -> dk20260909v1 -> dk20260909v2`。

## 1. 交付物与自测证据

| 交付物 | 用途 | 自测证据 |
|---|---|---|
| `deploy/systemd/smartcarb-corpus-embedding.service` | 本地 embedding 服务常驻（127.0.0.1:8310，loopback only） | 静态契约用例 + `bash -n` |
| `deploy/systemd/smartcarb-corpus-worker.service` | corpus_rag 构建 Worker（不认领旧 legacy_extraction） | 静态契约用例 + `bash -n` |
| `deploy/scripts/corpus-preflight.sh` | 只读预检入口（读受信任 env，输出 JSON） | 委托 `corpus_preflight.py`（下同） |
| `backend/scripts/corpus_preflight.py` | 只读预检核心：schema_head / source_manifest / model_ready / model_fingerprint / dimension / FTS / active_release / resource_margin | `test_corpus_preflight.py` 5 用例；数据库**只读引擎**（SQLite `mode=ro`、PG `default_transaction_read_only=on`） |
| `backend/scripts/verify_corpus_rag.py` | 检索验收：统计 / 引用可解析 / 延迟 / 错误码；默认 retrieval-only | `test_corpus_preflight.py` 3 用例（含生成问答必须显式开启+预算） |
| `deploy/scripts/smartcarb-release.sh` | 发布编排补齐：SHA 锁定 + Alembic 迁移 + Nexus 独立发布 | 静态契约用例 + `bash -n` |
| `backend/tests/discipline/test_corpus_preflight.py` | CR6 验收测试（10 用例） | `backend/.venv/Scripts/python.exe -m pytest backend/tests/discipline/test_corpus_preflight.py -q -p no:cacheprovider` → **10 passed** |

验证记录（2026-09-08，本地，合成密钥 + 隔离库）：
- CR6 用例 **10/10**；discipline 全量 **144/144** 通过（无回归）。
- 只读性由**外部证据**证明：运行预检前后数据库文件 sha256 + 全表行数逐表一致
  （不是读脚本自报的 `mutation_count`）。
- CLI 冒烟：无库/未冻结配置时如实报错并 exit 2（不伪造 ready）。
- 未验证：真实 E5 模型下载/加载、真实五来源语料、PG 真并发与 PG 上新迁移、
  登录后的页面与 Nexus 真实问答、真实部署。

## 2. 上线前只读清单（计划 §7.1，逐项打勾）

```bash
# 服务器上（不改动任何状态；退出码 2 表示存在阻断项，逐项修复后再发布）
bash /opt/smartcarb/scripts/corpus-preflight.sh
```

| 检查 | 报告字段 | 期望 | 本次 |
|---|---|---|---|
| 已部署代码版本 | `repo.commit/branch` | 等于批准 SHA | [ ] |
| 数据库迁移 | `schema_head.current == heads[0]`（唯一 head） | `dk20260909v2`（或当次批准 head） | [ ] |
| 来源登记 | `source_manifest.sha256/sets/files_available` | 五来源登记齐全，源文件就位 | [ ] |
| 模型文件与冻结配置 | `model_ready/model_fingerprint/dimension` | true / 已冻结指纹 / 384 | [ ] |
| embedding 服务 | `model.source=service`、`resource_margin.embedding_port_listening` | 8310 在听，指纹与配置一致 | [ ] |
| FTS 目录 | `fts.exists/writable`、`release_object_present` | 可写；当前版本对象落盘 | [ ] |
| 当前发布指针 | `active_release.release_id/status` | 上线前为空属正常；切换后为 ready | [ ] |
| 资源余量 | `resource_margin.{cpu_count,memory_available_mb,disk_free_mb}` | 满足模型常驻 + 构建预算 | [ ] |

同时人工核对（脚本不覆盖）：`/opt/smartcarb/current` 与 Backend 主进程 cwd、
`/opt/smartcarb/nexus-runtime` 实际版本与两个服务健康、语料目录
`/opt/smartcarb/shared/knowledge_corpus` 文件 hash/大小、pgvector 版本、
仓内发布脚本与服务器脚本一致（本次已补齐迁移与 Nexus 同步，见 §3）。

## 3. 获准后的执行顺序（计划 §7.2）

1. **冻结目标。** 记录 Backend/Nexus 目标 SHA、模型配置 hash、数据库前一
   revision 和源清单；备份数据库/配置/当前指针并验证可读；源码与模型用独立
   可恢复 staging，保留旧目录。
2. **部署兼容代码与迁移。**
   ```bash
   SMARTCARB_SKIP_PRUNE=1 bash /opt/smartcarb/scripts/smartcarb-release.sh <批准SHA> 5
   ```
   脚本顺序：克隆锁定 SHA → 前端构建 → `alembic upgrade head`（唯一 head 校验，
   失败即中止且不切 current）→ 切 current → 重启 Backend + 健康检查 →
   Nexus 同步（旧代码打 tar 备份到 `shared/backups/`，`uv.lock` 变化才
   `uv sync --frozen`）+ 重启 + `/health` → 记录 `RELEASE_INFO`。
   验收窗口内用 `SMARTCARB_SKIP_PRUNE=1` 保留旧 release；仅当确认无迁移/无
   Nexus 变更时才允许 `SMARTCARB_SKIP_MIGRATIONS=1` / `SMARTCARB_SKIP_NEXUS=1`。
3. **准备模型服务。** 模型离线预置到固定目录并校验；启动
   `smartcarb-corpus-embedding`，用预检核对指纹/维度/固定输入结果；启动
   `smartcarb-corpus-worker`（默认 `--pipeline corpus_rag`，不认领旧抽取任务）。
4. **建立小批。** 按登记范围构建 ≤1 万段落（中英文 + 至少两个主题），范围不足
   如实统计（命令已按 P0-1 修复后的 CLI 对齐）：
   ```bash
   python backend/scripts/import_discipline_corpus.py --source-set cs-public --dry-run
   python backend/scripts/import_discipline_corpus.py --source-set cs-public --limit-docs 200
   # 建构建 + 规划 embed 分片（输出 build_id / document_version_ids）
   python backend/scripts/manage_corpus_index.py create-build --scope cs-textbooks \
     --model-fingerprint "$CORPUS_MODEL_FP" --dimension 384 --max-chunks 10000
   # 向量化（预算到顶暂停可恢复；--max-batches 为 --max-items 别名）
   python backend/scripts/run_discipline_worker.py --pipeline corpus_rag --max-batches 20
   python backend/scripts/manage_corpus_index.py status --build-id "$CORPUS_BUILD_ID"
   # 组装候选 release（--from-build 自动取版本清单）+ 构建 FTS
   python backend/scripts/manage_corpus_index.py build --from-build "$CORPUS_BUILD_ID" \
     --model-fingerprint "$CORPUS_MODEL_FP" --dimension 384
   python backend/scripts/manage_corpus_index.py status --release-id "$CORPUS_RELEASE_ID"
   ```
   先显式 release 查询，不切全局指针。
5. **更新 Nexus 与前端。** 由 §2 的发布脚本完成（Nexus 独立目录/环境保留旧副本）；
   仅依赖确有变化且获准时 sync。
6. **激活与验证。**
   ```bash
   python backend/scripts/manage_corpus_index.py validate --release-id "$CORPUS_RELEASE_ID"
   python backend/scripts/verify_corpus_rag.py --release-id "$CORPUS_RELEASE_ID" \
     --suite public-cs --retrieval-only
   python backend/scripts/manage_corpus_index.py activate --release-id "$CORPUS_RELEASE_ID" \
     --expected-revision "$CORPUS_HEAD_REVISION"
   ```
   `verify` 报告须满足：`references.failed == 0`（引用 100% 属于本次 release 且可
   解析）、延迟分位可接受、`error_codes` 为空或已解释。生成问答**必须显式开启且
   有预算**（`--with-generation --max-generation-calls N`，且配置
   `VERIFY_CORPUS_GENERATION_URL/TOKEN`），默认不调用回答模型；API 正常但 Agent
   未使用原文仍视为接线未完成。
7. **扩大覆盖。** 先教材/中英百科，再按范围扩至 RFC/arXiv；每批缓存复用、独立
   就绪后切换，保留上一版本；不以“候选抽取筛选”永久丢弃资料。
8. **全量结项。** 登记文档 = 成功 + 排除 + 失败/待处理；失败待处理不为 0 时
   明确列出，不写“全库向量化完成”。

## 4. 回退（计划 §7.4）

| 故障 | 动作 |
|---|---|
| 索引问题 | 暂停新构建，核对上一 ready release 的文件/来源/模型，CAS 回切（`activate --expected-revision`）；不删除新产物 |
| 模型服务问题 | 查询自动 lexical 降级（`degraded_reasons: VECTOR_UNAVAILABLE`）；恢复固定模型服务与健康检查后恢复 hybrid，不跨模型查询旧向量 |
| 代码问题 | 分别恢复 Backend/前端 release（切 `/opt/smartcarb/current` 到旧 release 目录）与 Nexus 副本（`shared/backups/nexus-runtime-<旧SHA>.tgz` → `nexus-runtime/` 后重启 `nexus-runtime`）；**只切 current 不会恢复 Nexus** |
| 数据库 | 兼容字段与闲置表默认保留，不为应用回退做破坏性 downgrade |

回退清单（每次发布由脚本写入 `releases/<short>/RELEASE_INFO` 与
`nexus-runtime/RELEASE_INFO`）：commit / branch / alembic_before→after /
nexus_previous / released_at。

## 5. 验收门对照（计划 §8.1）

| 层级 | 证据要求 | 本次状态 |
|---|---|---|
| 数据 | 五来源统计对账；幂等；正文离开导入进程可回读 | 工具就绪；真实语料未执行 |
| 向量 | 指纹/维度一致；无 NaN/零向量；相同内容不重算；无静默截断 | 工具与用例就绪；真实模型未执行 |
| 检索 | 中英 Hit@10/MRR；相比旧 FTS 基线无关键回归；30 题 ≥27 命中 | `verify_corpus_rag.py` 就绪；真实题集未跑 |
| 无答案 | 20 条无答案/干扰用例记录 | `stats.no_answer_*` 就绪；未跑 |
| 引用 | reference_id 100% 属于本次 release、可解析；撤回不显示；伪造拒绝 | 用例覆盖解析/伪造；未在真实版本跑 |
| 消费者 | TeachingAgent 与 Nexus 真实检索 + 原文 + 来源对应；页面不止 112/106 | 未执行（需登录环境，见计划 §9.1） |
| 发布/恢复 | 半成品不可见；并发冲突不覆盖；断点续跑；迟到拒绝；引用不串块 | 用例覆盖；真实并发未验证 |
| 性能 | 热查询检索 p95 ≤3s；冷启动/吞吐/在线影响 | `verify` 报告延迟分位；未测 |

## 6. 未验证与风险（不得当作已通过）

- 真实 E5 模型下载/加载/对照评测（需下载授权）；`rag/config.json` 仍为
  `draft-unfrozen`（`model.revision/files_hash` 为空），预检会如实报
  `MODEL_CONFIG_UNFROZEN` 并拒绝宣称 model_ready。
- 真实五来源语料（本地无 JSONL）；全量向量化、扩量日历与 tokens/s 未测。
- PostgreSQL 并发、PG 上的新迁移与 pgvector 查询计划（SQLite 结果不能代替）。
- 登录后的学科页/学生页/Nexus 页逐项体验（清单见计划 §9.1）与有限生成问答。
- 本仓库未提交、未推送；部署脚本的 systemd 单元需人工 `systemctl daemon-reload`
  并按 §2 核对 env 文件（`shared/env/corpus-embedding.env` 需新增
  `CORPUS_EMBEDDING_MODEL_PATH` / `CORPUS_EMBEDDING_MODEL_CONFIG`）。
