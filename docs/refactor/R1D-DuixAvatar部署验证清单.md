# R1D-DuixAvatar 部署验证清单

> **已废弃（2026-08-06，仅历史追溯）**：本文只保留旧引擎部署记录，不是当前课程媒体
> 或数字人验收清单。现行验收以阶段八的音频时钟、PPT manifest、playlist 和 PixiJS
> 降级策略为准。

> 本清单用于决赛演示机器或部署机器实测。当前 R1D 自动化测试不调用真实 Duix.Avatar 服务，不伪造实测结果。

## 1. 基础环境

| 项目 | 验证方法 | 期望结果 | 实测结果 |
| --- | --- | --- | --- |
| NVIDIA GPU | 检查设备管理器或 `lspci`/云主机配置 | 存在 NVIDIA GPU | 待实测 |
| nvidia-smi | `nvidia-smi` | 能显示 GPU、驱动版本、显存 | 待实测 |
| Docker | `docker --version` | Docker 可用 | 待实测 |
| docker-compose | `docker-compose --version` 或 `docker compose version` | Compose 可用 | 待实测 |
| NVIDIA Container Toolkit | `nvidia-ctk --version` 或容器内执行 `nvidia-smi` | 容器可访问 GPU | 待实测 |
| 100GB+ 磁盘 | Windows 检查 Docker 镜像盘；Linux 执行 `df -h` | Docker 镜像和数据盘剩余空间满足 100GB+ | 待实测 |

## 2. Duix 服务启动

| 项目 | 验证方法 | 期望结果 | 实测结果 |
| --- | --- | --- | --- |
| docker-compose 服务启动 | 在 Duix `deploy` 目录执行 `docker-compose up -d` 或对应 Linux compose 文件 | 服务进入 running 状态 | 待实测 |
| 8383 可访问 | `curl http://127.0.0.1:8383` | 端口可达，非连接拒绝 | 待实测 |
| /easy/submit 可提交 | 向 `/easy/submit` POST `audio_url`、`video_url`、`code`、`chaofen=0`、`watermark_switch=0`、`pn=1` | 返回结构化响应，记录 task code | 待实测 |
| /easy/query 可查询 | `GET /easy/query?code={taskCode}` | 返回结构化任务状态 | 待实测 |

## 3. 路径语义实测

| 项目 | 验证方法 | 期望结果 | 实测结果 |
| --- | --- | --- | --- |
| audio_url 路径语义 | 使用真实生成的 TTS wav 路径提交 | Duix 服务能读取音频 | 待实测 |
| video_url 路径语义 | 使用教师人脸视频路径提交 | Duix 服务能读取视频 | 待实测 |
| 输出视频路径 | 查询完成后记录 Duix 返回的视频路径字段 | 返回可访问或可落库的视频路径 | 待实测 |
| 失败响应结构 | 故意提交不存在的音频或视频路径 | 返回 HTTP 200 但业务失败状态，包含错误信息 | 待实测 |
| 生成耗时记录 | 记录 submit 到 query 完成的时间和返回的耗时字段 | 可估算单节点生成耗时 | 待实测 |

## 4. 平台集成实测

| 项目 | 验证方法 | 期望结果 | 实测结果 |
| --- | --- | --- | --- |
| provider 配置 | 设置 `DIGITAL_HUMAN_PROVIDER=duix` | 后端选择 `DuixAvatarProvider` | 待实测 |
| base URL 配置 | 设置 `DUIX_BASE_URL=http://127.0.0.1:8383` | submit/query 发往 Duix 8383 | 待实测 |
| 视频生成 API | 调用现有 `/api/v1/video-generation/node/{node_id}/generate` | API 路径和响应结构不变 | 待实测 |
| 任务落库 | 查询 `VideoGenerationTask` | 成功时 `status=completed` 且 `dh_video_path` 有值；失败时 `status=failed` 且 `error_message` 有值 | 待实测 |

## 5. 决赛 fallback 方案

| 场景 | fallback |
| --- | --- |
| Duix 服务无法启动 | 将 `DIGITAL_HUMAN_PROVIDER` 恢复为默认值，使用原有 digital human provider；保留 R1D 代码但不启用 |
| GPU/驱动异常 | 使用预生成演示视频；现场仅演示平台流程和任务状态查询 |
| 8383 可达但生成失败 | 展示失败任务的 `error_message` 和业务失败处理；切换预生成视频素材演示学习流程 |
| 路径语义不兼容 | 在部署机建立 Duix 容器可访问的共享目录，调整 `audio_url`/`video_url` 为容器可读路径；若时间不足，使用 fallback 视频 |
| 生成耗时过长 | 演示前预热并预生成关键节点视频；现场只生成短音频短视频样例 |

## 6. 不允许项

- 不在主项目启动流程中自动拉起 Duix docker-compose。
- 不在自动化测试中调用真实 `http://127.0.0.1:8383`。
- 不伪造路径语义、输出路径、失败结构或耗时结果。
- 不因 Duix 接入改变现有公开 API、数据库结构或前端调用方式。
