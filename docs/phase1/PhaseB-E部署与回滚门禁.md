# Phase B--E 部署、回滚与验收门禁

## 适用范围

本文覆盖题库与答题证据（G1--G2）、Judge0 沙箱（G3）、JSAV（G4）、R2
课程检索（G5）、TeachingAgent/WebResearch（G6--G7）、媒体时间轴（G8）及
Evidence/GraphSnapshot（G9）。它是部署操作说明，不替代代码、数据库迁移或
人工内容审核。

## 上线前检查

1. 备份应用数据库；在隔离副本执行 `access_control_preflight`，确认没有课程
   所有者、选课关系或角色映射孤儿数据。
2. 用应用启动时的迁移器创建新增表。不得用生产数据作为测试 fixture，也不得
   通过删表或修改既有字段语义来“迁移”。
3. 每门课程用 `CourseCapability` 单独启用题库、认知、图谱、Evidence、沙箱等
   能力；默认关闭或回退到既有行为。
4. 检查课程成员关系和教师策略。所有读取、生成、发布与交付必须走
   Course Access v1，不得以 `User.role` 或 `Course.teacher_id` 兜底授权。
5. 运行后端目标回归、前端单测和生产构建。测试不得调用付费 LLM、TTS、PPT 或
   数字人服务。

## 数据和变更边界

| 能力 | 主要表/资源 | 启用前条件 | 回滚方式 |
| --- | --- | --- | --- |
| 题库、映射、作答 | `question_bank_*`、`question_attempts` | 题目已归属课程、映射被接受、教师发布 | 关闭能力；撤回题目版本，不删除审计版本 |
| 六维认知与推荐 | `cognitive_states`、`learning_evidence_records`、`recommendation_records` | 学生和课程作用域有效；输出有策略版本和证据 | 停止写入/展示新推荐，保留历史记录 |
| 图谱/Evidence | `course_evidence_records`、`graph_snapshot_records`、`graph_node_reviews` | 人工审核、课程隔离、可回溯 Evidence | 切回前一不可变快照；Evidence 失效而非改写历史引用 |
| 媒体时间轴 | `media_assets`、`media_timeline_cues` | `object_key`、内容哈希与资源版本齐全 | 关闭时间轴，播放器回退旧节点时间；不自动调用 TTS/数字人 |
| WebResearch | `web_research_*`、`external_references` | 课程开关、HTTPS 提供商、域名白名单 | 关闭课程开关；外部参考从不写入课程事实或认知结论 |

课程删除是特例：它会在同一事务中删除该课程的受限数据。课程删除后学生无法
访问其历史引用；“保留 Evidence 并标为 stale”只适用于课件重解析/替换，不能
作为已删除课程的对外历史存档。

## Judge0（G3）

`deploy/judge0/docker-compose.yml` 仅监听 `127.0.0.1:2358`，后端通过
`SandboxClient` 调用；前端不得直接请求 Judge0。启动前复制
`deploy/judge0/.env.example` 为本机未提交的 `.env` 并替换全部密钥。

当前默认配置可验证健康检查、鉴权、队列与后端降级，但**不等同于可以安全执行
学生代码**。Judge0 的 `isolate` 在当前 Docker Desktop 路线需要 server 与 worker
获得 `privileged`。该选项默认关闭；只有在专用、加固、隔离的 Linux Judge0 主机
完成主机级安全审查后，运维人员才能显式设置两个
`JUDGE0_*_PRIVILEGED=true` 并执行真实代码验收。不得为了本机演示在主应用主机
绕过此门禁。

回滚：设置 `JUDGE0_ENABLED=false` 或关闭课程 `coding_sandbox` capability。学习
主流程仍正常工作，API 返回明确的 sandbox unavailable 降级结果。

## R2、TeachingAgent 与外部工具

R2 仅在课程侧车可用、作用域有效、Evidence 闭合且课程 capability 已启用时进入
正式回答；任一条件失败必须回退 V1，并记录 `retrieval_source` 与拒答原因。关闭
`R2_STUDENT_ANSWER_ENABLED` 或课程 capability 即可一键回退。

当前 TeachingAgent bootstrap 仍是**单个报告绑定的 Shadow/演示运行时**，不是通用
生产编排器。报告、课程作用域、LLM 配置或端口任一缺失时端点应保持
`503 TEACHING_AGENT_NOT_CONFIGURED`。要晋级为多学生生产运行时，必须先提供
课程隔离的真实 StudentState、Cognition、Retrieval、Recommendation、Sandbox 和
append-only LearningEvent adapter，再通过 Canary、教师审核和回滚演练。

WebResearch 必须同时配置 HTTPS provider URL 和 API key；外网内容仅为带时间和
来源的“补充参考”，不得更新掌握度、推荐优先级或课程图谱。

## 本地存储到 OSS

媒体和数字人产物使用 `MediaAsset.object_key` 作为稳定标识，而不是把绝对本机
路径泄露给客户端。迁移步骤：复制对象、校验 content hash、写入 OSS URL、切换
asset backend、验证时间轴读取，最后在保留期后清理本地副本。任何一步失败都可把
backend 切回 `local`，不改变 `object_key`、Cue 或前端契约。

## 服务器部署布局（2026-08-14 规范后）

云服务器 `120.26.104.247` 采用 release 目录 + `current` 软链布局，唯一工作目录为
`/opt/smartcarb`：

```
/opt/smartcarb/
├── current -> releases/<短hash>   # 生效 release（nginx / systemd 都指向这里）
├── releases/<短hash>/             # 每次发布的完整 checkout，保留最近 5 个
├── shared/
│   ├── env/       # backend.env / database.env / runtime-paths.env / postgres.env
│   ├── venvs/     # backend-py312（后端虚拟环境）
│   ├── node_modules/frontend/  # 前端 pnpm 依赖缓存（构建复用）
│   ├── media/ models/ runtime/ backups/  # 媒体、模型、运行时、备份输出
│   └── scripts/   # backup.sh / healthcheck.sh（postgres 备份与健康检查）
└── scripts/       # smartcarb-release.sh / smartcarb-prune-releases.sh
```

硬约束与约定：

- **dist 不入 git**：前端构建产物由发布脚本在 release 内构建（复用
  `shared/node_modules/frontend`），构建命令直接调用
  `node node_modules/vite/bin/vite.js build`——不能走 `pnpm build`（pnpm 预检会因
  符号链接触发重装且无 TTY 中止）。
- **发布流程**：`bash /opt/smartcarb/scripts/smartcarb-release.sh [ref=dev-liu] [keep=5]`
  完成 clone → 前端构建 → 原子切换 `current` → 重启后端 → 健康检查 → 清理旧 release。
  保留策略由 `smartcarb-prune-releases.sh` 实现（保留最近 N 个，永不删除 `current`
  指向的 release）。
- **systemd**：后端 `smartcarb-backend.service` 为单一单元（已合并历史 drop-in），
  指向 `current/backend` + `shared/venvs` + `shared/env`，只回环监听 8000。
  postgres 备份/健康检查单元指向 `shared/scripts/*.sh` + `shared/env/postgres.env`。
  nginx 站点配置为 `/etc/nginx/sites-enabled/smartcarb`，root 指向
  `current/frontend/dist`，仓库 `deploy/nginx/frontend.conf` 与其保持一致。
- **清理隔离区**：历史遗留工作目录（`/opt/smartcarb-git`、
  `/opt/smartcarb-postgres-live`、`/opt/smartcarb/backend` 等）已移至
  `/opt/_cleanup-20260814/` 隔离，确认无引用后删除；其中含旧 `.env` 密钥副本，
  删除前注意密钥轮换。

