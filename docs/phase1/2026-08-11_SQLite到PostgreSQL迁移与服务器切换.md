# SQLite 到独立 PostgreSQL 的迁移与服务器切换

日期：2026-08-11。本文是当前 Demo 服务器的数据库切换实施基线；代码事实以 `backend/app/models/database.py`、Alembic 迁移和 `deploy/postgres/` 为准。

## 已落地的准备

- 运行时支持 PostgreSQL 连接池、连接存活探测和 UTC 会话；SQLite 仍是本地默认。
- `0047` 修复 PostgreSQL 下课程构建 lease 索引，约束仅覆盖 `queued/running`，不再错误限制同课程的历史构建记录。
- `app.scripts.sqlite_to_postgres` 只能读取 SQLite Backup API 生成且带批次校验文件的快照，目标必须为空且在 Alembic head；复制、摘要比对、外键反查和序列重置在单一 PostgreSQL 事务中完成。
- 每个迁移批次保留无原始业务内容的报告：表计数、NULL 统计、主键边界、规范化 SHA-256 摘要、外键结果与 SQLite 文件摘要；连接串和密码不写入报告。

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

## 当前未完成的外部动作

截至 2026-08-11 的隔离预演，服务器已在独立工作树启动临时 PostgreSQL 16 容器（仅 `127.0.0.1:55432`）并向既有后端 venv 安装 `psycopg2-binary==2.9.12`；生产服务未重启、生产 SQLite 未读取或导入、systemd/Nginx 未切换。临时库已验证 `0001 → 0047`、局部唯一索引、合成 SQLite `plan/copy/verify`、类型归一化、外键反查和失败事务回滚（5 项定向测试通过）。

## 2026-08-11 隔离预演后的剩余边界

- 已修复并验证历史迁移中的 PostgreSQL 方言差异：布尔/枚举字面量、SQLite `DATETIME` DDL、数字人状态枚举和 DocumentIR 外键重建顺序。
- 迁移工具不复制 Alembic、脱敏迁移和 schema migration 账本；目标保留自身迁移历史，且只在复制校验成功后写入本次迁移摘要。`0045` 的确定性默认并发配置会在同一事务内替换为源库配置。
- 尚未对现有服务器 SQLite 做热快照或预演；该实际数据演练、30 分钟维护窗口、正式导入、服务切换及业务验收仍需要单独授权。
