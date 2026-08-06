# R1D-DuixAvatar 接入报告

> **已废弃（2026-08-06，仅历史追溯）**：DuixAvatar/服务端视频合成不属于当前阶段八
> 学习端主链。请以 `docs/phase1/阶段8_媒体TTS数字人PPT_实施规划.md` 的 PixiJS 2D
> 播放方案和发布门为准。

## 1. 范围

本次 R1D 只接入 Duix.Avatar 数字人视频生成 provider，不改变公开 API、数据库结构、前端调用方式、主项目启动流程，也不删除原有 Gradio 数字人 provider。

新增和修改范围：

- `backend/app/platform/adapters/duix_avatar.py`
- `backend/app/platform/adapters/registry.py`
- `backend/app/services/video_generation_service.py`
- `backend/app/api/v1/endpoints/video_generation.py`
- `backend/tests/test_r1d_duix_avatar_provider.py`

未修改范围：

- 未修改数据库模型和迁移。
- 未修改前端。
- 未拆分 `document.py`。
- 未拆分 `document_service.py`。
- 未新增 Duix 部署脚本到主项目启动流程。

## 2. 接入依据

Duix.Avatar 官方仓库 README 的 Open APIs 章节说明：

- Docker 启动后本地端口通过 `http://127.0.0.1` 访问。
- 视频合成提交接口为 `POST http://127.0.0.1:8383/easy/submit`。
- 提交参数包含 `audio_url`、`video_url`、`code`、`chaofen`、`watermark_switch`、`pn`。
- 进度查询接口为 `GET http://127.0.0.1:8383/easy/query?code=${taskCode}`。

来源：<https://github.com/duixcom/Duix-Avatar>

## 3. 实现说明

`DuixAvatarProvider` 对齐现有 `DigitalHumanAdapter` 的 client 协议：

- `check_health()`：访问 `DUIX_BASE_URL`，返回布尔可用状态。
- `generate_video(audio_path, video_path, **kwargs)`：提交 `/easy/submit`，再轮询 `/easy/query?code=...`。
- 成功时返回 `DigitalHumanResponse(video_path=..., generation_time=..., download_path=...)`。
- 结构化业务失败时返回 `DigitalHumanResponse`，并设置 `status="failed"`、`error=...`、`video_path=""`，由 `DigitalHumanAdapter` 分类为 `business_failure`。
- malformed JSON 或非 dict 响应返回 `{"malformed": True}`，由 `DigitalHumanAdapter` 分类为 `malformed_response`。
- timeout 和服务不可用不在 provider 内吞掉，交给 `run_adapter_call()` 按现有规则分类。

Provider 选择逻辑在 `get_digital_human_adapter()` 中：

- 默认仍使用原有 `digital_human_client`。
- 当 `DIGITAL_HUMAN_PROVIDER=duix` 或 `duix_avatar` 时，创建 `DuixAvatarProvider`。
- `DUIX_BASE_URL` 默认值为 `http://127.0.0.1:8383`。
- 测试注入 fake client 时仍保留原有注入路径，避免破坏 R1/R2B 测试隔离。

## 4. 行为兼容性

保持不变：

- `/api/v1/video-generation/...` 路由路径不变。
- 请求字段不变。
- 响应结构不变。
- `VideoGenerationTask` 表结构不变。
- 前端调用方式不变。
- 默认 provider 未配置时仍走原有数字人客户端。

内部调整：

- 视频生成服务的数字人调用由直接 `DigitalHumanAdapter(digital_human_client)` 改为 `get_digital_human_adapter(digital_human_client)`。
- video-generation 路由的健康检查也改为通过 `get_digital_human_adapter(digital_human_client).check_health()`，避免 `DIGITAL_HUMAN_PROVIDER=duix` 时仍被旧 Gradio health check 阻断。

## 5. 测试覆盖

新增 `backend/tests/test_r1d_duix_avatar_provider.py`，覆盖：

- success：验证 `/easy/submit` payload 和 `/easy/query` URL。
- timeout：fake client 抛 `TimeoutError`，验证分类为 `timeout`。
- service_unavailable：fake client 抛服务不可用异常，验证分类为 `service_unavailable`。
- malformed_response：fake response JSON 解析失败，验证分类为 `malformed_response`。
- business_failure：fake Duix 返回 200 和结构化失败状态，验证分类为 `business_failure`，且 `status=failed`、`video_path=""`、错误信息保留。
- registry：验证 `DIGITAL_HUMAN_PROVIDER=duix` 时选中 `DuixAvatarProvider`；未配置时保留注入的默认 fake client。

自动化测试不请求真实 `http://127.0.0.1:8383`，全部通过 fake/httpx mock 完成。

## 6. 风险

- Duix.Avatar README 未给出完整成功/失败响应样例；当前解析兼容常见字段：`video_url`、`videoUrl`、`video_path`、`videoPath`、`output_url`、`output_path`、`path`、`url`。
- `audio_url` 和 `video_url` 的真实路径语义必须在部署机实测确认，当前代码按 Duix 文档将现有 `audio_path`、`video_path` 字符串原样提交。
- `/health` 对 Duix provider 只验证 base URL 端口可达；真实生成能力仍以 `/easy/submit` 和 `/easy/query` 实测为准。

## 7. 回滚方法

如需回滚 R1D：

1. 删除 `backend/app/platform/adapters/duix_avatar.py`。
2. 删除 `backend/tests/test_r1d_duix_avatar_provider.py`。
3. 将 `backend/app/platform/adapters/registry.py` 的 `get_digital_human_adapter()` 恢复为仅返回 `DigitalHumanAdapter(client)`。
4. 将 `backend/app/services/video_generation_service.py` 恢复为直接使用 `DigitalHumanAdapter(digital_human_client)`。
5. 将 `backend/app/api/v1/endpoints/video_generation.py` 的健康检查恢复为 `digital_human_client.check_health()`。
6. 删除本报告和部署验证清单。

## 8. 验证命令

```powershell
backend\.venv\Scripts\python.exe -m pytest backend\tests\test_r1d_duix_avatar_provider.py backend\tests\test_r1_adapters.py backend\tests\test_r1_adapter_migration.py backend\tests\test_r2b_video_task.py backend\tests\test_m4b_main_flows.py -q
```

```powershell
cd frontend
npm.cmd run build
```


## 9. Execution Results

- `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_r1d_duix_avatar_provider.py -q`: 8 passed.
- `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_r1d_duix_avatar_provider.py backend\tests\test_r1_adapters.py backend\tests\test_r1_adapter_migration.py backend\tests\test_r2b_video_task.py backend\tests\test_m4b_main_flows.py -q`: 31 passed, 233 warnings. The warnings are existing `datetime.utcnow()` deprecation warnings.
- `cd frontend; npm.cmd run build`: first sandbox run failed with esbuild `spawn EPERM`; rerunning the same command with elevated execution passed. Vite reported the existing chunk-size warning.

## 10. Limits

- Real Duix.Avatar docker-compose was not started in this verification.
- Real `http://127.0.0.1:8383` was not called by automated tests.
- `audio_url`/`video_url` path semantics, output video path, failure response structure, and real generation time still need deployment-machine verification through the R1D DuixAvatar deployment checklist.
