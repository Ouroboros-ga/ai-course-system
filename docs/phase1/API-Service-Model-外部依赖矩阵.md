# API-Service-Model-外部依赖矩阵

更新时间：2026-07-08

本矩阵只依据实际代码调用链，不依据规划文档推断实现状态。

## 后端主入口实际注册路由

证据：`backend/app/main.py:63-80`

| 主入口注册 | endpoint 文件 | prefix | 接入状态 | 说明 |
|---|---|---|---|---|
| `user.router` | `backend/app/api/v1/endpoints/user.py` | `/api/v1/user` | 已接入主流程 | 登录、注册、用户信息、用户列表、角色、统计 |
| `document.router` | `backend/app/api/v1/endpoints/document.py` | `/api/v1/document` | 已接入主流程 | 文档上传、课程、脚本、选课、统计、PPT 图片、TTS |
| `chat.router` | `backend/app/api/v1/endpoints/chat.py` | `/api/v1/chat` | 已接入主流程 | 聊天历史、消息、问答、测验 |
| `progress.router` | `backend/app/api/v1/endpoints/progress.py` | `/api/v1/progress` | 已接入主流程 | 理解度分析、进度同步、续学、节点完成 |
| `knowledge.router` | `backend/app/api/v1/endpoints/knowledge.py` | `/api/v1/knowledge` | 已接入主流程 | 知识库、知识点、检索、导入、关系 |
| `prerequisite.router` | `backend/app/api/v1/endpoints/prerequisite.py` | router 自带 `/api/v1/prerequisite` | 已接入主流程 | 前置知识缺口分析、跳转、返回、路径 |
| `asset.router` | `backend/app/api/v1/endpoints/asset.py` | `/api/v1/asset` | 已接入主流程 | 教师素材上传、预览、默认素材、声音复刻 |
| `mapping.router` | `backend/app/api/v1/endpoints/mapping.py` | `/api/v1/mapping` | 已接入主流程 | 知识点与 PPT 页映射 |
| `player.router` | `backend/app/api/v1/endpoints/player.py` | `/api/v1/player` | 已接入主流程 | 分屏播放器初始化、进度保存 |
| `ppt_generation.router` | `backend/app/api/v1/endpoints/ppt_generation.py` | `/api/v1/ppt` | 已接入主流程 | PPT 模板、生成、同步生成、任务状态 |
| `video_generation.router` | `backend/app/api/v1/endpoints/video_generation.py` | `/api/v1/video-gen` | 已接入主流程 | 课程/节点数字人视频生成、任务、健康检查 |
| `video.router` | `backend/app/api/v1/endpoints/video.py` | `/api/v1/video` | 已接入主流程 | 本地/远程视频播放、上传、信息 |
| `platform.router` | `backend/app/api/v1/endpoints/platform.py` | `/api/v1/platform` | 已接入主流程 | 泛雅 SSO、用户/课程/选课同步、进度回调 |
| `document.router` | `backend/app/api/v1/endpoints/document.py` | `/api/v1/chat/file` | 已接入但高风险 | 同一个 document router 被二次挂载到聊天文件路径 |

## 存在但未由 `main.py` 注册的 endpoint 文件

| 文件 | 代码证据 | 状态 | 风险 |
|---|---|---|---|
| `backend/app/api/v1/endpoints/document_course.py` | `router = APIRouter(prefix="/document")` at line 22；未见 `main.py` include | 已完成但未接入主流程 | 与 `document.py` 中 `/courses` 等功能重复，易造成文档与代码分叉 |
| `backend/app/api/v1/endpoints/document_upload.py` | `@router.post("/upload")` at line 35；未见 `main.py` include | 已完成但未接入主流程 | 与 `document.py` 上传/分析逻辑重复 |
| `backend/app/api/v1/endpoints/document_new.py` | `@router.get("/courses")` at line 86；未见 `main.py` include | 已完成但未接入主流程 | 新旧 document endpoint 并存，维护成本高 |
| `backend/app/api/v1/endpoints/document_script.py` | 仅定义 `APIRouter(prefix="/document")` | 占位代码 | 未发现实际路由函数 |
| `backend/app/api/v1/endpoints/document_tts.py` | 仅定义 `APIRouter(prefix="/document")` | 占位代码 | 未发现实际路由函数 |
| `backend/app/api/v1/endpoints/agents.py` | 文件内容只有注释 | 占位代码 | 不得作为复杂多智能体已实现证据 |
| `backend/app/api/v1/endpoints/cognitive.py` | 文件内容只有注释 | 占位代码 | 不得作为 BKT/HMM/LSTM 或认知追踪已实现证据 |
| `backend/app/api/v1/endpoints/graphrag.py` | 文件内容只有注释 | 占位代码 | 不得作为 GraphRAG 已实现证据 |
| `backend/app/api/v1/endpoints/codebench.py` | 文件内容只有注释 | 占位代码 | 不得作为计算机垂类已实现证据 |
| `backend/app/api/v1/endpoints/visualization.py` | 文件内容只有注释 | 占位代码 | 不得作为可视化智能体已实现证据 |
| `backend/app/api/v1/endpoints/router.py` | 文件内容只有“统一路由注册”注释 | 占位代码 | 实际注册在 `main.py`，此文件不是统一路由中心 |

## API 到 Service、Model、外部依赖矩阵

| 功能/API 组 | 主要路由或函数 | Endpoint | Service | Model | 外部依赖 | 调用关系与判断 |
|---|---|---|---|---|---|---|
| 用户认证与管理 | `/login` `/register` `/me` `/modify` `/list` `/role` `/stats` | `user.py:33-240` | 未使用独立 user service，`user_service.py` 长度为 0 | `User`、`UserRole`、`Course`、`StudentEnrollment` | JWT/签名相关工具 | endpoint 直接操作模型，已接入主流程 |
| 文档上传与课程生成 | `/document/upload` `/document/analyze` | `document.py:149-437` | `document_service`、`smart_course_service` | `Course`、`CourseScript`、`ScriptNode`、Docling 系列表 | Docling/Office 转 PDF、LLM、文件系统 | endpoint 保存文件后调用解析与脚本生成；外部解析和 LLM 必须 Mock |
| 课程管理与脚本编辑 | `/document/courses` `/document/course/{id}` `/save` `/publish` `/unpublish` `/delete` | `document.py:465-1394` | 部分直接写库，部分调用 `document_service` | `Course`、`CourseScript`、`ScriptNode`、进度/QA/视频相关模型 | 文件系统 | `document.py` 同时承载查询、保存、发布、删除与级联清理 |
| 学生选课与学习统计 | `/enroll` `/unenroll` `/my-courses` `/students` `/stats` | `document.py:1553-1944` | endpoint 内部辅助函数 `_init_learning_progress_for_student`、`_ensure_learning_progress` | `StudentEnrollment`、`LearningProgress`、`NodeProgress` | 无直接外部服务 | 已接入学生/教师主流程，但集中在大文件内 |
| PPT 图片与节点音频 | `/slides` `/slide/{page_num}` `/node/{node_id}/synthesize-audio` `/audio/{course_id}/{filename}` `/synthesize-all-audio` | `document.py:2106-2396` | endpoint 内部文件渲染与 TTS 调用 | `Course`、`CourseScript`、`ScriptNode` | `tts_client`、LibreOffice/PDF 渲染、文件系统 | 已接入主流程；TTS 与渲染需要可控替身 |
| 聊天问答 | `/chat/history` `/messages/{chat_id}` `/ask` `/create` `/quiz` | `chat.py:25-411` | `qa_service`、`progress_service` | `ChatHistory`、`ChatMessage`、`Course`、`CourseScript`、`DoclingDocument`、`DoclingText` | `llm_client` 经 service 调用 | 已接入学生学习问答主流程 |
| 学习进度 | `/progress/analyze` `/visualization/{course_id}` `/sync` `/resume/{course_id}` `/detail/{course_id}` `/node/complete` `/continuation` | `progress.py:29-469` | `progress_service` | `LearningProgress`、`NodeProgress`、`UnderstandingAnalysis`、`ChatMessage` | `llm_client` | endpoint 和 service 均可能调用 LLM；自动化测试必须 patch |
| 知识库 | `/knowledge/bases` `/points` `/search` `/import/*` `/relations` `/stats` | `knowledge.py:37-688` | `KnowledgeBaseService`、`KnowledgePointService`、`KnowledgeSearchService`、`KnowledgeImportService`、`KnowledgeRelationService` | `KnowledgeBase`、`KnowledgePoint`、`KnowledgeRelation`、`KnowledgeImportLog`、`KnowledgeSearchHistory` | 文件导入/解析；未见主流程 GraphRAG | 已接入知识库 CRUD 与检索，但不是 GraphRAG |
| 映射引擎 | `/mapping/{course_id}` `/pages` `/auto` `/ai-match` `/nodes/{node_id}` `/batch` `/apply` | `mapping.py:39-217` | `mapping_service` | `KnowledgePageMap`、`Course`、`CourseScript`、`ScriptNode` | `llm_client`、PPTX 文本提取 | 已接入主流程；AI 匹配路径必须 Mock LLM |
| 分屏播放器 | `/player/init/{course_id}` `/knowledge-points/{course_id}` `/progress/save` `/progress/{course_id}` | `player.py:66-424` | 局部使用 `MappingService` | `Course`、`CourseScript`、`ScriptNode`、`VideoGenerationTask`、`LearningProgress`、`KnowledgePageMap` | 文件路径、PPT/PDF 转图 | 已接入学生播放器主流程 |
| PPT 生成 | `/ppt/themes` `/task/{sid}` `/generate` `/generate-sync` | `ppt_generation.py:62-184` | `ppt_generation_service`、`document_service` | `Course`、`CourseScript`、`ScriptNode`、Docling 文本模型 | `llm_client`、讯飞 PPT API、文件下载 | 已接入但依赖真实外部服务；测试需完全替身 |
| 数字人视频生成 | `/video-gen/course/{course_id}/generate` `/node/{node_id}/generate` `/task/{task_id}` `/course/{course_id}/tasks` `/health` | `video_generation.py:32-209` | `video_generation_service` | `VideoGenerationTask`、`Course`、`CourseScript`、`ScriptNode` | `tts_client`、`digital_human_client` | 已接入但真实调用成本高；健康检查也会触达服务 |
| 视频服务 | `/video/stream/{filename}` `/file/{filename}` `/list` `/remote` `/upload` `/info/{filename}` | `video.py:53-250` | 无独立 service | 文件系统 | `httpx` 用于远程视频上传/播放 | 已接入视频播放；远程接口测试需 patch httpx |
| 泛雅平台 | `/platform/sso/callback` `/syncUser` `/syncCourse` `/syncEnrollment` `/callback/progress` `/bind/status/{course_id}` `/unbind/{course_id}` `/status` | `platform.py:72-502` | endpoint 内部逻辑 | `User`、`Course`、`StudentEnrollment` | `httpx` 推送泛雅 | 已接入；部分接口使用 `Depends(lambda: {"user_id": 1})`，测试与安全审计需特别标记 |
| 前置知识跳转 | `/api/v1/prerequisite/analyze-gap` `/jump` `/return` `/jump-stack` `/mark-reviewed` `/learning-path` | `prerequisite.py:28-503` | `PrerequisiteAnalyzer`、`JumpHistoryManager` | `LearningJumpHistory`、`ScriptNode` | `llm_client` | 已接入主流程；不是 BKT/HMM/LSTM |

## 外部服务客户端清单

| 外部服务 | 代码位置 | 入口类/单例 | 当前风险 | M4-M7 Mock 建议 |
|---|---|---|---|---|
| LLM | `backend/app/common/llm_client.py:38-499` | `DoubaoClient`、`QwenClient`、`WenxinClient`、`OpenAIClient`、`LLMClient`、`llm_client` | 默认 `LLM_PROVIDER=doubao`，没有统一 mock provider 证据 | monkeypatch `llm_client.chat` / `simple_chat` |
| TTS | `backend/app/common/tts_client.py:35-526` | `AliyunTTSClient`、`TencentTTSClient`、`VolcengineTTSClient`、`MockTTSClient`、`tts_client` | 生产 provider 默认见 `config.py:71`，测试可用 mock 但需显式隔离 | 设置测试环境或 patch `tts_client.synthesize` |
| 声音复刻 | `backend/app/common/tts_client.py:529-656` | `VoiceCloneClient`、`voice_clone_client` | 火山接口真实调用风险 | patch `voice_clone_client.create_voice_clone` / status 查询 |
| 数字人 | `backend/app/common/digital_human_client.py:38-206` | `DigitalHumanClient`、`digital_human_client` | 健康检查和生成均可能请求 Gradio | patch `check_health` / `generate_video` |
| 讯飞 PPT | `backend/app/services/ppt_generation_service.py:37-463` | `XfyunPPTClient`、`PPTGenerationService`、`ppt_generation_service` | 模板、创建、轮询、下载均为 httpx 外部调用 | 替换 `xfyun_client` 为 fake client |
| 泛雅平台 | `backend/app/api/v1/endpoints/platform.py:80`、`:422` | `httpx.AsyncClient` | SSO/回调推送外部网络风险 | patch `httpx.AsyncClient` 或封装后替换 |
| 远程视频 | `backend/app/api/v1/endpoints/video.py:157`、`:206` | `httpx.AsyncClient` | 测试远程播放/上传会触网 | patch `httpx.AsyncClient` |

## 前端实际 API 调用面

证据：`frontend/src/api/*.js`、`frontend/src/composables/*.js`、`frontend/src/views/*.vue`

| 前端模块 | 后端 API | 证据 | 风险 |
|---|---|---|---|
| 用户 | `/user/login` `/register` `/me` `/modify` `/list` `/role` `/stats` | `frontend/src/api/user.js:12-97` | `user.js:44` 调用 `GET /user/me` 作为 logout 相关接口需核查语义 |
| 聊天 | `/chat/history` `/chat/create` `/chat/ask` `/chat/messages/{id}` | `frontend/src/api/chat.js:11-109` | `chat.js:45` 使用 `/chat/${chatId}`，后端未见对应路由，只见 `/messages/{chat_id}` |
| 素材 | `/asset/upload` `/asset/` `/asset/{id}/default` `/clone-voice` | `frontend/src/api/asset.js:13-50` | 预览 URL 直接拼接 base URL，不走统一 request |
| 映射 | `/mapping/{courseId}` `/pages` `/auto` `/ai-match` `/batch` `/apply` | `frontend/src/api/mapping.js:9-43` | AI 匹配触发 LLM |
| 平台 | `/platform/sso/callback` `/syncUser` `/syncCourse` `/syncEnrollment` `/status` | `frontend/src/api/platform.js:4-51` | 外部泛雅接口测试需 patch |
| 播放器 | `/player/init/{courseId}` `/knowledge-points/{courseId}` `/progress/save` | `frontend/src/api/player.js:14-46` | 与学生学习主流程强相关 |
| PPT 生成 | `/ppt/themes` `/ppt/generate` `/ppt/generate-sync` `/ppt/task/{sid}` | `frontend/src/api/ppt_generation.js:9-24` | 真实调用会触发 LLM+讯飞 |
| 进度 | `/progress/analyze` `/visualization/{courseId}` `/sync` `/resume/{courseId}` `/node/complete` | `frontend/src/api/progress.js:12-77` | `progress/detail/{courseId}` 由 `useStudentLearning.js` 直接调用 |
| 脚本编辑 | `/document/course/{courseId}/script/*` `/save` | `frontend/src/api/script_editor.js:9-26` | 直接依赖 `document.py` 大文件接口 |
| 视频 | `/video/list` `/video/info/{filename}` `/video/upload` `/video/remote` | `frontend/src/api/video.js:4-22` | `getVideoStreamUrl` 返回裸 `/api/v1/video/stream/{filename}` |
| 学生学习组合式函数 | `/document/courses` `/enroll` `/course/{id}` `/slides` `/progress/detail` `/chat/quiz` `/chat/ask` `/prerequisite/*` | `frontend/src/composables/useStudentLearning.js:105-604`、`usePrerequisiteJump.js:22-172` | 主流程集中且长文件，后续冒烟测试优先覆盖 |
| 直接 fetch 绕过统一 request | `/api/v1/document/course/{courseId}/node/{nodeId}/synthesize-audio` | `frontend/src/components/chat/player/PptPlayer/KnowledgeProgressPage.vue:498-499` | 绕过统一拦截器和错误处理，是测试与认证风险点 |

## 配置与部署依赖矩阵

| 项 | 代码证据 | 审计结论 |
|---|---|---|
| 当前数据库 | `backend/app/models/database.py:54` 使用 `sqlite:///.../smart_class.db` | 当前开发/运行模型是 SQLite |
| 启动建表 | `backend/app/main.py:37` 调 `create_tables()`；`database.py:64` `SQLModel.metadata.create_all(engine)` | 导入主应用会写数据库结构 |
| 启动迁移 | `backend/app/main.py:38` 调 `run_migrations()` | 导入主应用会执行迁移逻辑 |
| 启动依赖检查 | `backend/app/main.py:16` `run_dependency_check(auto_install=True)` | 导入主应用可能触发依赖检查/安装逻辑，是测试副作用 |
| 前端 dev proxy | `frontend/vite.config.js:24-26` 代理 `/api` 到 `http://localhost:8000` | 本地联调依赖该代理 |
| 部署 compose | `deploy/docker-compose.yml:3-23` 只有 PostgreSQL 和 Neo4j | 与当前 SQLite 代码路径不一致，不能作为当前运行事实 |
