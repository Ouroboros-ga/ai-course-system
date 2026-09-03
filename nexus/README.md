# Nexus AI Runtime

> **状态**：P0 已实现（2026-09-03，本地可运行 + 真实 SearXNG 链路验证通过）
> **定位**：CodeNexus 课程外全局入口智能体——复杂问题拆解、论文研究、快速复现。
> **决策依据**：[docs/phase1/2026-09-03_CodeNexus转型实施决策.md](../docs/phase1/2026-09-03_CodeNexus转型实施决策.md)

## 架构边界（硬约束）

- **独立 Python 环境**：本目录是独立 uv 项目（独立 pyproject + uv.lock + venv），
  与 `backend/`（langgraph 0.6）**不共享依赖树**；deepagents/langgraph 1.x 只进本环境。
  禁止为兼容 Nexus 而调整旧 Backend 的依赖版本（AGENTS.md §4.1.9）。
- **与旧 Backend 通信只经 HTTP/SSE**：未来由 Backend 反代 `/api/v1/nexus/*` 或前端直连。
- **复现安全**：未知 GitHub Repo 只能经 Repro Worker 受限执行，不进本进程执行
  （AGENTS.md §4.1.10）；Worker 未配置时 fail-closed。
- **数据边界**：工具结果一律 `is_supplementary`，不写掌握度/课程事实/图谱
  （AGENTS.md §4.1.5）。P0 会话状态存内存（InMemorySaver），重启即清。

## P0 能力清单

| 能力 | 实现 | 失败语义 |
|---|---|---|
| 主智能体 | deepagents 0.7.12（LangGraph 编译，内置 todo 拆解/规划中间件） | LLM Key 缺失 → 503 `LLM_NOT_CONFIGURED` |
| Web Search | `web_search` 工具：SearXNG 主通道（47.99.97.154 自部署）+ 本机 DuckDuckGo 降级 | 双通道失败 → `WEB_SEARCH_UNAVAILABLE`，不编造 |
| 论文检索 | `search_arxiv_papers` 工具：arXiv Atom API，3s 限速 + 1 天缓存 | 上游失败 → `ARXIV_UNAVAILABLE` |
| 复现规划 | `plan_reproduction` 工具：nanoGPT 预设（MIT 已核验，官方 CPU 命令） | 无预设 → 返回调研指引，不编造命令 |
| 复现执行 | `run_reproduction` 工具：提交 Repro Worker | 未配置 → `REPRO_WORKER_UNAVAILABLE`，绝不假造执行 |
| LLM | DeepSeek（`deepseek-chat`，OpenAI 兼容端点） | — |
| 会话 | thread_id = session_id，内存 checkpointer 支持续聊 | — |

## 快速开始

```bash
cd nexus
cp .env.example .env     # 填 DEEPSEEK_API_KEY
uv sync
uv run uvicorn nexus.main:app --host 127.0.0.1 --port 8300
```

本地开发连服务器 SearXNG 主通道（SSH 隧道）：

```bash
ssh -N -L 18888:127.0.0.1:8888 root@47.99.97.154
# .env: NEXUS_SEARXNG_URL=http://127.0.0.1:18888
```

## API

### `GET /health`

```json
{"status":"ok","version":"0.1.0","llm_configured":true,"searxng_configured":true,
 "ddgs_enabled":true,"repro_worker_configured":false}
```

### `POST /api/v1/nexus/chat`（非流式）

```bash
curl -X POST http://127.0.0.1:8300/api/v1/nexus/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"调研一下 nanoGPT 论文并给出复现计划","session_id":"demo-1"}'
```

返回 `{session_id, message, tool_events[]}`。

### `POST /api/v1/nexus/chat/stream`（SSE）

SSE 事件序列：`token`（增量文本）→ `tool_call`/`tool_result`（工具执行过程）→
`done`。`tool_result.content` 截断至 600 字符。

认证：`NEXUS_API_KEY` 配置后要求 `Authorization: Bearer <key>`；未配置则开放
（本地开发/演示）。

## Repro Worker 对接契约（待实现）

`run_reproduction` 提交作业：

```
POST {NEXUS_REPRO_WORKER_URL}/jobs
{"preset_id": "nanogpt", "repo_url": "...", "repo_license": "MIT", "steps": [...]}
→ 200 {"job_id": "...", "status": "queued"}
```

Worker 侧职责（实现时遵守）：
- 在 47.99.97.154 以独立容器运行：与 Backend/Judge0 **同宿主机、容器级隔离**
  （独立容器与独立网络，非物理隔离——该机为 4C8G 单机，主栈与 Judge0 栈均运行其上）；
- 未知仓库先做 License 校验，越线仓库拒绝执行；
- 资源限制（CPU/内存/时长/磁盘配额）与网络限制；
- 只回传结构化结果（状态、日志尾部、artifact 元数据），不回传任意文件。

## 测试

```bash
uv run pytest tests -q   # 18 passed（全 mock，不调真实 LLM/付费服务）
```

## 已验证 / 未验证

- ✅ 单测 19 passed（工具降级链、fail-closed、API 契约、鉴权、非流式/流式端点真实图回归）；
- ✅ `build_agent()` 真实构建 deepagents CompiledStateGraph；
- ✅ `web_search` 经 SSH 隧道真实调用服务器 SearXNG（返回 arXiv:1706.03762 等 5 条）；
- ✅ 无 LLM Key 时 chat 返回 503 fail-closed；
- ✅ **已部署服务器**（2026-09-03：`/opt/smartcarb/nexus-runtime` + systemd
  `nexus-runtime.service`，127.0.0.1:8300，由 Backend 反代 `/api/v1/nexus/*`）；
- ✅ **真实 DeepSeek 端到端冒烟 6/6 通过**（S1-V1，含 SearXNG 主通道检索、
  nanoGPT 复现规划、复现执行 fail-closed、会话续聊；记录见
  `docs/phase1/验收记录/S1_Nexus真实链路_2026-09-03.md`）；
- ⚠️ arXiv 直连 API 在境内服务器不可达（网络现实，工具 fail-closed 正确）；
  Agent 经 SearXNG 通道完成论文检索；建议后续为 `paper_search` 增加
  SearXNG `site:arxiv.org` 降级通道；
- ❌ Repro Worker 未实现（接口已预留，`run_reproduction` 当前必返
  `REPRO_WORKER_UNAVAILABLE`）。
