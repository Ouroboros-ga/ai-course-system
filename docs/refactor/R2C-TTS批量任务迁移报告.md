# R2C TTS 批量任务迁移报告

更新时间：2026-07-09

## 1. 修改文件

修改：

- `backend/app/api/v1/endpoints/document.py`

新增测试：

- `backend/tests/test_r2c_tts_batch_task.py`

新增文档：

- `docs/refactor/R2C-TTS批量任务迁移报告.md`

本轮复用 R2B 已新增的轻量 task runtime：

- `backend/app/platform/tasks/`

## 2. 迁移目标

R2C 只处理 TTS 内部任务兼容：

- 单节点 TTS 的 `TaskResult` 兼容。
- 批量 TTS 的 `TaskRunner` 包装。
- `success / timeout / service_unavailable / malformed_response / business_failure`。
- `PARTIAL_SUCCESS`。
- 错误节点记录。

本轮不拆 `document.py`，不拆 `document_service.py`，不改前端，不改数据库结构，不引入 Celery、Redis、RabbitMQ，不调用真实 TTS，不实现新 TTS provider，不处理文档解析。

## 3. 单节点 TTS 迁移点

文件：

- `backend/app/api/v1/endpoints/document.py`

路由：

- `POST /api/v1/document/course/{course_id}/node/{node_id}/synthesize-audio`

迁移点：

- 原有 `TTSAdapter(tts_client).synthesize(...)` 调用被包入 `TaskRunner().run(...)`。
- 使用 `TaskContext(task_type=TaskType.TTS_NODE, course_id=..., node_id=..., provider="tts")` 记录内部上下文。
- 成功路径仍返回原有统一响应字段：`node_id`、`audio_url`、`audio_duration`、`latency_ms`。
- 失败路径仍返回原有 `unified_response(code=500, message="音频合成失败: ...", data=None)`。

## 4. 批量 TTS 迁移点

文件：

- `backend/app/api/v1/endpoints/document.py`

涉及函数：

- `_background_synthesize_audio`
- `synthesize_all_node_audio`
- `get_tts_generation_status`

迁移点：

- 上传后后台批量 TTS 中每段 `tts_client.synthesize(...)` 调用被包入 `TaskRunner().run(...)`。
- 手动同步批量接口 `POST /course/{course_id}/synthesize-all-audio` 中每段 TTS 调用被包入 `TaskRunner().run(...)`。
- 错误节点仍记录在原有 `errors` 数组中，字段保持 `node_id`、`title`、`error`。
- 新增内部 `_tts_batch_task_result(...)` 将批量完成情况映射为 `TaskStatus`。

## 5. API、数据库、前端变化

公开 API 是否变化：否。

数据库生产结构是否变化：否。

前端调用方式是否变化：否。

用户可见流程是否变化：否。

本轮未新增、删除或修改公开路由；未修改请求字段；未修改数据库模型或 migration；未修改前端代码。

## 6. 状态映射说明

内部状态映射：

| 内部 TaskStatus | 原有公开状态 |
|---|---|
| `SUCCEEDED` | `completed` |
| `PARTIAL_SUCCESS` | `partial` |
| `FAILED` | `failed` |
| `RUNNING` | `processing` |

后台批量 TTS：

- 全部成功：`tts_generation_status[course_id]["status"] = "completed"`。
- 部分成功且存在错误节点：`status = "partial"`。
- 全部失败：`status = "failed"`。

同步批量 TTS：

- 保持原有响应结构：`success_count`、`error_count`、`results`、`errors`。
- 内部每个节点或片段通过 `TaskRunner` 归一化 TTS adapter 结果。

## 7. 错误映射说明

TTS 错误来自 R1 `TTSAdapter`：

| Adapter 错误 | TaskStatus | 落地行为 |
|---|---|---|
| `timeout` | `TIMEOUT` | 单节点返回 `code=500`；批量记录错误节点 |
| `service_unavailable` | `FAILED` | 单节点返回 `code=500`；批量记录错误节点 |
| `malformed_response` | `FAILED` | 单节点返回 `code=500`；批量记录错误节点 |
| `business_failure` | `FAILED` | 单节点返回 `code=500`；批量记录错误节点 |
| unexpected exception | `FAILED` | 保持原有异常捕获和错误记录 |

错误节点记录仍使用原有结构：

```text
{"node_id": ..., "title": ..., "error": "..."}
```

## 8. 测试命令和结果

R2C 新增测试：

```text
backend\.venv\Scripts\python.exe -m pytest backend\tests\test_r2c_tts_batch_task.py -q
```

结果：

```text
12 passed, 120 warnings
```

R2B + R2C 组合测试：

```text
backend\.venv\Scripts\python.exe -m pytest backend\tests\test_r2_task_runtime.py backend\tests\test_r2b_video_task.py backend\tests\test_r2b_ppt_task.py backend\tests\test_r2c_tts_batch_task.py -q
```

结果：

```text
27 passed, 204 warnings
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
28 failed, 160 passed, 399 warnings, 11 errors
```

## 9. 全量测试失败分类变化

R2B 后全量基线：

```text
28 failed, 148 passed, 279 warnings, 11 errors
```

R2C 后全量结果：

```text
28 failed, 160 passed, 399 warnings, 11 errors
```

变化说明：

- 失败数未增加。
- 错误数未增加。
- 通过数增加 12，对应新增 R2C 测试。
- warning 增加主要来自新增测试触发既有 `datetime.utcnow()` deprecation warning。

仍为历史失败分类：

- `backend/tests/test_f5_mapping_fix.py`：旧测试引用不存在的 `ScriptNodeType.KNOWLEDGE_POINT`。
- `backend/tests/test_new_features.py`：缺少 `published_course_id` fixture；部分旧断言仍按非统一响应结构读取顶层 `courses/total`。
- `backend/tests/test_prerequisite_jump.py`：前置知识跳转历史测试多处失败。
- `backend/tests/test_split_video_player.py`：课程不存在分支断言失败。
- `backend/tests/test_video_generation.py`：旧数字人 client/service/API 测试仍有历史断言问题，包括旧路由名 `/api/v1/video-generation/...`。

本轮未扩大修复这些历史失败。

## 10. 未迁移范围

本轮未处理：

- `/api/v1/document/tts/synthesize` 的通用二进制 TTS 接口。
- `/api/v1/document/tts/health` 健康检查。
- 文档解析。
- 课程脚本生成。
- `document_service.py`。
- 新 TTS provider。
- 前端轮询或 UI。

## 11. 已知风险

- `document.py` 仍然是超大文件，本轮只做函数内兼容封装，没有拆分。
- 后台批量 TTS 状态仍存储在内存字典 `tts_generation_status`，服务重启后仍会丢失。
- 批量 TTS 没有独立数据库任务 ID，仍沿用 `course_id` 作为内存状态 key。
- `PARTIAL_SUCCESS` 内部映射到已有公开状态 `partial`，没有新增公开字段。

## 12. 回滚方式

未提交时回滚：

```text
git checkout -- backend/app/api/v1/endpoints/document.py
git rm -- backend/tests/test_r2c_tts_batch_task.py docs/refactor/R2C-TTS批量任务迁移报告.md
```

已提交后回滚：

```text
git revert <R2C提交ID>
```

回滚后建议验证：

```text
backend\.venv\Scripts\python.exe -m pytest backend\tests\test_m4a_isolation.py backend\tests\test_m4a_route_contract.py backend\tests\test_m4b_fakes.py backend\tests\test_m4b_main_flows.py backend\tests\test_r1_adapters.py backend\tests\test_r1_adapter_migration.py -q
```
