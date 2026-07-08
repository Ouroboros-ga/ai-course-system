# 前后端 API 契约检查表

更新时间：2026-07-08

检查依据：

- 前端：`frontend/src/api/*.js`、`frontend/src/composables/*.js`、`frontend/src/views/*.vue`、`frontend/src/components/**/*.vue`
- 请求基准：`frontend/src/utils/request.js`，开发环境 baseURL 为 `/api/v1`
- 后端：通过 `app.main.app.routes` 导出的真实 FastAPI 路由清单
- 回归覆盖：`backend/tests/test_m4a_route_contract.py`、`backend/tests/test_m4b_main_flows.py`、`backend/tests/test_m4b_fakes.py`

## 总览

| 前端调用来源 | API | 后端路由状态 | M4B/M4C 覆盖 | 结论 |
|---|---|---|---|---|
| `frontend/src/api/user.js` | `POST /user/login` | 存在 | M4B 覆盖 | 一致 |
| `frontend/src/api/user.js` | `POST /user/register` | 存在 | M4B 覆盖 | 一致 |
| `frontend/src/api/user.js` | `GET /user/me` | 存在 | M4B 覆盖 | 一致 |
| `frontend/src/api/user.js` | `POST /user/modify` | 存在 | 未覆盖 | 路由存在，需后续补测试 |
| `frontend/src/api/user.js` | `GET /user/list` | 存在 | 未覆盖 | 管理员页使用，需后续补测试 |
| `frontend/src/api/user.js` | `PUT /user/role` | 存在 | 未覆盖 | 管理员页使用，需后续补测试 |
| `frontend/src/api/user.js` | `GET /user/stats` | 存在 | 未覆盖 | 教师历史页使用，需后续补测试 |
| `frontend/src/api/user.js` | `POST /user/logout` | 不存在 | 未覆盖 | 不一致 |
| `frontend/src/api/chat.js` | `GET /chat/history` | 存在 | 未覆盖 | 路由存在 |
| `frontend/src/api/chat.js` | `POST /chat/create` | 存在 | 间接覆盖上传创建聊天 | 路由存在 |
| `frontend/src/api/chat.js` | `DELETE /chat/${chatId}` | 不存在 | M4A 已记录类似风险 | 不一致 |
| `frontend/src/api/chat.js` | `POST /chat/file/upload` | 存在，来自 document router 二次挂载 | M4B 上传主流程覆盖 `/document/upload`，未单独覆盖 `/chat/file/upload` | 路由存在但高耦合 |
| `frontend/src/api/chat.js` | `POST /chat/ask` | 存在 | M4B 覆盖 | 一致 |
| `frontend/src/api/chat.js` | `GET /chat/messages/{chatId}` | 存在 | 未覆盖 | 路由存在 |
| `frontend/src/api/mapping.js` | `GET /mapping/{courseId}` | 存在 | M4B 覆盖 | 一致 |
| `frontend/src/api/mapping.js` | `GET /mapping/{courseId}/pages` | 存在 | 未覆盖 | 路由存在 |
| `frontend/src/api/mapping.js` | `POST /mapping/{courseId}/auto` | 存在 | M4B 覆盖 | 一致 |
| `frontend/src/api/mapping.js` | `POST /mapping/{courseId}/ai-match` | 存在 | 未覆盖；需 LLM fake | 外部 LLM 风险 |
| `frontend/src/api/mapping.js` | `PUT /mapping/{courseId}/nodes/{nodeId}` | 存在 | M4B 覆盖 | 一致 |
| `frontend/src/api/mapping.js` | `PUT /mapping/{courseId}/batch` | 存在 | 未覆盖 | 路由存在 |
| `frontend/src/api/mapping.js` | `POST /mapping/{courseId}/apply` | 存在 | M4B 覆盖 | 一致 |
| `frontend/src/api/platform.js` | `GET /platform/sso/callback` | 存在 | 未覆盖；需 httpx fake | 外部泛雅风险 |
| `frontend/src/api/platform.js` | `POST /platform/syncUser` | 存在 | 未覆盖 | 路由存在 |
| `frontend/src/api/platform.js` | `POST /platform/syncCourse` | 存在 | 未覆盖 | 路由存在 |
| `frontend/src/api/platform.js` | `POST /platform/syncEnrollment` | 存在 | 未覆盖 | 路由存在 |
| `frontend/src/api/platform.js` | `GET /platform/bind/status/{courseId}` | 存在 | 未覆盖 | 路由存在 |
| `frontend/src/api/platform.js` | `DELETE /platform/unbind/{courseId}` | 存在 | 未覆盖 | 路由存在 |
| `frontend/src/api/platform.js` | `GET /platform/status` | 存在 | 未覆盖 | 路由存在 |
| `frontend/src/api/player.js` | `GET /player/init/{courseId}` | 存在 | M4B 后端覆盖 | 响应外壳不一致，前端高风险 |
| `frontend/src/api/player.js` | `GET /player/knowledge-points/{courseId}` | 存在 | 未覆盖 | 路由存在 |
| `frontend/src/api/player.js` | `POST /player/progress/save` | 存在 | M4B 覆盖 | 一致 |
| `frontend/src/api/player.js` | `GET /player/progress/{courseId}` | 存在 | 未覆盖 | 路由存在 |
| `frontend/src/api/ppt_generation.js` | `GET /ppt/themes` | 存在 | 未覆盖；需 PPT fake | 组件读取响应有风险 |
| `frontend/src/api/ppt_generation.js` | `POST /ppt/generate` | 存在 | 未覆盖；需 PPT fake | 外部服务风险 |
| `frontend/src/api/ppt_generation.js` | `POST /ppt/generate-sync` | 存在 | M4B 覆盖 success/business_failure | 路由存在，组件读取响应有风险 |
| `frontend/src/api/ppt_generation.js` | `GET /ppt/task/{sid}` | 存在 | 未覆盖 | 路由存在 |
| `frontend/src/api/progress.js` | `POST /progress/analyze` | 存在 | 未覆盖；需 LLM fake | 路由存在 |
| `frontend/src/api/progress.js` | `GET /progress/visualization/{courseId}` | 存在 | 未覆盖 | 路由存在 |
| `frontend/src/api/progress.js` | `POST /progress/sync` | 存在 | M4B 覆盖 | 一致 |
| `frontend/src/api/progress.js` | `GET /progress/resume/{courseId}` | 存在 | M4B 覆盖 | 一致 |
| `frontend/src/api/progress.js` | `POST /progress/node/complete` | 存在 | 未覆盖 | 路由存在 |
| `frontend/src/api/script_editor.js` | `POST /document/course/{courseId}/script/snapshot` | 存在 | M4B 覆盖 | 一致 |
| `frontend/src/api/script_editor.js` | `GET /document/course/{courseId}/script/versions` | 存在 | M4B 覆盖 | 一致 |
| `frontend/src/api/script_editor.js` | `POST /document/course/{courseId}/script/rollback/{scriptId}` | 存在 | M4B 覆盖 | 一致 |
| `frontend/src/api/script_editor.js` | `POST /document/course/{courseId}/save` | 存在，重复路由已由 M4A 锁定 | M4B 覆盖 | 一致但有重复路由风险 |
| `frontend/src/api/asset.js` | `/asset/*` | 上传、列表、预览、默认、删除、声音复刻、状态均存在 | fake 自测覆盖声音复刻 fake，未覆盖 asset endpoint 主流程 | 路由存在，声音复刻需 fake |
| `frontend/src/api/video.js` | `/video/list`、`/video/info/{filename}`、`/video/upload`、`/video/remote`、`/api/v1/video/stream/{filename}` | 均存在 | 未覆盖 video.js 主流程 | 路由存在，远程视频需 httpx fake |

## composables 直接调用

| 文件 | API | 后端路由 | 覆盖 | 结论 |
|---|---|---|---|---|
| `frontend/src/composables/useStudentLearning.js` | `GET /document/courses` | 存在 | M4B 间接覆盖课程列表 | 一致 |
| `frontend/src/composables/useStudentLearning.js` | `POST /document/course/{id}/enroll` | 存在 | M4C 覆盖 | 一致 |
| `frontend/src/composables/useStudentLearning.js` | `GET /document/course/{id}` | 存在 | M4B 覆盖 | 一致 |
| `frontend/src/composables/useStudentLearning.js` | `GET /progress/detail/{courseId}` | 存在 | M4B 覆盖 | 一致 |
| `frontend/src/composables/useStudentLearning.js` | `GET /document/course/{courseId}/slides` | 存在 | M4B 间接覆盖 | 一致 |
| `frontend/src/composables/useStudentLearning.js` | `POST /progress/sync` | 存在 | M4B 覆盖 | 一致 |
| `frontend/src/composables/useStudentLearning.js` | `POST /chat/quiz` | 存在 | M4B 覆盖 | 一致 |
| `frontend/src/composables/useStudentLearning.js` | `POST /chat/ask` | 存在 | M4B 覆盖 | 一致 |
| `frontend/src/composables/usePrerequisiteJump.js` | `POST /prerequisite/analyze-gap` | 存在 | M4B 覆盖 | 一致 |
| `frontend/src/composables/usePrerequisiteJump.js` | `POST /prerequisite/jump` | 存在 | M4B 覆盖 | 一致 |
| `frontend/src/composables/usePrerequisiteJump.js` | `POST /prerequisite/return` | 存在 | M4B 覆盖 | 一致 |
| `frontend/src/composables/usePrerequisiteJump.js` | `GET /prerequisite/jump-stack` | 存在 | 未覆盖 | 路由存在 |
| `frontend/src/composables/usePrerequisiteJump.js` | `POST /prerequisite/mark-reviewed` | 存在 | 未覆盖 | 路由存在 |
| `frontend/src/composables/usePrerequisiteJump.js` | `GET /prerequisite/learning-path` | 存在 | 未覆盖 | 路由存在 |

## .vue 直接调用与重点检查

| 文件 | 调用 | 后端路由 | 风险 |
|---|---|---|---|
| `frontend/src/views/TeacherDashboard.vue` | `/document/course/{id}`、`/tts-status`、`/node/{nodeId}/synthesize-audio`、`publish/unpublish/stats/students` | 均存在 | TTS 真实服务需 fake；部分统计接口未进 M4B |
| `frontend/src/views/TeacherHistory.vue` | `/document/courses`、publish/unpublish/delete/stats/students、`/user/stats` | 均存在 | 删除已由 M4B 覆盖，统计未覆盖 |
| `frontend/src/views/StudentHome.vue` | `/document/my-courses`、`/document/courses`、enroll/unenroll | 均存在，`my-courses` 由 M4C 修复 | 该组件未注册路由 |
| `frontend/src/components/chat/player/PptPlayer/KnowledgeProgressPage.vue` | 直接 fetch `/api/v1/document/course/{courseId}/node/{nodeId}/synthesize-audio` | 存在，M4B 覆盖 | 绕过统一 request；页面未注册路由；同时调用缺失的 `api.chat` 方法 |
| `frontend/src/components/chat/player/SplitVideoPlayer.vue` | `GET /player/init/{courseId}`、`POST /player/progress/save` | 均存在 | init 响应外壳与 request 拦截器不一致，是 P0 风险 |
| `frontend/src/views/SsoCallback.vue` | `/platform/sso/callback` | 存在 | 依赖泛雅，不应自动化触网 |

## 特别检查结论

| 检查项 | 结论 |
|---|---|
| `KnowledgeProgressPage.vue` 直接 fetch 的 TTS 路径 | 后端存在 `/api/v1/document/course/{course_id}/node/{node_id}/synthesize-audio`，但页面未注册路由且绕过统一 request |
| `chat.js` 中 `/chat/${chatId}` | 后端不存在 `DELETE /api/v1/chat/{chat_id}`，不一致 |
| `progress/detail` | 后端存在 `/api/v1/progress/detail/{course_id}`，M4B 覆盖 |
| `document/my-courses` | 后端存在 `/api/v1/document/my-courses`，M4C 修复并测试覆盖；但 `StudentHome.vue` 未注册，`StudentDashboard` 主流程不直接用该接口 |
| `video-gen` 与旧 `video-generation` | 前端未发现旧 `video-generation` 调用；当前后端真实路径为 `/api/v1/video-gen` |
| prerequisite 相关路径 | 前端 6 个 prerequisite 路径后端均存在；M4B 覆盖 analyze/jump/return，其他未覆盖 |
| player 初始化和 progress 保存路径 | 路由均存在；progress save 是统一响应，init 是扁平响应，前端高风险 |
## M5C 更新：前端阻断缺陷修复

更新时间：2026-07-08

| 项目 | M5 结论 | M5C 处理 | 当前结论 |
|---|---|---|---|
| `frontend/src/api/player.js` -> `GET /player/init/{courseId}` | 后端路由存在，但返回 `PlayerInitData` 扁平结构；前端 `request.js` 可能按统一外壳拒绝 | `frontend/src/utils/request.js` 新增 `allowFlatResponse` opt-in；`getPlayerInitData` 只对该接口启用，并包装为 `{ data }` | P0 阻断风险已修复；后端 API 未变 |
| `frontend/src/components/chat/player/SplitVideoPlayer.vue` | 组件读取 `response.data` | 组件不改；由 `player.js` 保持返回 `{ data }` | 用户可见播放器流程不变 |
| `frontend/src/components/profile/LoginIn/courses/PPTGenerationDialog.vue` -> `GET /ppt/themes` | 组件按 `res.data.code` / `res.data.data.templateList` 读取，和 `request.js` 解包不一致 | 组件兼容 `res?.data?.data || res?.data || res`，并读取 `templateList` / `templates` | 响应读取风险已修复 |
| `frontend/src/components/profile/LoginIn/courses/PPTGenerationDialog.vue` -> `POST /ppt/generate-sync` | 组件按 `res.data.code` / `res.data.data.course_id` 读取，和 `request.js` 解包不一致 | 组件兼容解包后 `payload.course_id`，并继续填充原结果状态 | 响应读取风险已修复；真实外部 PPT 服务仍需可控策略 |

M5C 未改变任何后端 endpoint、service、model、数据库结构或启动方式。`/player/init/{courseId}` 后端仍为扁平响应，M4B 后端测试继续按扁平结构覆盖。

仍未修复并保留在后续清单中的不一致：`POST /user/logout`、`DELETE /chat/${chatId}`、未注册 `Knowledge.vue` / `KnowledgeProgressPage.vue` 及其缺失的 `api.chat` 方法。