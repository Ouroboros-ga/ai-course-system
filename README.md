# AI 互动智课系统

本仓库是本地原型 Demo。当前实现以代码、注册路由、数据库迁移、契约测试和浏览器手工行为为准；规划文档不能替代可运行证据。

## 当前媒体与数字人方案

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

学习端不解析 PPTX、不调用 TTS，也不为每位学生启动服务端数字人推理。发布清单中的每个知识点拥有独立音频、字幕、Cue 和 PPT 映射；当前活动知识点的原生 `<audio>` 是唯一主时钟，PPT、字幕、知识点切换和 PixiJS 角色都从 `audio.currentTime` 投影。数字人首版固定使用平台预制 PixiJS 2D 角色 `platform-instructor-v1`，按 `avatar-cues/v1` 驱动；Cue 或 WebGL 不可用时降级为静态头像或关闭，绝不阻断音频、PPT 和字幕。

服务端只负责权限、批次编排、缓存复用、时序归一化、对象存储和版本发布。媒体数据只保存 `object_key`、SHA 和签名 URL，不保存绝对路径。Local storage 与 S3/OSS presigned PUT/POST 通过同一适配层切换。

## 课程 87 当前状态

代码链路已接入 P4 批量 API、`ppt-manifest/v1`、`audio-playlist/v1` 和 PixiJS 播放面；但本地数据库中的课程 87 仍没有 active `MediaRelease`，正式课程快照的 `media_snapshot` 为空。当前真实阻塞是 PPT 映射/manifest 和新一批可播放媒体资产尚未完成冻结。因此页面可以计划、生成 Fake WAV 并试听，但服务端必须拒绝半成品清单冻结、媒体激活和正式发布。

Fake TTS 使用 `fake-v1.1-playable` 生成浏览器可解码 WAV，仅用于本地链路和试听，不代表真实音质、字级时间戳或数字人口型效果；自动化测试禁止调用豆包、讯飞或其他付费服务。

## 课程系统总链路

```text
课程资料 → 统一上传与版本化对象存储 → 解析任务 / DocumentIR / Evidence
→ 可信检索、课程图谱与教学结构 → 教师审核、编辑与发布
→ 学生学习、练习、代码实验、TeachingAgent 与课程媒体播放
```

课程授权统一遵循 Course Access v1；学生代码只通过独立 Judge0 沙箱执行。外部 LLM、OCR、TTS、PPT 和数字人服务只能经独立适配层或任务服务接入。

## 开发入口

- [开发与安全规则](AGENTS.md)
- [前端设计指南](design.md)
- [文档导航](docs/DOCUMENTATION_INDEX.md)
- [阶段 8：媒体与数字人当前方案](docs/phase1/阶段8_媒体TTS数字人PPT_实施规划.md)
- [当前功能审计](docs/phase1/功能现状审计表.md)
- [运行说明](docs/RUN.md)

## 文档维护与废弃规则

与开发者讨论后发生的产品方案、技术路线、发布门槛或真实状态变化，必须在同一变更中同步 README、对应 `docs/phase1/` 现行文档和必要的审计/契约文档，并在文档中记录日期、变更原因和代码证据。被替代的路线不得继续作为实现依据：应在原文档顶部标记“已废弃/仅历史追溯”，并链接到现行文档；不要用旧文档证明功能已完成。

`docs/phase1/` 是当前实施基线；`docs/refactor/`、`backend/docs/`、`frontend/docs/` 和根目录产品材料仅用于历史追溯，除非在文档导航中明确重新登记。

`docs/research/` 与 `research/` 保存离线研究和实验，不构成生产效果证明。

## 前端约定

前端视觉令牌、布局、滚动模型、过渡动画、组件和按钮规范以 [`design.md`](design.md) 为唯一权威。新增或修改页面、组件前必须先阅读该文档。
