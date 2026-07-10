# R2C TTS 批量任务迁移报告

更新时间：2026-07-10

## 1. 修改文件

本次补齐修改：

- backend/app/api/v1/endpoints/document.py
- backend/tests/test_r2c_tts_batch_task.py
- docs/refactor/R2C-TTS批量任务迁移报告.md

复用但未修改 backend/app/platform/tasks、TTSAdapter 和 backend/tests/fakes.py。未修改 Duix、PPT、数字人 provider、数据库、前端或部署文件。

## 2. 当前 TTS 路径盘点

当前相关路径：

1. POST /api/v1/document/tts/synthesize：通用二进制 TTS，仍直接调用 tts_client，不属于本轮节点或批量迁移。
2. POST /api/v1/document/course/{course_id}/node/{node_id}/synthesize-audio：单节点 TTS，通过 TTSAdapter 和 TaskRunner。
3. document.py::_background_synthesize_audio：上传后由原 asyncio.create_task 触发，状态写 tts_generation_status。
4. POST /api/v1/document/course/{course_id}/synthesize-all-audio：手动同步批量 TTS。
5. GET /api/v1/document/course/{course_id}/tts-status：原状态查询接口。

## 3. 单节点 TTS 迁移点

单节点继续使用 TaskRunner.run -> TTSAdapter.synthesize -> 生产 tts_client 或测试 FakeTTSClient。本次不重写单节点路径，只补充 success、timeout、malformed_response、business_failure、数据库字段写入和失败字段保护测试。原响应结构和状态码语义不变。

## 4. 后台批量 TTS 迁移点

_background_synthesize_audio 保持原串行方式。每个可生成节点建立独立 TaskContext 和 TaskResult；每个分段继续经过 TTSAdapter 和 TaskRunner。分段失败保留 error_code 和 TaskStatus，TaskRunner 自身异常等意外错误映射为 unknown_error/FAILED。一个节点失败后继续后续节点，最后生成批量聚合结果。

任务级 timeout 映射为内部 TIMEOUT，其他任务级异常映射为 FAILED，对外继续使用原 failed 状态。

## 5. 手动批量 TTS 迁移点

synthesize_all_node_audio 保持同步串行执行。内部新增每节点 TaskContext、TaskResult 和批量聚合。公开响应仍只包含 course_id、success_count、error_count、results、errors，不暴露内部状态或任务 ID。

## 6. TaskRunner 使用位置

TaskRunner 用于单节点、后台批量和手动批量的每个 TTS 文本分段。本轮没有扩展 platform/tasks，聚合能力保留在 document.py 的 TTS 局部。

## 7. TTSAdapter 使用位置

三条节点相关路径均通过 TTSAdapter(tts_client).synthesize。测试通过 monkeypatch 注入 FakeTTSClient，生产默认 provider 不变。现有 fake 已具备 success、timeout、service_unavailable、malformed_response、business_failure，因此本轮未修改 fakes.py。

## 8. 批量状态聚合规则

内部聚合字段：

- total_count
- success_count
- failed_count
- completed_count
- failed_nodes
- errors
- duration_ms
- status

规则：

- total_count 等于 0：SUCCEEDED，保持原 no-op 完成语义。
- 全部成功：SUCCEEDED。
- 部分成功：PARTIAL_SUCCESS。
- 所有节点失败：FAILED。
- 任务级整体超时：TIMEOUT。
- 任务级其他异常：FAILED。

节点 timeout 不强制整个批量为 TIMEOUT；混合结果为 PARTIAL_SUCCESS，所有节点失败为 FAILED，失败节点保留 timeout 错误码。

## 9. PARTIAL_SUCCESS 定义

total_count 大于 0、success_count 大于 0 且 failed_count 大于 0。后台公开状态仍为 partial，手动接口仍通过原成功和失败计数表达。

## 10. timeout 处理规则

单节点 timeout 由 TTSAdapter 分类为 timeout，TaskRunner 映射为 TIMEOUT，endpoint 保持原 code=500。批量节点 timeout 保留节点状态和错误码并继续后续节点。任务级 timeout 内部为 TIMEOUT，公开状态兼容映射为 failed，并保留 error_code=timeout。本轮不新增 deadline、重试或取消能力。

## 11. tts_generation_status 兼容方式

原字段始终保留：

- status
- total
- completed
- errors

后台完成后兼容增加 success_count、failed_count、completed_count、failed_nodes、error_code、duration_ms。公开状态仍为 processing、completed、partial、failed、not_started、no_script，没有用 TaskStatus 值替换原状态。

## 12. ScriptNode 字段兼容方式

成功节点继续写 audio_url 和 audio_duration。URL 格式、后台字节数估算和单节点 ffprobe 优先逻辑保持不变。失败节点不写新的成功 URL 或 duration。

## 13. API 是否变化

否。没有新增、删除或改名公开 API 路径、请求字段和原响应字段。

## 14. 数据库结构是否变化

否。没有修改 model、字段、枚举、migration，也没有新增任务表。

## 15. 前端是否变化

否。没有修改前端代码、请求方式或轮询逻辑。

## 16. 启动方式是否变化

否。没有修改 main.py、启动命令、compose 或部署文件。

## 17. 自动化测试是否真实调用外部服务

否。测试使用临时 SQLite、测试音频目录、FakeTTSClient 和受控 client，由 conftest 阻止外网。不读取生产 API Key，不调用真实 Edge TTS、云 TTS、PPT、LLM 或数字人服务，不写生产音频目录。

## 18. 测试命令和结果

R2C：

    backend\.venv\Scripts\python.exe -m pytest backend\tests\test_r2c_tts_batch_task.py -q
    17 passed, 162 warnings

R2/R1/R1D/R2B/M4B：

    backend\.venv\Scripts\python.exe -m pytest backend\tests\test_r2_task_runtime.py backend\tests\test_r2b_video_task.py backend\tests\test_r2b_ppt_task.py backend\tests\test_r2c_tts_batch_task.py backend\tests\test_r1_adapters.py backend\tests\test_r1_adapter_migration.py backend\tests\test_r1d_duix_avatar_provider.py backend\tests\test_m4b_main_flows.py -q
    58 passed, 396 warnings

M4A：

    backend\.venv\Scripts\python.exe -m pytest backend\tests\test_m4a_isolation.py backend\tests\test_m4a_route_contract.py backend\tests\test_m4b_fakes.py -q
    20 passed, 10 warnings

全量后端：

    backend\.venv\Scripts\python.exe -m pytest backend\tests -q
    173 passed, 28 failed, 11 errors, 442 warnings

前端沙箱运行出现既有 spawn EPERM。提升权限后同一命令成功：

    2153 modules transformed
    built in 2.99s

存在既有大 chunk warning，不影响 build 通过。

## 19. 全量测试失败数量与分类变化

实施前为 168 passed、28 failed、11 errors、400 warnings；本次补齐后为 173 passed、28 failed、11 errors、442 warnings。新增通过 5 个，失败数和错误数未增加。

历史失败分类保持：

- test_f5_mapping_fix.py：不存在的 ScriptNodeType.KNOWLEDGE_POINT。
- test_new_features.py：缺少 published_course_id fixture，旧断言读取统一响应顶层字段。
- test_prerequisite_jump.py：前置知识跳转历史测试债。
- test_split_video_player.py：课程不存在分支旧断言失败。
- test_video_generation.py：旧 client、service、API 断言和旧路由名问题。

warnings 增加主要来自既有 datetime.utcnow 弃用告警。全量运行仍出现一条既有 AsyncMock coroutine 未 await RuntimeWarning，本轮不扩大处理。

## 20. 已知风险

- document.py 仍是超大高耦合文件，本轮只改 TTS 局部。
- tts_generation_status 仍是进程内字典，重启后丢失。
- 批量 TTS 没有独立数据库任务 ID。
- 当前串行模式没有取消、持久重试或跨进程恢复。
- 合成前清理旧音频是既有逻辑；失败时数据库可能仍保留旧 URL，本轮未改变。
- fake 短音频不能代表真实 provider 音质、耗时或路径语义。

## 21. 未迁移内容

未处理通用二进制 TTS、TTS 健康检查、声音复刻、文档解析、脚本生成、PPT、数字人、DuixAvatarProvider、新 TTS provider、持久任务表、队列、重试中心或复杂 workflow。

## 22. 回滚方式

本次补齐尚未提交，可恢复三个修改文件：

    git restore -- backend/app/api/v1/endpoints/document.py backend/tests/test_r2c_tts_batch_task.py docs/refactor/R2C-TTS批量任务迁移报告.md

原 R2C 提交为 29e3df0。整体撤销需单独人工评估后执行 git revert 29e3df0。

开始前的无关文档改动已保存为 stash：wip: unrelated docs before R2C completion。本轮不自动恢复。

## 23. 人工 review 建议

1. 检查 _tts_batch_task_result 的成功、部分成功、全部失败和任务级 timeout 映射。
2. 检查后台节点失败后是否继续，原四个状态字段是否始终保留。
3. 检查手动批量原响应字段和值是否保持，内部状态是否未暴露。
4. 检查测试是否验证数据库字段、错误信息和后续节点继续，而非只断言 TaskRunner 调用。
5. 检查 Git diff 仅包含本报告列出的三个文件，不包含 Duix、PPT、数字人、数据库、前端或临时文件。