# 独立 PostgreSQL 部署与 SQLite 切换

该目录是主服务器上应用数据库的唯一 PostgreSQL 部署入口。它不管理 Judge0 的 PostgreSQL、Redis、PaddleOCR、LanceDB、媒体文件或模型文件。

## 准备

在服务器创建私有配置和数据目录：

```sh
install -d -m 700 /opt/smartcarb-postgres /var/lib/smartcarb-postgres/16/data /opt/smartcarb-backups/postgres /opt/smartcarb-migrations
install -m 600 deploy/postgres/.env.example /opt/smartcarb-postgres/postgres.env
```

编辑私有 `postgres.env`，填入彼此不同的 bootstrap、application 与 migration 密码。不得将该文件放回仓库。启动前记录固定镜像的 digest：

```sh
docker pull postgres:16.14-alpine3.23
docker image inspect postgres:16.14-alpine3.23 --format '{{index .RepoDigests 0}}'
docker compose --env-file /opt/smartcarb-postgres/postgres.env -f deploy/postgres/compose.yml up -d
```

应用服务只使用 `ai_course_app`，其连接串写入 systemd 的私有环境文件：

```text
AI_COURSE_DATABASE_URL=postgresql+psycopg2://ai_course_app:<URL_ENCODED_PASSWORD>@127.0.0.1:5432/ai_course
AI_COURSE_DB_POOL_SIZE=5
AI_COURSE_DB_MAX_OVERFLOW=5
AI_COURSE_DB_POOL_RECYCLE_SECONDS=1800
```

首次切换时，先运行 `sh scripts/enable_migration_role.sh`，再由临时 migration 账号执行 Alembic 与数据复制。完成后运行 `sh scripts/grant_app_privileges.sh` 与 `sh scripts/disable_migration_role.sh`；后端进程只能持有 application 账号，migration 账号保持 `NOLOGIN NOSUPERUSER`。

## 预演与切换命令

以下命令只针对备份快照和已经确认可清空的目标 PostgreSQL；不要在仍有用户流量时执行。

```sh
export PYTHONPATH=/opt/smartcarb-git/backend
export AI_COURSE_SQLITE_SOURCE_PATH=/opt/smartcarb-git/database/smart_class.db
export AI_COURSE_SQLITE_SNAPSHOT_PATH=/opt/smartcarb-migrations/<batch-id>/source.sqlite
export AI_COURSE_POSTGRES_TARGET_URL='postgresql+psycopg2://<temporary-migration-role>@127.0.0.1:5432/ai_course'
export AI_COURSE_MIGRATION_REPORT_DIR=/opt/smartcarb-migrations

sh ./deploy/postgres/scripts/enable_migration_role.sh
python -m app.scripts.sqlite_to_postgres snapshot --batch-id <batch-id>
python -m app.scripts.sqlite_to_postgres plan --batch-id <batch-id>
python -m app.scripts.sqlite_to_postgres copy --batch-id <batch-id> --allow-replica-role
python -m app.scripts.sqlite_to_postgres verify --batch-id <batch-id>
sh ./deploy/postgres/scripts/grant_app_privileges.sh
sh ./deploy/postgres/scripts/disable_migration_role.sh
```

复制命令仅在目标库为空、版本为当前 Alembic head、SQLite 快照一致并且临时迁移账号可设置 `session_replication_role` 时执行。复制失败会回滚目标事务，源 SQLite 不会被改写。

在 Nginx 维护模式内完成后端健康检查、课程 2、上传/解析、GraphRAG、LanceDB、PPT manifest、Judge0 和管理员任务并发配置验证，再解除维护。开始接收新写入后，不再直接回切 SQLite；此时采用 PostgreSQL 备份与前向修复。

## 备份与恢复

加载私有环境文件后执行 `sh scripts/backup.sh` 生成 custom-format dump 与 SHA-256 文件。systemd 模板每天 UTC 03:20 运行一次、周日额外保留四周副本；每月在独立目标库用 `pg_restore` 做恢复演练。SQLite 最终快照至少保留 30 天。

安装两个 timer 模板后，备份和健康检查都会进入 systemd journal：

```sh
install -m 644 deploy/postgres/systemd/*.service deploy/postgres/systemd/*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now smartcarb-postgres-backup.timer smartcarb-postgres-health.timer
```

`healthcheck.sh` 每十分钟确认数据库可连接、连接数/上限、慢查询日志阈值、`pg_stat_statements` 统计是否启用、备份目录磁盘余量和最近备份年龄；状态异常会以非零退出，供宿主机监控或 journal 告警接收。慢查询正文只保留在受限 PostgreSQL 日志中，不由脚本输出。
