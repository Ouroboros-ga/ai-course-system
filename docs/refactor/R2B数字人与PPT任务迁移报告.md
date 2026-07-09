# R2B 数字人与 PPT 任务迁移报告

更新时间：2026-07-09

## 1. 修改文件

新增 task runtime：

- `backend/app/platform/tasks/__init__.py`
- `backend/app/platform/tasks/status.py`
- `backend/app/platform/tasks/context.py`
- `backend/app/platform/tasks/result.py`
- `backend/app/platform/tasks/runner.py`
- `backend/app/platform/tasks/errors.py`

修改业务 service：

- `backend/app/services/video_generation_service.py`
- `backend/app/services/ppt_generation_service.py`

新增测试：

- `backend/tests/test_r2_task_runtime.py`
- `backend/tests/test_r2b_video_task.py`
- `backend/tests/test_r2b_ppt_task.py`

## 2. 新增 task runtime 文件说明

`backend/app/platform/tasks/status.py` 定义内部统一状态：

- `TaskStatus.PENDING`
- `TaskStatus.RUNNING`
- `TaskStatus.SUCCEEDED`
- `TaskStatus.FAILED`
- `TaskStatus.CANCELLED`
- `TaskStatus.TIMEOUT`
- `TaskStatus.PARTIAL_SUCCESS`

`backend/app/platform/tasks/context.py` 定义：

- `TaskType`
- `TaskContext`

`backend/app/platform/tasks/result.py` 定义：

- `TaskResult.ok`
- `TaskResult.fail`
- `TaskResult.from_adapter_result`

`backend/app/platform/tasks/runner.py` 定义轻量 `TaskRunner`：

- `create_task`
- `mark_running`
- `mark_progress`
- `mark_succeeded`
- `mark_failed`
- `query_status`
- `run`

该 runtime 只做内部结果归一化，不创建数据库表，不持久化状态，不引入 Celery、Redis、RabbitMQ 或复杂 workflow。

## 3. 数字人迁移点

迁移文件：

- `backend/app/services/video_generation_service.py`

迁移函数：

- `VideoGenerationService.generate_node_video`

迁移点：

- 原有 `DigitalHumanAdapter(digital_human_client).generate_video(...)` 调用被包入 `TaskRunner().run(...)`。
- 使用 `TaskContext(task_type=TaskType.DIGITAL_HUMAN_VIDEO, task_id=VideoGenerationTask.id, course_id=..., node_id=..., provider="digital_human")` 记录内部上下文。
- 成功路径仍写 `VideoGenerationTask.dh_video_path`、`dh_generation_time`，最终状态仍为 `GenerationStatus.COMPLETED`。
- 失败路径仍写 `VideoGenerationTask.status = GenerationStatus.FAILED` 和 `error_message`。
- `business_failure` 仍按既有行为返回失败任务，不抛给 endpoint。
- `timeout`、`service_unavailable`、`malformed_response` 仍按既有行为记录失败后抛 `DigitalHumanError`。

未迁移：

- `backend/app/api/v1/endpoints/video_generation.py` 中的路由层健康检查。
- `VideoGenerationService.generate_course_videos` 的批量总任务抽象。
- 分屏合成 `final_video_path`。

## 4. PPT 迁移点

迁移文件：

- `backend/app/services/ppt_generation_service.py`

迁移函数：

- `PPTGenerationService.generate_ppt`

迁移点：

- `PPTAdapter.get_theme_list(...)` 包入 `TaskRunner().run(...)`。
- `PPTAdapter.create_ppt_task(...)` 包入 `TaskRunner().run(...)`。
- `PPTAdapter.wait_for_completion(...)` 包入 `TaskRunner().run(...)`。
- `PPTAdapter.download_ppt(...)` 包入 `TaskRunner().run(...)`。
- 成功路径仍返回 `PPTTaskResult(status="done", ppt_url=..., ppt_file_path=...)`。
- `business_failure` 仍返回 `PPTTaskResult(status="failed", error=...)`。
- 外部轮询返回 `PPTTaskResult(status="timeout")` 时仍保留 `timeout` 语义。
- 创建、模板、下载阶段的异常或 adapter 失败仍转换为原有 `PPTTaskResult(status="failed", error=...)`。

未迁移：

- `/api/v1/ppt/generate` 后台生成后的 `_parse_generated_pptx` 文档解析链路。
- `PPTGenerationService.get_themes`
- `PPTGenerationService.get_task_status`
- 前端 `PPTGenerationDialog` 调用方式。

## 5. API、数据库、前端变化

公开 API 是否变化：否。

数据库生产结构是否变化：否。

前端是否变化：否。

启动方式是否变化：否。

本轮未修改 endpoint、Pydantic 请求模型、SQLModel 数据库模型、migration、部署文件或前端代码。

## 6. 状态映射说明

数字人：

| TaskStatus | 业务落地 |
|---|---|
| `SUCCEEDED` | `VideoGenerationTask.status = GenerationStatus.COMPLETED` |
| `FAILED` | `VideoGenerationTask.status = GenerationStatus.FAILED` |
| `TIMEOUT` | `VideoGenerationTask.status = GenerationStatus.FAILED`，`error_message` 保留 timeout 原因 |

PPT：

| TaskStatus | 业务落地 |
|---|---|
| `SUCCEEDED` | `PPTTaskResult.status = "done"` |
| `FAILED` | `PPTTaskResult.status = "failed"` |
| `TIMEOUT` | 外部 `PPTTaskResult.status = "timeout"` 时原样返回；创建阶段 timeout 仍按既有 `failed` 返回 |

## 7. 错误映射说明

统一错误码来自 R1 `AdapterErrorCode`：

| 错误码 | TaskStatus | 数字人落地 | PPT 落地 |
|---|---|---|---|
| `timeout` | `TIMEOUT` | `failed` + `error_message`，非 business 分支抛 `DigitalHumanError` | 轮询 timeout 保留 `status="timeout"`；创建阶段返回 `failed` |
| `service_unavailable` | `FAILED` | `failed` + `error_message`，抛 `DigitalHumanError` | 返回 `PPTTaskResult(status="failed", error=...)` |
| `malformed_response` | `FAILED` | `failed` + `error_message`，抛 `DigitalHumanError` | 返回 `PPTTaskResult(status="failed", error=...)` |
| `business_failure` | `FAILED` | `failed` + `error_message`，返回失败任务 | 返回 `PPTTaskResult(status="failed", error=...)` |
| `unknown_error` | `FAILED` | 保持原异常记录方式 | 保持原异常记录方式 |

## 8. 测试命令和结果

R2B 新增测试：

```text
backend\.venv\Scripts\python.exe -m pytest backend\tests\test_r2_task_runtime.py backend\tests\test_r2b_video_task.py backend\tests\test_r2b_ppt_task.py -q
```

结果：

```text
15 passed, 84 warnings
```

M4A/M4B/R1 关键回归：

```text
backend\.venv\Scripts\python.exe -m pytest backend\tests\test_m4a_isolation.py backend\tests\test_m4a_route_contract.py backend\tests\test_m4b_fakes.py backend\tests\test_m4b_main_flows.py backend\tests\test_r1_adapters.py backend\tests\test_r1_adapter_migration.py -q
```

结果：

```text
38 passed, 160 warnings
```

全量后端测试：

```text
backend\.venv\Scripts\python.exe -m pytest backend\tests -q
```

结果：

```text
28 failed, 148 passed, 279 warnings, 11 errors
```

前端 build：

```text
cd frontend
npm.cmd run build
```

沙箱内结果：

```text
failed to load config from E:\smartcarb\ai-course-system\frontend\vite.config.js
Error: spawn EPERM
```

提升权限后同一命令结果：

```text
✓ built in 3.40s
```

同时存在 Vite chunk size warning，不影响本次 build 通过。

## 9. 全量后端失败分类变化

R1 记录的全量基线：

```text
132 passed, 28 failed, 11 errors, 195 warnings
```

R2B 后全量结果：

```text
148 passed, 28 failed, 11 errors, 279 warnings
```

变化说明：

- 新增 R2B 测试通过数增加，失败数和错误数未增加。
- warning 增加主要来自新增 R2B 测试触发既有 `datetime.utcnow()` deprecation warning，以及全量测试运行覆盖更多新增用例。

失败分类仍为历史失败：

- `backend/tests/test_f5_mapping_fix.py`：旧测试引用不存在的 `ScriptNodeType.KNOWLEDGE_POINT`。
- `backend/tests/test_new_features.py`：缺少 `published_course_id` fixture；部分旧断言仍按非统一响应结构读取顶层 `courses/total`。
- `backend/tests/test_prerequisite_jump.py`：前置知识跳转历史测试多处失败。
- `backend/tests/test_split_video_player.py`：课程不存在分支断言失败。
- `backend/tests/test_video_generation.py`：旧数字人 client/service/API 测试仍有历史断言问题，包括旧路由名 `/api/v1/video-generation/...`。

按 R2B 范围，未扩大修复这些历史失败。

## 10. 未迁移任务

本轮未迁移：

- 文档上传与解析任务。
- 课程脚本生成任务。
- TTS 单节点和 TTS 批量任务。
- 声音复刻任务。
- 泛雅同步任务。
- 远程视频拉取或上传任务。
- 计算机垂类代码执行能力。

## 11. 已知风险

- `TaskRunner` 当前只做轻量内部封装，不提供持久任务查询、取消、重试队列或跨进程状态恢复。
- 数字人批量生成仍没有统一总任务 ID，只是逐节点沿用 `VideoGenerationTask`。
- PPT 生成仍没有本地任务表，异步生成仍复用 `DoclingDocument.status` 表示后续解析状态。
- `PPTGenerationService.get_themes/get_task_status` 仍直连 `xfyun_client`，与 R1 报告中的暂未迁移范围一致。
- 前端 build 在当前沙箱内会因 esbuild 子进程 `spawn EPERM` 失败，需要提升权限运行同一命令。

## 12. 回滚方式

未提交时回滚：

```text
git checkout -- backend/app/services/video_generation_service.py backend/app/services/ppt_generation_service.py
git rm -r -- backend/app/platform/tasks
git rm -- backend/tests/test_r2_task_runtime.py backend/tests/test_r2b_video_task.py backend/tests/test_r2b_ppt_task.py docs/refactor/R2B数字人与PPT任务迁移报告.md
```

若已提交后回滚：

```text
git revert <R2B提交ID>
```

回滚后建议重新验证：

```text
backend\.venv\Scripts\python.exe -m pytest backend\tests\test_m4a_isolation.py backend\tests\test_m4a_route_contract.py backend\tests\test_m4b_fakes.py backend\tests\test_m4b_main_flows.py backend\tests\test_r1_adapters.py backend\tests\test_r1_adapter_migration.py -q
cd frontend
npm.cmd run build
```

## 13. 人工 review 建议

请优先人工 review：

- `backend/app/platform/tasks/`

重点看该抽象是否仍然足够轻量，是否存在为未来能力提前过度设计的问题。
