# SQLite 到独立 PostgreSQL 的迁移与服务器切换

日期：2026-08-11。本文是当前 Demo 服务器的数据库切换实施基线；代码事实以 `backend/app/models/database.py`、Alembic 迁移和 `deploy/postgres/` 为准。

## 已落地的准备

- 运行时支持 PostgreSQL 连接池、连接存活探测和 UTC 会话；SQLite 仍是本地默认。
- `0047` 修复 PostgreSQL 下课程构建 lease 索引，约束仅覆盖 `queued/running`，不再错误限制同课程的历史构建记录；`0048` 将历史 `media_release_items → script_nodes` 失效引用定义为 PostgreSQL `NOT VALID` 外键，旧发布快照原样保留，后续写入仍受外键校验；`0049/0050` 遗留的小写枚举标签仅保持类型兼容，`0051/0052` 补齐 SQLAlchemy 实际使用的大写成员名并归一化 `evidence_render_assets.asset_type`、`source_material_versions.parse_status`、`source_materials.status`。导入器保留源 SQLite 的大写成员名，未知枚举继续拒绝。
- `app.scripts.sqlite_to_postgres` 只能读取 SQLite Backup API 生成且带批次校验文件的快照，目标必须为空且在 Alembic head；复制、摘要比对、外键反查和序列重置在单一 PostgreSQL 事务中完成。
- 每个迁移批次保留无原始业务内容的报告：表计数、NULL 统计、主键边界、规范化 SHA-256 摘要、外键结果与 SQLite 文件摘要；连接串和密码不写入报告。对 `media_release_items:node_id` 这一已知历史关系，报告必须证明源/目标失效引用数量完全一致；任何其他关系的失效引用仍会 fail-closed。

## 服务器边界

- 应用 PostgreSQL 使用独立容器、卷和账户，仅绑定 `127.0.0.1:5432`。
- Judge0 的 PostgreSQL、Redis、PaddleOCR、LanceDB、媒体、模型与 Docker volumes 不属于此次数据复制范围；业务表中的 object_key 和索引元数据会被复制。
- 应用账号无超级权限；仅维护窗口内显式启用的独立 migration 账号可关闭触发器导入旧数据，完成后强制为 `NOLOGIN NOSUPERUSER`。
- 未开放公网端口；真实密码只存服务器 `600` 权限的环境文件。
- `pg_dump -Fc` 日备份保留 7 份、周日副本保留 4 份；独立健康 timer 检查连通性、连接数、慢查询日志阈值、磁盘余量和备份年龄，恢复演练仍需每月人工在隔离库执行。

## 强制验收顺序

1. 在隔离 PostgreSQL 上从 `0001` 升级到当前 head，并执行 PostgreSQL 定向测试。
2. 使用在线 SQLite 热快照做预演，验证表集合、行数、摘要、外键、序列和核心课程读取；预演不超过 15 分钟才允许安排 30 分钟维护窗口。
3. 维护模式内等待 `running` 任务结束，停止后端，生成最终 SQLite Backup API 快照并运行 `integrity_check`/`foreign_key_check`。
4. 创建空 PostgreSQL、Alembic 升级、复制、验证、授予应用账号权限并切换 systemd 环境。
5. 仍在维护模式内完成人工业务验收后才恢复写流量。

若第 4 或第 5 步失败，立即恢复原 systemd 环境并启动 SQLite 后端。恢复流量后，SQLite 不再是可安全直接回切的写库；后续故障以 PostgreSQL 备份/恢复或前向修复处理。

## 2026-08-11 实际服务器切换与枚举修正

- 服务器已在维护窗口内从 SQLite 切换到 PostgreSQL 16：最终 SQLite Backup API 快照为 116,801,536 字节，正式报告 `pg-cutover-20260811-01` 为 `verified`，162 张表和 89,561 行的规范化摘要匹配；14 条 `media_release_items:node_id` 历史失效引用在源/目标保持一致。
- 生产 PostgreSQL 只绑定 `127.0.0.1:5432`，应用账号没有超级权限，迁移账号切换后为 `NOLOGIN NOSUPERUSER`。首份 `pg_dump -Fc` 备份、每日备份计时器和十分钟健康计时器均已启用；最终 SQLite 快照以只读方式保留。
- 初次切换后发现 SQLite 导入器的枚举别名逻辑错误地将三列 SQLAlchemy 枚举成员名转为小写；`0049/0050` 只为这些既有错误值保留 PostgreSQL 类型兼容标签，材料和备课状态接口因而发生 `LookupError`。`0051` 在受控 autocommit 中补齐 `NEEDS_REVIEW` 与 `PPT_SLIDE_IMAGE`，`0052` 在后续事务中归一化既有行；隔离 PostgreSQL 在 `0050 → 0052` 后验证三类小写残留均为零，ORM 可读取 3 条材料、3 条材料版本和 62 条渲染资产。
- 迁移工具不复制 Alembic、脱敏迁移和 schema migration 账本；目标保留自身迁移历史，且只在复制校验成功后写入本次迁移摘要。`0045` 的确定性默认并发配置会在同一事务内替换为源库配置。正式切换后 SQLite 不再是可安全直接回切的写库，后续故障使用 PostgreSQL 备份或前向修复。
