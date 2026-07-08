# M4B 执行报告

更新时间：2026-07-08

## 目标

为 8 月决赛主流程建立稳定、离线、确定性的后端回归测试。本次只修改测试、测试 fake、测试夹具和 `docs/phase1/` 文档；未修改 endpoint、service、model 或生产数据库结构。

## 修改范围

| 文件 | 类型 | 说明 |
|---|---|---|
| `backend/tests/fakes.py` | 测试 fake | 为 LLM、TTS、PPT、数字人、声音复刻、HTTPX 补齐 `business_failure`；PPT fake 兼容 service 传入的 `search` 等额外参数 |
| `backend/tests/test_m4b_fakes.py` | fake 自测 | 验证 success、timeout、service_unavailable、malformed_response、business_failure 五种模式均可稳定触发 |
| `backend/tests/conftest.py` | 测试夹具 | 固定用户名改为唯一用户名，避免全量测试中 `users.username` 唯一约束冲突；仍使用 M4A 临时 SQLite、外部网络阻断和外部服务 fake |
| `backend/tests/test_m4b_main_flows.py` | M4B 主流程测试 | 新增 5 个主流程回归测试，覆盖用户、上传、脚本、映射、发布、选课、播放器、进度、问答、测验、前置知识、TTS、数字人、PPT |
| `docs/phase1/关键业务回归矩阵.md` | 文档 | 新增 M4B 关键业务回归矩阵 |
| `docs/phase1/M4A执行报告.md` | 文档 | 补充 M4B 前置 business_failure fake 能力说明 |
| `docs/phase1/M4B执行报告.md` | 文档 | 本报告 |

## 新增测试覆盖

| 测试文件 | 用例数 | 结果 |
|---|---:|---|
| `backend/tests/test_m4b_fakes.py` | 6 | 通过 |
| `backend/tests/test_m4b_main_flows.py` | 5 | 通过 |

M4B 主流程覆盖：

1. 用户注册、登录、角色识别。
2. 教师上传课件并创建课程。
3. 文档解析 fake 成功路径和失败路径。
4. 教学脚本读取、保存、快照、回滚。
5. 知识点与 PPT 页面映射创建、读取、应用。
6. 课程发布、下架、删除基础行为。
7. 学生选课、重复选课、退课、我的课程当前路由状态。
8. 播放器初始化与播放器进度保存。
9. 学习进度同步、详情、续学。
10. AI 问答与测验 fake LLM 路径。
11. 前置知识缺口分析、跳转、返回。
12. TTS 节点音频合成 fake 路径。
13. 数字人视频生成任务创建、状态查询、服务不可用和 business_failure 分支。
14. PPT 生成 fake 成功和 business_failure 分支。

## 验证命令

工作目录：

```text
E:\smartcarb\ai-course-system
```

| 命令 | 结果 |
|---|---|
| `backend\.venv\Scripts\python.exe -m pytest --collect-only -q` | 通过：`158 tests collected in 0.26s` |
| `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_m4a_isolation.py backend\tests\test_m4a_route_contract.py backend\tests\test_m4b_fakes.py -q` | 通过：`19 passed, 10 warnings in 1.21s` |
| `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_m4a_isolation.py backend\tests\test_m4a_route_contract.py backend\tests\test_m4b_fakes.py backend\tests\test_m4b_main_flows.py -q` | 通过：`24 passed, 126 warnings in 3.29s` |
| `backend\.venv\Scripts\python.exe -m pytest backend\tests -q` | 未全绿：`28 failed, 119 passed, 162 warnings, 11 errors in 5.91s` |

## 失败分类

| 分类 | 数量/范围 | 证据 | 处理结论 |
|---|---:|---|---|
| 新增测试失败 | 0 | `test_m4b_fakes.py` 6 passed；`test_m4b_main_flows.py` 5 passed | M4B 新增测试稳定 |
| 测试基础设施问题 | 11 errors + 2 errors | `backend/tests/test_new_features.py` 缺少 `published_course_id` fixture；`backend/tests/test_f5_mapping_fix.py` 期望 `ScriptNodeType.KNOWLEDGE_POINT`，但当前 `backend/app/models/course_model.py::ScriptNodeType` 不存在该枚举 | 保留记录，不在 M4B 顺手补历史测试或业务枚举 |
| 历史测试失败 | 多个历史用例 | `backend/tests/test_new_features.py` 期望 `/api/v1/document/courses` 顶层 `courses`，当前真实响应为统一结构 `data.courses`；`backend/tests/test_video_generation.py` 期望旧前缀 `/api/v1/video-generation`，当前 M4A 已锁定 `/api/v1/video-gen` | 历史测试与当前 API 契约不一致 |
| 已确认业务缺陷 | 4 类 | 见下节 | 记录到 M4B 报告，留待 M6/M7 或单独修复 |
| 外部环境阻塞 | 0 | 新增测试未访问真实外部服务；未出现网络/密钥/付费服务阻塞 | 无 |

## 已确认业务缺陷

1. `backend/app/api/v1/endpoints/document.py::enroll_course` 首次选课在 DB 已创建 `StudentEnrollment` 和 `LearningProgress` 后，响应构造访问不存在字段 `enrollment.enrollment_at`，导致统一响应 `code=500`。
   - M4B 证据：`test_m4b_teacher_script_mapping_publish_enrollment_and_course_lifecycle`。
   - 当前处理：测试锁定“DB 已写入但响应失败”的现状，不修改业务代码。

2. `/api/v1/document/my-courses` 当前被 `backend/app/api/v1/endpoints/document.py` 中更早注册的 `/{document_id}` 动态路由遮蔽，实际返回 HTTP 404。
   - M4B 证据：`test_m4b_teacher_script_mapping_publish_enrollment_and_course_lifecycle`；全量历史 `test_new_features.py::TestStudentEnrollment::test_get_my_courses_empty` 同样失败。
   - 当前处理：记录为决赛相关风险，不改路由顺序。

3. `backend/app/services/video_generation_service.py::generate_node_video` 对数字人 `business_failure` 响应未识别为失败；当 fake 返回结构化 `status="failed"` 且 `video_path=""` 时，任务仍被标记为 `GenerationStatus.COMPLETED`，`error_message` 为空。
   - M4B 证据：`test_m4b_tts_video_and_ppt_fake_external_paths`。
   - 当前处理：测试暴露并锁定现状，不补业务逻辑。

4. 前置知识历史测试与当前鉴权和模型约束不一致。
   - 证据：`backend/tests/test_prerequisite_jump.py` 单独运行 `19 failed, 1 passed`；多个 API 用例未带 token 返回 401；模型直接入库用例缺少必填 `session_id`；嵌套跳转期望 `jump_depth=2`，当前模型默认仍为 1。
   - 当前处理：M4B 新增测试使用真实鉴权和 fake analyzer 验证当前可用主路径；历史用例留待后续整理。

## 外部服务隔离证明

- `backend/tests/conftest.py::block_external_network` autouse fixture 阻断非 loopback socket。
- `backend/tests/conftest.py::install_external_fakes` 注入 LLM、TTS、声音复刻、PPT、数字人 fake。
- `backend/tests/test_m4b_fakes.py` 证明 LLM、TTS、PPT、数字人、声音复刻、HTTPX 的 success、timeout、service_unavailable、malformed_response、business_failure 均可控触发。
- PPT、TTS、数字人测试中的文件输出均写入 `.pytest_tmp/ai_course_m4a/artifacts/...` 临时目录。
- `AI_COURSE_DATABASE_URL` 指向 `.pytest_tmp/ai_course_m4a/test_smart_class.db`，未访问 `database/smart_class.db`。

## 限制

- 未调用真实 LLM、TTS、PPT、数字人或声音复刻服务。
- 未覆盖 PPT `auto_parse=True` 后的自动解析链路。
- 未覆盖真实文档解析器、真实 Office/PDF 转换和真实视频素材上传链路。
- 未修复任何 endpoint/service/model 业务缺陷。
- 全量历史测试未全绿，失败已按当前证据分类。

## 回滚方法

回滚 M4B 可删除或还原以下文件修改：

1. 删除：
   - `backend/tests/test_m4b_main_flows.py`
   - `backend/tests/test_m4b_fakes.py`
   - `docs/phase1/关键业务回归矩阵.md`
   - `docs/phase1/M4B执行报告.md`
2. 还原：
   - `backend/tests/fakes.py` 中的 `business_failure` fake 能力。
   - `backend/tests/conftest.py` 中唯一用户名 fixture 调整。
   - `docs/phase1/M4A执行报告.md` 中 M4B 前置补充小节。

回滚后应重新执行：

```text
backend\.venv\Scripts\python.exe -m pytest backend\tests\test_m4a_isolation.py backend\tests\test_m4a_route_contract.py -q
```