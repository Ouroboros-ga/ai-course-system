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
| `PUT /sandboxes/{run_id}` | ensure（同 run 幂等，返回 sandbox_id/status） |
| `POST /sandboxes/{run_id}/operations` | `{operation_id, command, timeout_s}` 登记后执行；同 ID 不运行两次 |
| `GET /sandboxes/{run_id}/operations/{operation_id}` | 结果/状态查询（HTTP 超时≠进程停止） |
| `PUT /sandboxes/{run_id}/files/{path:path}` | 受限大小文件上传（工作区限定） |
| `GET /sandboxes/{run_id}/files/{path:path}` | 下载（截断/过大如实报错） |
| `POST /sandboxes/{run_id}/cancel` | 先停操作，再回收实例；重复同一终态 |
| `GET /sandboxes/{run_id}` | 生命周期/活跃 operation/资源摘要（对账用） |
| `GET /health` | 存活探针（无业务信息） |

鉴权：`Authorization: Bearer $REPRO_RUNTIME_TOKEN`（未配置则拒绝启动，
fail-closed）。监听：只绑 `127.0.0.1`。

## 本地开发（无 Docker 可跑单测）

```bash
uv sync --extra test
uv run pytest tests/test_swerex_adapter.py tests/test_service.py -q
```

`test_live_docker.py` 需真实 Docker＋运行中服务（`REPRO_RUNTIME_URL`/`TOKEN`），
默认跳过；只在授权的验证环境执行。

## 服务器验证部署（T1-b 一次性）

见回执 T1-b 节：构建镜像→ `127.0.0.1:8401` 起容器（socket 仅管理面挂载）→
跑 `test_live_docker.py` 黑盒核验 5 项语义→停容器（验证环境不常驻，生产
部署另行决策）。
