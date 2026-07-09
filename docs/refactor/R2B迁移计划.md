# R2B 迁移计划

更新时间：2026-07-09

R2B 目标：在 R2A 设计通过后，只迁移数字人视频生成任务和 PPT 生成任务到轻量 TaskRunner / TaskStatus / TaskResult / TaskContext 抽象。R2B 不迁移文档解析，不迁移 TTS 批量，不改前端，不改公开 API，不改数据库生产结构。

## 为什么第一批选择数字人和 PPT

选择标准：

- 是否影响 8 月决赛演示。
- 是否依赖真实外部服务，自动化测试风险高。
- 是否已有 R1 adapter，可在不改业务 API 的前提下包一层 TaskRunner。
- 是否已有相对清晰的任务状态。

数字人视频生成满足：

- 入口清晰：`backend/app/api/v1/endpoints/video_generation.py`。
- service 清晰：`backend/app/services/video_generation_service.py::VideoGenerationService.generate_node_video`。
- 有数据库任务表：`backend/app/models/video_generation_model.py::VideoGenerationTask`。
- 有状态枚举：`GenerationStatus`。
- 有查询接口：`GET /api/v1/video-gen/task/{task_id}` 和 `GET /api/v1/video-gen/course/{course_id}/tasks`。
- R1 已接入 `DigitalHumanAdapter` 和 `TTSAdapter`。

PPT 生成满足：

- 入口清晰：`backend/app/api/v1/endpoints/ppt_generation.py`。
- service 清晰：`backend/app/services/ppt_generation_service.py::PPTGenerationService.generate_ppt`。
- 外部任务 ID 清晰：讯飞 `sid`。
- 本地结果结构清晰：`PPTTaskResult`。
- R1 已将模板获取、任务创建、轮询、下载接入 `PPTAdapter`。

## 数字人迁移边界

允许迁移：

- `VideoGenerationService.generate_node_video` 中数字人生成调用。
- 必要时将 `TTSAdapter` 与 `DigitalHumanAdapter` 的结果转换为 `TaskResult`。
- 将 `TaskStatus.SUCCEEDED` 映射回 `GenerationStatus.COMPLETED`。
- 将 `TaskStatus.FAILED/TIMEOUT` 映射回 `GenerationStatus.FAILED`，并写 `error_message`。

不得迁移或修改：

- 不改 `/api/v1/video-gen/*` 路由。
- 不改 `_task_to_dict` 响应结构。
- 不改 `VideoGenerationTask` 表结构和字段语义。
- 不改变 `force`、`retry_count`、`error_message` 的现有可见行为。
- 不迁移 endpoint 层健康检查，除非另有明确测试和授权。
- 不实现分屏合成 `final_video_path`。

状态映射建议：

| TaskStatus | VideoGenerationTask.status |
|---|---|
| `PENDING` | `GenerationStatus.PENDING` |
| `RUNNING` | 当前阶段状态：`TTS_SYNTHESIZING/TTS_COMPLETED/DH_GENERATING` |
| `SUCCEEDED` | `GenerationStatus.COMPLETED` |
| `FAILED` | `GenerationStatus.FAILED` |
| `TIMEOUT` | `GenerationStatus.FAILED`，`error_message` 保留 timeout |
| `PARTIAL_SUCCESS` | course 批量生成可统计部分成功，但单节点不使用 |

必须覆盖：

- success -> `completed` / `SUCCEEDED`
- timeout -> `failed` / `TIMEOUT`
- service_unavailable -> `failed` / `FAILED`
- malformed_response -> `failed` / `FAILED`
- business_failure -> `failed` / `FAILED`

## PPT 迁移边界

允许迁移：

- `PPTGenerationService.generate_ppt` 内模板获取、创建任务、等待完成、下载文件的 adapter 调用外包 TaskRunner。
- `PPTTaskResult.status == "done"` 映射为 `TaskStatus.SUCCEEDED`。
- `PPTTaskResult.status == "timeout"` 映射为 `TaskStatus.TIMEOUT`。
- `business_failure/malformed_response/service_unavailable` 映射为失败并返回原有 `PPTTaskResult(status="failed", error=...)`。

不得迁移或修改：

- 不改 `/api/v1/ppt/generate`、`/generate-sync`、`/task/{sid}` 路由。
- 不改 `GeneratePPTRequest` 字段。
- 不改同步接口成功或失败响应结构。
- 不改前端 `PPTGenerationDialog` 调用方式。
- 不新建 PPT 任务表。
- 不迁移生成后的文档解析 `_parse_generated_pptx`。
- 不调用真实讯飞 PPT 或真实 LLM。

状态映射建议：

| TaskStatus | PPTTaskResult.status 或 endpoint 表达 |
|---|---|
| `PENDING` | `pending` |
| `RUNNING` | `generate` 异步返回 `status="generating"`，内部可用 |
| `SUCCEEDED` | `done` |
| `FAILED` | `failed` |
| `TIMEOUT` | `timeout` 或 endpoint 失败响应中保留 timeout error |
| `PARTIAL_SUCCESS` | R2B 不使用 |

必须覆盖：

- PPT success
- PPT timeout
- PPT service_unavailable
- PPT malformed_response
- PPT business_failure

## 不迁移文档解析的原因

文档解析涉及：

- `backend/app/api/v1/endpoints/document.py::upload_document`
- `backend/app/services/document_service.py::DocumentService.process_document`
- `DocumentParser`、`KnowledgeExtractor`、`ScriptGenerator`、`RAGProcessor`
- `DoclingDocument`、`Course`、`CourseScript`、`ScriptNode`
- Docling、Office/PDF 转换、LLM、文件系统、后台 TTS

phase1 风险清单已标记 `document.py` 和 `document_service.py` 为超大高耦合文件。R2B 若迁移文档解析，会同时触及课程创建、脚本生成、RAG、PPT 图片、TTS 后台任务和学生主流程，超出“第一批小步迁移”的安全边界。

文档解析建议在 R2D 或后续单独做，前置条件是先补更细的契约测试和失败分支测试。

## 不迁移 TTS 批量的原因

TTS 批量任务当前有两种形态：

- 上传成功后 `asyncio.create_task(_background_synthesize_audio(...))`。
- 手动 `POST /api/v1/document/course/{course_id}/synthesize-all-audio`。

当前状态依赖：

- 模块内内存字典 `tts_generation_status`。
- `ScriptNode.audio_url/audio_duration`。
- `GET /api/v1/document/course/{course_id}/tts-status` 的推断逻辑。

它没有独立任务 ID，重启会丢失内存状态，也没有持久错误字段。直接在 R2B 迁移会迫使设计新表或改变状态查询语义，违反“不改数据库结构、不改公开 API、不改前端”的约束。

TTS 批量建议放在 R2C：先补测试，再决定是否只做兼容 TaskRunner，或另设计轻量持久状态。

## R2B 需要新增哪些测试

建议新增：

- `backend/tests/test_r2_task_runtime.py`
- `backend/tests/test_r2b_video_task.py`
- `backend/tests/test_r2b_ppt_task.py`

建议更新但谨慎：

- `backend/tests/test_m4b_main_flows.py`：只在必要时补数字人/PPT business_failure 状态断言。
- `backend/tests/test_r1_adapter_migration.py`：只在 TaskRunner 接入影响 R1 adapter 调用路径时补回归。

测试要求：

- TaskStatus 枚举测试。
- TaskType 枚举测试。
- TaskResult success/failure 测试。
- TaskContext 字段测试。
- TaskRunner success 流程测试。
- TaskRunner unexpected_exception -> failed 测试。
- TaskRunner adapter timeout -> timeout 测试。
- 数字人 success/business_failure/timeout/service_unavailable/malformed_response。
- PPT success/business_failure/timeout/service_unavailable/malformed_response。
- M4A/M4B/R1 关键回归继续通过。
- 不访问真实外部服务。
- 不访问生产数据库。

建议命令：

```text
backend\.venv\Scripts\python.exe -m pytest backend\tests\test_r2_task_runtime.py backend\tests\test_r2b_video_task.py backend\tests\test_r2b_ppt_task.py -q
```

```text
backend\.venv\Scripts\python.exe -m pytest backend\tests\test_m4a_isolation.py backend\tests\test_m4a_route_contract.py backend\tests\test_m4b_fakes.py backend\tests\test_m4b_main_flows.py backend\tests\test_r1_adapters.py backend\tests\test_r1_adapter_migration.py -q
```

```text
cd frontend
npm.cmd run build
```

## R2B 完成条件

- 新增轻量 task runtime 文件。
- 数字人生成 service 通过 TaskRunner 接入 R1 adapter 结果。
- PPT 生成 service 通过 TaskRunner 接入 R1 adapter 结果。
- 不改变任何公开 API 路径、请求字段、响应结构。
- 不改变数据库生产结构。
- 不改变前端调用方式。
- success、timeout、service_unavailable、malformed_response、business_failure 均有 fake 覆盖。
- M4A/M4B/R1 关键回归通过。
- 前端 build 状态记录。
- R2B 迁移报告完成。

## R2B 回滚方式

未提交时回滚：

```text
git checkout -- backend/app/platform/tasks backend/app/services/video_generation_service.py backend/app/services/ppt_generation_service.py backend/tests/test_r2_task_runtime.py backend/tests/test_r2b_video_task.py backend/tests/test_r2b_ppt_task.py docs/refactor/R2B数字人与PPT任务迁移报告.md
```

如果使用 stash 保存试验改动：

```text
git stash list
git stash show -p stash@{0}
git stash pop stash@{0}
```

已提交后回滚：

```text
git revert <R2B提交ID>
```

回滚后必须重新验证：

```text
backend\.venv\Scripts\python.exe -m pytest backend\tests\test_m4a_isolation.py backend\tests\test_m4a_route_contract.py backend\tests\test_m4b_fakes.py backend\tests\test_m4b_main_flows.py backend\tests\test_r1_adapters.py backend\tests\test_r1_adapter_migration.py -q
```

