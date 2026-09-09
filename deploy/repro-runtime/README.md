# repro-runtime：自主实验执行控制服务（内网专用）

> 状态：T1-b 验证中。只接受 127.0.0.1 本机调用（Runtime 经内网 HTTP），
> 外网不得暴露。实验实例容器**不挂 Docker socket、不读宿主业务卷**；
> 只有本服务（容器管理面）持有 Docker 访问。

## 职责边界

- 本服务：SWE-ReX Docker 后端的薄 HTTP 封装——实例生命周期、命令执行、
  文件传输、取消回收、资源限额透传。不做审批、不做指标判定、不存业务。
- 调用方（Nexus Runtime `experiment_sandbox.py`）：身份/授权/预算/快照；
  审批与 Verification 仍归 Nexus 域。

## 接口（任务书 §2）

| 方法与路径 | 说明 |
| --- | --- |
| `PUT /sandboxes/{run_id}` | ensure：体为 `{scope_hash, resources}`；同 run 同 scope 幂等，异 hash → 409 `SCOPE_HASH_MISMATCH`；resources 超部署上限 → 422 |
| `POST /sandboxes/{run_id}/operations` | `{operation_id, command, timeout_s, request_hash?, fencing?}` 登记后执行；同 ID 同请求去重，不同请求 → 409 `OPERATION_ID_CONFLICT`；fencing 锁定后旧/空 token → 409 `FENCING_REJECTED`；超 run 时限 → 409 `WALL_TIME_EXCEEDED` |
| `PUT /sandboxes/{run_id}/fencing` | F2：轮换执行 fencing（恢复认领后新持有者接管；终态 409） |
| `GET /sandboxes/{run_id}/operations/{operation_id}` | 结果/状态查询（HTTP 超时≠进程停止） |
| `PUT /sandboxes/{run_id}/files/{path:path}` | 受限大小文件上传；路径限定 `REPRO_WORKSPACE_ROOT`（默认 `/workspace`），`..`/symlink 逃逸 → 422 |
| `GET /sandboxes/{run_id}/files/{path:path}` | 下载（截断/过大如实报错；上限 5MB） |
| `POST /sandboxes/{run_id}/cancel` | 先停操作，再回收实例；重复同一终态 |
| `GET /sandboxes/{run_id}` | 生命周期/活跃 operation/资源摘要＋`image`/`image_digest`（对账与配方用） |
| `GET /health` | 存活探针（无业务信息） |

资源与镜像（2026-09-08 审核修复后）：
- 容器限额由 ensure 携带的**已确认 resources** 派生（`--memory/--cpus/--storage-opt`），
  无声明时回退 `REPRO_TASK_DOCKER_ARGS` 或默认值；磁盘配额不被存储驱动支持时
  降级并在 run note 如实记录。
- 镜像拉取策略 `REPRO_TASK_PULL` 默认 **never**（缺镜像即启动失败，不静默联网拉取）；
  `GET /sandboxes/{run_id}` 暴露 `docker inspect` 得到的镜像 ID 供配方记录。
- 工作区根可经 `REPRO_WORKSPACE_ROOT` 配置；服务端可用容量上限经
  `REPRO_MAX_MEMORY_MB/MAX_CPUS/MAX_DISK_MB/MAX_WALL_TIME_S` 收紧。

鉴权：`Authorization: Bearer $REPRO_RUNTIME_TOKEN`（未配置则拒绝启动，
fail-closed）。监听：只绑 `127.0.0.1`。

## 本地开发（无 Docker 可跑单测）

```bash
uv sync --extra test
uv run pytest tests/test_swerex_adapter.py tests/test_service.py -q
```

`test_live_docker.py` 需真实 Docker＋运行中服务（`REPRO_RUNTIME_URL`/`TOKEN`），
默认跳过；只在授权的验证环境执行。宿主侧隔离断言（Memory/PidsLimit/
Privileged/Mounts/NetworkMode/无 docker.sock）用 `scripts/verify_host.sh
<container_name>` 在部署宿主执行（任务镜像内无 docker CLI，容器内无法自证）。

## 服务器验证部署（T1-b 一次性）

见回执 T1-b 节：构建镜像→ `127.0.0.1:8401` 起容器（socket 仅管理面挂载）→
跑 `test_live_docker.py` 黑盒核验 5 项语义→停容器（验证环境不常驻，生产
部署另行决策）。

## 生产常驻部署（用户授权，2026-09-08 生效）

- systemd 单元：`deploy/systemd/repro-runtime.service`（Nexus Runtime 同款
  写法），`127.0.0.1:8401`，`Restart=always`，`After/Wants=docker.service`。
  安装：解码写入 `/etc/systemd/system/repro-runtime.service` →
  `daemon-reload` → `enable` → `start`。
- 代码：从 release 的 `deploy/repro-runtime/` 同步到
  `/opt/smartcarb/repro-runtime/`（排除 `.venv/data/.token/__pycache__`），
  与 release diff 干净。
- 配置 `/opt/smartcarb/shared/env/repro-runtime.env`（root:600）：
  `REPRO_RUNTIME_TOKEN`（沿用 T1-b 验证 token 文件值，不打印）、
  `REPRO_TASK_IMAGE=repro-task:1.4.0`（digest `4f2ba29bade5`，pull 策略
  `missing`＋本地已缓存＝等价 never，不追 latest）、
  `REPRO_SNAPSHOT_PATH=/opt/smartcarb/repro-runtime/data/sandboxes.json`。
  资源限额沿代码默认（`--memory=2g --cpus=2 --pids-limit=512`，T1-b 实证
  生效；非特权、零挂载、bridge 默认）。
- 权限收敛：`data/` 700、`sandboxes.json` 600（曾为 755/644）。
- Nexus 接线：`nexus.env` 追加 `NEXUS_REPRO_CONTROL_URL=http://127.0.0.1:8401`
  与 `NEXUS_REPRO_CONTROL_TOKEN`（同值，备份 `nexus.env.bak-control-*`），
  重启 nexus-runtime。
- 常驻复验（黑盒 23/23）：ensure/幂等/执行/查询/上传下载/鉴权拒绝/跨任务
  隔离/资源断言/取消零残留/生命周期。另有真实 autonomous 点火验证
  （7 个 operation 全 exit 0，含目标命令正确输出），见回执打通节。
