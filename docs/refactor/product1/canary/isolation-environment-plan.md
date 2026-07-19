# G5B-0 隔离环境方案（Isolation Environment Plan）

> 状态：**准备（G5B-0）**。方案文档，未实施。
> 约束（CLAUDE.md 仍生效，本文件不解除）：**不安装到生产环境、不接生产主链、不调用真实付费服务**。
> 放行顺序：Docling -> PaddleOCR -> Embedding -> Reranker -> LLM，逐项申请放行。

## 1. 目的

定义 G5B 真实 provider 的隔离运行环境方案，确保：
- 真实 provider 的依赖/模型**不进入生产 venv**。
- 真实 provider **不接入生产主链**（不修改 `main.py` 生产路由、不改 V1 service 流程）。
- 真实 provider 的 canary 调用**可审计**（ProviderCallLog），`real_services_called` 可推导。
- 生产环境与 M7 基线**零影响**。

## 2. 隔离层级

### 2.1 依赖隔离：独立 venv / 容器
- 每个 real provider（或每组）运行在**独立 Python venv 或容器**，与生产 `backend/.venv` 完全分离。
- 生产 venv **不安装** docling/paddleocr/torch 等重依赖。
- 容器化优先（docker/podman），便于资源/端口/磁盘隔离与清理。

### 2.2 模型文件隔离
- 真实模型文件存于**隔离目录**（如 `/opt/p1-canary/models/` 或容器卷），不污染生产磁盘。
- 优先**离线模型文件**（预下载），避免运行时联网下模型。

### 2.3 网络隔离
- 本地模型（Docling/PaddleOCR/Embedding/Reranker）：**离线运行**，无网络。
- 在线 API（LLM）：仅在隔离 canary 中调用，**密钥与生产分离**（独立 env/secret），不写入生产配置。

### 2.4 端口/GPU 隔离
- 隔离环境**避开 M7 占用端口** {7860, 8383}（见 G3B 约束）。
- GPU 调度独立（如 `CUDA_VISIBLE_DEVICES` 限定），不与 M7 抢占。

## 3. 主链隔离

- **不修改生产路由**：真实 provider 不注册到生产 `main.py`；通过 **canary 专用入口**（`canary_runner` + `canary_v2` endpoint）调用。
- **不改 V1 service**：真实 provider 仅在 canary 路径运行，不进入 `document_service.process_document` / `qa_service` 生产流程。
- **不写 V1 表**：真实 provider 产出仅写隔离 shadow store（`p1_shadow_*`），与 G3 shadow 同一隔离原则。
- **flag 隔离**：真实 canary 通过 `canary_runner` 的 flag patch（all-flags-on）触发，**不改生产 settings**。

## 4. 审计：ProviderCallLog

G5A.1 已引入 `ProviderCallRecord`（provider_name, invoked_real, stage, detail）。G5B 执行时：
- canary_runner 调用真实 provider 前/后写 `ProviderCallRecord(invoked_real=True)`。
- `real_services_called = derive_real_services_called(log)`（已实现，G5A.1）。
- 日志持久化到隔离 store，供 P1-10 审计：哪些 provider、何时、哪条金标被真实调用。

## 5. 实施步骤（G5B 执行阶段，非 G5B-0）

1. 选定 provider（按放行顺序）。
2. 准备隔离 venv/容器 + 离线模型。
3. 实现 G2 Protocol 真实实现（新增，不改 fake/契约）。
4. canary_runner 接入该 provider（flag-gated, scope-controlled）。
5. 金标集跑指标（metric-thresholds.md）。
6. P1-10 审计 ProviderCallLog + 三维度判定。
7. 人工"放行" -> 下一 provider。

## 6. 清理与回滚

- 关 flag / 拆除隔离 venv/容器 -> 生产零影响（真实 provider 本就未进生产）。
- 隔离 shadow store 按 G3 回滚策略保留只读审计。

## 7. 约束重申（CLAUDE.md，本文件不解除）

- ❌ 不安装依赖到生产 venv。
- ❌ 不接生产主链（不改生产路由/V1 service）。
- ❌ 不调用真实付费服务（LLM 仅在隔离 canary + 独立密钥，且需单独放行）。
- ❌ 不访问生产 DB / 凭证。
- ❌ 不在测试中调用真实泛雅。

## 8. G5B-0 边界

- ✅ 本方案、隔离层级、主链隔离原则、审计方案、实施步骤。
- ❌ 不创建任何 venv/容器。
- ❌ 不下载模型。
- ❌ 不实现真实 provider。
