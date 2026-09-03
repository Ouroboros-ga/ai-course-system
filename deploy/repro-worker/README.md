# CodeNexus Repro Worker（P1-W）

不可信论文仓库的**受限执行器**。独立容器、独立 Docker 网络、非 root 运行；
Nexus Runtime 经 `POST /jobs` 提交已核验预设，Worker 完成 License 双重校验、
受限执行并只回传结构化结果（AGENTS.md §4.1.10、技术决策补丁 §14/§23/§29）。

## 契约

| 端点 | 说明 |
|---|---|
| `GET /health` | 状态与配置（超时/配额/License 白名单/活跃任务数） |
| `POST /jobs` | 提交 `{preset_id, repo_url, repo_license, steps[]}` → `{"job_id", "status": "queued"}`；URL 非 GitHub → 422；License 越线 → `{"status":"rejected","code":"LICENSE_VIOLATION"}` |
| `GET /jobs/{id}` | 任务记录：状态、License 三源校验结果、每步 `exit_code`/`log_tail`（4KB 截尾）、artifact 清单（文件名+大小，≤1MB×20）；**不回传任意文件** |

行为要点：

- **License 三源判定**：请求声明 + GitHub API spdx + clone 后本地 `LICENSE*` 解析，
  全部可验证且在白名单内才执行；GitHub 与本地均无法识别 → 视为无 License 拒绝
  （fail-closed）。白名单默认 `MIT, Apache-2.0, BSD-*, ISC, 0BSD, Unlicense, CC0-1.0`。
- **执行**：`bash -lc` 逐步运行，单步超时（默认 300s）SIGKILL，任务总预算
  （默认 15min）硬截止，磁盘配额 2GB，串行执行；跨步 `cd` 语义自动维护。
- **工作目录 ephemeral**：任务结束（含失败）即删除。
- **认证**：`REPRO_WORKER_TOKEN` 配置后所有 /jobs 请求需 `Authorization: Bearer`。

## 本地测试

```bash
# 复用 nexus 独立 venv（含 pytest-asyncio/respx）：
nexus/.venv/Scripts/python -m pytest deploy/repro-worker/test_worker.py -q \
  --basetemp=deploy/repro-worker/.pytest_tmp/w   # Windows 下系统临时目录可能拒绝访问
```

## 服务器部署清单（P1-W4，需用户明确授权）

1. **构建镜像**（境内走清华 PyPI 镜像）：
   `docker build -t repro-worker:latest deploy/repro-worker/`
2. **写入 env**（`/opt/smartcarb/shared/env/repro-worker.env`，600）：
   `REPRO_WORKER_TOKEN=<随机>`、可选 `REPRO_WORKER_GITHUB_TOKEN=<gh_pat>`（缓解 API 限流）
3. **启动**：`REPRO_WORKER_TOKEN=<值> docker compose -f deploy/repro-worker/docker-compose.yml up -d`
   ——compose 已内置：独立网络 `repro_net`、1C/2G/512 pids 限额、仅绑 127.0.0.1:8400
4. **出站白名单**（iptables，仅放行 git/pip 所需）：
   ```bash
   iptables -I DOCKER-USER -i br-$(docker network inspect repro_net --format '{{.Id}}' | cut -c1-12) \
     -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
   # 放行 DNS、GitHub、PyPI/镜像站，其余出站 REJECT —— 具体规则部署时按现场网络落地
   ```
5. **配置 Nexus 对接**（W5 已实现）：`nexus.env` 追加
   `NEXUS_REPRO_WORKER_URL=http://127.0.0.1:8400` 与 `NEXUS_REPRO_WORKER_TOKEN=<同上>`
   并 `systemctl restart nexus-runtime`
6. **验收**：`curl 127.0.0.1:8400/health` 200；演示脚本用例 5（nanoGPT 复现执行）
   返回 `queued` 而非 `REPRO_WORKER_UNAVAILABLE`；提交 GPL 仓库返回 `LICENSE_VIOLATION`

## 资源占用

1C2G 容器限额 + 2GB 磁盘配额；与主栈/Judge0/Nexus 同宿主机（4C8G 单机），
按落地计划 §三 的资源配额设计预留。
