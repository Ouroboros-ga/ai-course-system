# M4C 缺陷修复报告

更新时间：2026-07-08

## 目标

在不改变公开 API 路径、数据库生产结构、启动方式和用户可见主流程的前提下，修复 M4B 已确认且影响 8 月决赛主流程的 3 个缺陷：

1. 学生首次选课响应引用不存在的 `enrollment_at`。
2. `GET /api/v1/document/my-courses` 被 `GET /api/v1/document/{document_id}` 遮蔽。
3. 数字人服务返回结构化业务失败时，视频任务仍被标记为 `completed` 且无错误信息。

## 修改范围

| 缺陷 | 修改文件 | 修改内容 |
|---|---|---|
| 首次选课响应 500 | `backend/app/api/v1/endpoints/document.py` | 将响应中的存在性判断从 `enrollment.enrollment_at` 改为 `enrollment.enrolled_at`，不改变响应字段名 `enrolled_at`。 |
| `my-courses` 路由不可达 | `backend/app/api/v1/endpoints/document.py` | 移动既有 `@router.get("/my-courses")` 路由块到 `@router.get("/{document_id}")` 之前，不新增 API 路径，不改变函数逻辑。 |
| 数字人业务失败误标完成 | `backend/app/services/video_generation_service.py` | 对数字人结构化响应增加业务状态和空 `video_path` 检查；业务失败时记录 `GenerationStatus.FAILED` 与 `error_message` 并返回任务；数字人异常时先落库失败再沿用原异常路径。 |
| 回归测试 | `backend/tests/test_m4a_route_contract.py` | 新增路由顺序契约：`/api/v1/document/my-courses` 必须早于 `/api/v1/document/{document_id}` 注册。 |
| 回归测试 | `backend/tests/test_m4b_main_flows.py` | 将 M4B 已确认缺陷断言更新为 M4C 修复后断言；新增数字人超时后任务失败落库验证；保留数字人 business_failure 的失败状态和错误信息验证。 |

## 验证命令与结果

```text
backend\.venv\Scripts\python.exe -m pytest backend\tests\test_m4a_isolation.py backend\tests\test_m4a_route_contract.py -q
```

结果：`14 passed, 10 warnings`

```text
backend\.venv\Scripts\python.exe -m pytest backend\tests\test_m4b_fakes.py -q
```

结果：`6 passed`

```text
backend\.venv\Scripts\python.exe -m pytest backend\tests\test_m4b_main_flows.py -q
```

结果：`5 passed, 121 warnings`

```text
backend\.venv\Scripts\python.exe -m pytest backend\tests\test_m4a_isolation.py backend\tests\test_m4a_route_contract.py backend\tests\test_m4b_fakes.py backend\tests\test_m4b_main_flows.py -q
```

结果：`25 passed, 131 warnings`

```text
backend\.venv\Scripts\python.exe -m pytest backend\tests -q
```

结果：`120 passed, 28 failed, 11 errors, 166 warnings`

全量失败未在本次 M4C 范围内修改，主要集中在历史测试基线：

- `backend/tests/test_new_features.py`：旧测试期望扁平响应结构，且多处引用缺失 fixture `published_course_id`。
- `backend/tests/test_f5_mapping_fix.py`：期望不存在的 `ScriptNodeType.KNOWLEDGE_POINT`。
- `backend/tests/test_prerequisite_jump.py`：多处与当前鉴权、模型约束和接口行为不一致。
- `backend/tests/test_video_generation.py`：旧视频生成测试与当前 `/api/v1/video-gen` 路由和数字人客户端行为不一致。
- `backend/tests/test_split_video_player.py`：旧播放器错误处理断言与当前行为不一致。

## 限制

- 未修改公开 API 路径、请求字段、响应结构、数据库生产结构或启动方式。
- 未拆分 `document.py`、`document_service.py` 或外部服务适配器。
- 未实现计算机垂类、BKT、HMM、LSTM、GraphRAG 或复杂多智能体能力。
- 未调用真实 LLM、TTS、PPT、数字人或声音复刻服务。
- 数字人业务失败当前通过任务 `status=failed` 和 `error_message` 暴露；响应仍沿用现有统一响应外壳，HTTP 状态保持 200，异常路径保持 500/503。

## 回滚方法

仅回滚本次 M4C 修改范围：

```text
git checkout -- backend/app/api/v1/endpoints/document.py backend/app/services/video_generation_service.py backend/tests/test_m4a_route_contract.py backend/tests/test_m4b_main_flows.py docs/phase1/M4C缺陷修复报告.md docs/phase1/关键业务回归矩阵.md
```

注意：仓库中已有 M4A/M4B 相关未提交文件和改动，不应使用 `git reset --hard` 或整仓回滚。