# AI 互动智课系统

> **2026-08-10 首轮智能备课稳定性：** `segment_evidence` 使用页内碎块合并后的分层 Map/Reduce；模型不返回证据 ID，服务端确定性回填并在持久化前展开真实 `DocumentBlock.block_id`。默认单批正文不超过 24,000 字、Map 并发 2，证据 Reduce/大纲输出上限为 16,384 tokens；全局 `LLM_MAX_TOKENS` 不变。高密度课程材料的 Map + Reduce 共享调用预算从 64 提升到 160，仍保留总材料、分块数和并发硬上限。Map/Reduce 对描述性 `examples`/`exercises` 稳定去重、去空并裁剪至 10 项，Map 分段内冗余 `stage` 会被移除；其他结构与证据字段仍 fail-closed。真实大材料端到端验收仍在继续，任何剩余失败均不覆盖原课程草稿。代码证据见 `course_initial_prep_service.py`、`controlled_prep_workflow.py`、`controlled_prep.py` 与 `prep/llm_adapter.py`；Fake/本地回归未调用真实付费模型。

> **2026-08-09 Ubuntu 部署基线：** 服务器文件解析、LanceDB/GraphRAG、Judge0、Node 与外部 Provider 的真实状态和回滚方式见 [服务器环境一致性与外部链路审计](docs/phase1/2026-08-09_服务器环境一致性与外部链路审计.md)。LanceDB 0.34/PyArrow 25 在 Ubuntu x86_64 未发现兼容阻塞；GraphRAG 必须经独立 Python Worker，真实 LLM 构图受 token、USD 预估、数据外发授权与人工确认闸门控制。当前 GraphRAG/Judge0 均 fail-closed：前者等待课程数据范围/目的地级外发授权，后者因官方 isolate 需要共用主机不接受的提升权限而未启用。

> **2026-08-09 账户名称收敛**：账户只有一个可见且可登录的 `username`：`/app/admin`、右上角和个人中心均展示/编辑它，数字用户 ID 不变；登录接受“用户名或数字用户 ID + 密码”。旧 `real_name` 仅保留为外部资料字段，不再作为账户昵称。管理员与 Provider 配置入口仍为 `/app/admin`；详见 [现行实施说明](docs/phase1/平台管理员Provider与开放API兼容层.md)。

本仓库是本地原型 Demo。当前实现以代码、注册路由、数据库迁移、契约测试和浏览器手工行为为准；规划文档不能替代可运行证据。

> **2026-08-07 ResearchAgent P0**：新增课程内 `/app/course/:courseId/research` 研究工作台与独立 `platform/agents/research/`。当前真实接通 arXiv 元数据检索、课程权限、PII 脱敏、来源核验和补充参考边界；趋势分析、证据综合、学术写作、Semantic Scholar/OpenAlex/Crossref 与完整仓库复现仍为 `Research Preview`，未伪装完成。现行架构、开源选型、数据模型与分阶段上线门见 [ResearchAgent 整体架构、前端与上线基线](docs/phase1/研究智能体整体架构与前端设计.md)。

> **2026-08-07 Stage 8 Provider**：本地媒体 Demo 必须显式 `MEDIA_DEMO_MODE=true`，页面
> 显示 `fake-demo` 且不会调用付费 TTS；正式媒体生成须设置 `MEDIA_DEMO_MODE=false` 与
> `STAGE8_TTS_PROVIDER=doubao`，缺失配置时 fail-closed。详见
> [`docs/phase1/阶段8_P5.0_Provider配置基线.md`](docs/phase1/阶段8_P5.0_Provider配置基线.md)。

## 当前媒体与数字人方案

> **2026-08-10 平台女性讲师预设**：`platform-female-instructor-v1@1.0.0` 已成为新媒体建设的默认 2D 角色。它由一张 960px 静默虚构女性讲师肖像、8 个口型补丁和 1 个闭眼补丁组成；发布播放响应会分别签发 manifest 与纹理 URL，浏览器仅按 `avatar-cues/v1` 和 `<audio>` 时钟选择口型/眨眼。旧 `platform-instructor-real-v1@1.0.0`（汽车教师）已退休，仅允许已冻结的历史 Release 解析，不能被静默替换。课程 87 的当前发布版本也必须按“新建媒体版本 → 激活 → 正式课程发布”切换，不能覆盖旧快照。

> **2026-08-10 本地播放回归**：已用 `MEDIA_DEMO_MODE=true` 在课程 87 的三知识点合成 fixture 上重新执行 Fake WAV、PPT manifest、`audio-playlist/v1`、MediaRelease 激活、CourseRelease 发布与学生学习页播放。当前本地快照为 `mrel_2376035e170c438c9ee9d9dc331145a9` / `cr_8897817c555447928962abc3f1880c25`，播放清单 SHA-256 为 `9432c7de…`；它是可重复创建的本地诊断数据，不替代历史 20 节点快照，更不代表真实课程或付费 TTS 质量。真实本地 Chrome 已验证签名角色资源、音频/PPT/字幕/目录/口型共同时钟、跨节点 seek、播放与暂停状态保持、自然续播及 manifest 失败静态降级。480p 视口下 4.123 秒短测记录 977 帧（约 237 FPS），只证明该次无头 Chrome 短测超过 24 FPS；Windows Computer Use 桥本次不可用，且尚未完成有头 GPU、连续 10 分钟和掉帧率验收。

媒体主链已经冻结为“课程级批量建设 + 不可变播放清单”：

```text
课程讲稿 / 知识点选择 / PPT 映射
  → 服务端只读计划（脚本指纹、缓存命中、字符数、费用估算）
  → 教师一次确认
  → MediaBuildBatch + MediaReleaseItem
  → Fake WAV 或受控 Media Worker TTS
  → 字幕与 avatar-cues/v1 非付费冻结
  → ppt-manifest/v1 冻结
  → audio-playlist/v1 冻结
  → MediaRelease 激活
  → 正式课程发布快照固定 release_id + playlist_content_hash
  → 学习端 playback API
```

### P5.1：平台音色与 2D 角色注册表（2026-08-07）

**2026-08-10 状态更新**：平台注册表的活跃默认角色已切换为 `platform-female-instructor-v1@1.0.0`。源图为本地生成的虚构人物、无真实人物参考；其来源说明与 SHA-256 记录在 `frontend/src/assets/platform-avatar-presets/platform-female-instructor-v1/source/SOURCE.md`。源图实为 1254×1254（不是 2K），但处理后的 960px 主纹理足以覆盖当前 480p 目标。纹理对象采用内容寻址 `object_key`，按课程/Release/预设 scope 签发；加载失败降级，绝不使音频、PPT 或字幕停播。

当前实现已将媒体版本绑定从前端硬编码提升为服务端注册表：

- `PlatformVoicePreset` 与 `PlatformAvatarPreset` 由服务端维护，批量计划重新解析并在 `MediaBuildBatch` / `MediaRelease` 中冻结 `preset_id + version`。
- `GET /api/v1/media/course/{course_id}/platform-presets` 只返回安全的显示信息和内容哈希，不暴露 Doubao speaker、resource ID 或密钥。
- 首版已注册 1 个 fake-demo 音色和 4 个平台预制 Sprite2D 角色；默认建设角色为 `platform-female-instructor-v1@1.0.0`（半写实虚构女性教师）。旧 `platform-instructor-real-v1@1.0.0`（汽车教师）为历史 Release 兼容项，不能在新建设中选择；角色 manifest 按版本写入对象存储并通过发布版本签名下发。
- 学习端按发布版本加载 manifest；加载失败依次降级为本地平台默认角色、静态头像、无数字人，音频/PPT/字幕不被阻断。

P5.1/P5.2 已通过本地 fake provider、SQLite 迁移、上传隔离和前端构建验证。P5.3 的单次豆包短文本 POC 已有脱敏历史结果：音频与 `words` 返回，时间误差约 191.583ms，但 `phonemes` 为空，因此不能承诺精确口型；本回合重新调用被外部付费请求审批拦截，未重试。详见 [`阶段8_P5.3_一次受控豆包验收`](docs/phase1/阶段8_P5.3_一次受控豆包验收.md)。

学习端不解析 PPTX、不调用 TTS，也不为每位学生启动服务端数字人推理。发布清单中的每个知识点拥有独立音频、字幕、Cue 和 PPT 映射；当前活动知识点的原生 `<audio>` 是唯一主时钟，PPT、字幕、知识点切换和 PixiJS 角色都从 `audio.currentTime` 投影。数字人首版使用发布版本冻结的半写实平台注册角色（当前默认 `platform-female-instructor-v1@1.0.0`），按 `avatar-cues/v1` 驱动；这不是某位真实教师的肖像。Cue 或 WebGL 不可用时降级为静态头像或关闭，绝不阻断音频、PPT 和字幕。

这次浏览器回归的代码修正集中在 `media_timeline.py`（平台 manifest/纹理签名与 Course Access）、`Sprite2DRenderer.js` / `AvatarViewport.vue`（无扩展名纹理解析、人物主体与正确 Canvas 尺寸）、`LectureStage.vue`（跨知识点 keyed audio 事件隔离与自然续播）及 `unified_learning_service.py`（SQLite 时区时间归一化）。Fake Cue 没有音素，因此页面必须显示“字幕段估算”，不能把可动嘴型表述为精确唇形同步。

服务端只负责权限、批次编排、缓存复用、时序归一化、对象存储和版本发布。媒体数据只保存 `object_key`、SHA 和签名 URL，不保存绝对路径。Local storage 与 S3/OSS presigned PUT/POST 通过同一适配层切换。

### P5.2：OSS 与旧链隔离（2026-08-07）

上传意图按对象存储协议返回：Local 使用受控 `PUT`，S3/OSS 使用 `POST fields + file`；两者上传完成后都必须调用服务端 `confirm`，由服务端重新 HEAD、计算 SHA、探测 MIME/时长。Local 媒体读取 URL 强制携带并校验 `exp/sig/object_key/scope`，scope 绑定课程和用途。旧 `/video-gen` 仅保留历史 `VideoGenerationTask` 兼容，带弃用响应和 Sunset，不得写入新的 `MediaRelease` 或正式播放清单。



## 课程系统总链路

### 2026-08-07 统一学习数据链

学习页面现在以 `course_id + release_id + outline_node_id` 作为知识点学习身份。学习事件写入不可变 `learning_events`，再投影到学生学习状态和教师课程统计；曝光/完成与评分型认知证据分离。正式评分产生的 `LearningEvidenceRecord` 会以 `LearningEvidenceContext` 关联图谱节点与可安全确定的 release/outline 身份；无法唯一映射时保留 unknown，不猜测来源。学生学习轨道直接显示自己的完成进度，并以双层状态显示“已掌握/待掌握/需要更多证据/暂不可分析”；点击状态后按需读取认知详情，认知不可用不阻断学习。新学习页已接入 `learning-context`、事件写入和显式完成接口，刷新后从当前 release 投影恢复最近锚点；失败事件暂存浏览器待发队列。教师 `/app/course/:courseId/analytics` 已读取统一统计投影。接口与 Agent planned Port/Tool 边界见 [统一学习进度认知推荐统计契约](docs/phase1/统一学习进度认知推荐统计契约.md)。

```text
课程资料 → 统一上传与版本化对象存储 → 解析任务 / DocumentIR / Evidence
→ 可信检索、课程图谱与教学结构 → 教师审核、编辑与发布
→ 学生学习、练习、代码实验、TeachingAgent 与课程媒体播放
```

课程授权统一遵循 Course Access v1；学生代码只通过独立 Judge0 沙箱执行。外部 LLM、OCR、TTS、PPT 和数字人服务只能经独立适配层或任务服务接入。

### 2026-08-07 Conversation Domain 与提问反推

TeachingAgent 的数据持久化按三个相互独立的域划分（AGENTS.md §5.1）：

1. **Agent Runtime Context / Audit 域**仍保持数据最小化。`agent_learning_events`、`agent_trace_records`、`agent_conversation_sessions` 由白名单 sanitize 函数强制最小化，不持久化原始问题、完整答案、Prompt 或完整 LLM Trace。
2. **Conversation Domain（产品体验域）**独立持久化学生与教学智能体的完整消息（`conversation_messages` 表 + `conversation_service`），用于刷新 / 重新进入课程后恢复对话。写入在 TeachingAgent 端点回答成功后非阻塞进行；读取经 `GET /api/v1/teaching-agent/conversations/{course_id}`，仅限学习者本人，带独立 `data_policy_version="conversation-domain/1"` 与 `retention_until` 保留窗口（默认 90 天）。
3. **学习分析不得直接依赖完整 Conversation**。提问反推经 `derive_question_inference_signals` / `GET /api/v1/teaching-agent/conversations/{course_id}/inference` 把近期提问聚合成结构化信号（计数、平均提问深度、薄弱标记、trace 引用），不返回原文；认知/推荐/出题只消费此结构化投影。

前端 `useLearningWorkspace.load()` 在 TeachingAgent 受控条件齐备时调用 `getConversationHistory` 重建聊天面板，学生可在刷新后继续上下文对话。

## 开发入口

- [开发与安全规则](AGENTS.md)
- [前端设计指南](design.md)
- [文档导航](docs/DOCUMENTATION_INDEX.md)
- [阶段 8：媒体与数字人当前方案](docs/phase1/阶段8_媒体TTS数字人PPT_实施规划.md)
- [当前功能审计](docs/phase1/功能现状审计表.md)
- [ResearchAgent 整体架构与前端设计](docs/phase1/研究智能体整体架构与前端设计.md)
- [运行说明](docs/RUN.md)

## 文档维护与废弃规则

与开发者讨论后发生的产品方案、技术路线、发布门槛或真实状态变化，必须在同一变更中同步 README、对应 `docs/phase1/` 现行文档和必要的审计/契约文档，并在文档中记录日期、变更原因和代码证据。被替代的路线不得继续作为实现依据：应在原文档顶部标记“已废弃/仅历史追溯”，并链接到现行文档；不要用旧文档证明功能已完成。

`docs/phase1/` 是当前实施基线；`docs/refactor/`、`backend/docs/`、`frontend/docs/` 和根目录产品材料仅用于历史追溯，除非在文档导航中明确重新登记。

`docs/research/` 与 `research/` 保存离线研究和实验，不构成生产效果证明。

## 前端约定

前端视觉令牌、布局、滚动模型、过渡动画、组件和按钮规范以 [`design.md`](design.md) 为唯一权威。新增或修改页面、组件前必须先阅读该文档。
# 当前学习页进度可见性（2026-08-08）

学生学习页使用 `/facade/course/{course_id}/learning-context` 作为唯一聚合读模型：
同一响应包含当前发布版本的知识点清单、学习状态、认知摘要和推荐摘要。轨道以图标与文字
分别展示“未学习/学习中/已完成”和“已掌握/待掌握/需要更多证据/暂不可分析”；观看行为不会
直接变成掌握结论。节点详情提供完成原因、置信度、正式证据数量和知识图谱依据入口。

推荐动作复用现有练习面板和学习状态机；消费接口成功时由服务端写入统一
`recommendation_consumed` 学习事件，失败时保留本地待发送队列。认知和推荐服务降级不会阻断
课程学习。
