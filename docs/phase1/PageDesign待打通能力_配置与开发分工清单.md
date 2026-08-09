# PageDesign 待打通能力：配置与开发分工清单

**状态：** 2026-07-28 代码审计后的实施清单。
**目的：** 将“页面/接口已经存在”与“教师、学生可以连续使用”分开，不把环境缺失误判为代码未完成，也不把占位实现表述为可用能力。

> **2026-08-09 部署更新：** Ubuntu 服务器的实际差异、GraphRAG 真实 LLM 预算闸门、PaddleOCR/Judge0 资源约束与 Fake 链路状态已迁移到 [服务器环境一致性与外部链路审计](2026-08-09_服务器环境一致性与外部链路审计.md)。本清单继续作为能力分工入口，实际服务器状态以后者与运行命令为准。

## 0. 先看结论

当前系统的基础课程、权限、题库练习、任务、图谱治理、课程建设数据模型和本地存储已经具备较多实现。真正阻断 PageDesign 体验闭环的，不是一个单一 Bug，而是三类事项：

1. **必须由部署者配置或运行的外部能力**：PaddleOCR、LibreOffice、LLM、Judge0、TTS、数字人、泛雅和对象存储；
2. **可由开发/Codex 在仓库内完成的接线工作**：PPT 页映射、从解析产物生成结构/讲稿、Evidence/R2 晋级、Agent 动作回写、动画计划、前端遗留冻结文案；
3. **必须共同验收的真实课程数据链**：新材料上传、教师审核、发布、学生引用/练习/图谱/实验。

> 规则：任何密钥只放部署环境的 `.env` 或密钥管理系统，绝不提交到仓库、测试、日志或文档。

---

## A. 需要你配置、部署或提供授权的事项

这些不是单靠修改前后端代码能完成的。完成后由开发侧用一个受控样例课程验收。

| 优先级 | 服务/资料 | 你需要提供或操作 | 配置完成标志 | 未完成时的真实表现 |
|---|---|---|---|---|
| P0 | PaddleOCR Docker 服务（人工配置阻塞） | 让 Docker Desktop/未来 Linux Docker 构建并运行 `deploy/paddleocr/compose.yml`；开放后端可访问的 OCR 地址。当前代码仅保留 `OcrProvider`/`DocumentOcrPort` fake/unavailable 接口，不生成假文本。 | `GET /health` 成功；PPT 图片页、PDF 每页、图片均能返回文本与坐标。 | PDF/图片解析按设计 fail-closed；不会伪造“解析成功”。 |
| P0 | LibreOffice 转换环境 | 在**解析 Worker 所在环境**安装 `soffice`，或使用包含 LibreOffice 的 Worker 容器。 | DOC、DOCX、PPT/PPTX 转 PDF 的实际样例成功；失败可读错误明确要求重新上传 DOCX/PDF。 | DOC/DOCX/非原生材料无法进入统一 PDF + OCR 链。 |
| P0 | 可供验收的新课程材料 | 选择一套可上传的 PPTX/PDF（可附 DOCX、图片）及教师审核人。旧课程不自动迁移，应走重新上传。 | 该课程生成 SourceMaterialVersion、DocumentBlock、Evidence 候选、结构/讲稿草稿并由教师发布。 | 旧课程没有新 Evidence/GraphSnapshot/R2 sidecar，学生功能只能降级或为空。 |
| P1 | LLM Provider | 提供受控 LLM 的部署方式或环境变量；明确模型、地址、限额与是否允许 WebResearch。 | `TEACHING_AGENT_MODE=enabled`、LLM 健康检查可用；Agent 对课程内样例问题能返回结构化结果或清晰降级。 | 普通 V1 问答仍可用；TeachingAgent API 保持 503/前端回退，不应伪造智能结果。 |
| P1 | Judge0 服务 | 保持 Ubuntu VM 中 Judge0 可达；在后端运行环境配置 `JUDGE0_ENABLED=true` 和 `JUDGE0_API_URL=http://127.0.0.1:2358`（或 Linux 内网地址）；逐课程开启 `coding_sandbox` 能力。 | 后端 `/sandbox/health` 为 enabled/available；学生从课程实验提交代码，得到 `ExperimentRun.run_id` 和受限结果。 | 代码实验应显示“暂不可用”；不能在主后端执行学生代码。 |
| P1 | 讯飞 TTS | 提供测试应用的讯飞凭据、接口版本、可用语音和调用限额。 | 受控讲稿生成真实音频，写入对象存储 `object_key`，失败可重试且不泄露密钥。 | 媒体流程只能使用 Fake TTS，不能产生真实音频。 |
| P2 | CPU 数字人 Worker | 先选定并部署一个独立数字人实现（不要把引擎塞入主后端）；提供 Worker 地址、资源限额和测试资产。 | 预处理教师头像/声音素材成功；能按讲稿与 TTS 音频生成可播放媒体。 | 预设、任务和时间轴模型可存在，但没有真实视频或本地合成服务。 |
| P2 | 对象存储 | 选择 MinIO/S3/阿里云 OSS 之一，提供测试桶、最小权限凭据、CORS 与生命周期规则。 | 真实 Provider 上传、签名下载、HEAD、迁移、哈希复核成功。 | 当前只能可靠使用 LocalStorage；不能假装 OSS 已启用。 |
| P2 | 泛雅 | 提供正式或测试 API、授权方式、字段映射和一个隔离测试课程。 | “发起同步 → 预览 → 教师确认”能真实拉取并写入规定范围。 | 当前页面可管理同步运行记录，但没有可证明的外部系统互通。 |

### A1. PaddleOCR 当前实际阻塞

Docker Desktop 已可访问，但 `deploy/paddleocr/compose.yml` 当前没有运行容器。镜像构建曾停在基础镜像下载阶段；本机现在仅确认存在 `python:3.11-slim` 基础镜像，并没有可运行的 PaddleOCR 服务镜像。

先完成：

```powershell
docker compose -f deploy/paddleocr/compose.yml up -d --build
Invoke-RestMethod http://127.0.0.1:8090/health
```

然后只用一份经授权的 PDF 和图片做人工解析验收。不要先批量导入历史材料。

### A2. LLM 与 Agent 的启用边界

启用 LLM 不等于允许它直接改学生掌握度。必须保持：

```text
LLM/Agent → 候选教学动作、解释、图谱/题目建议
                 ↓ 教师确认或受限工具校验
正式 LearningEvidence / 认知状态
```

Agent 日志与会话摘要仅是教学 Agent 上下文/审计记录；它们不应自动产生 `LearningEvidence`、`observed_performance_score` 或 `MasteryState`。

---

## B. 可由 Codex/开发直接完成的接线任务

以下工作不要求你先购买服务或提供密钥；可在本地 Demo 中逐项实现、用 Fake/Mock 验证，并在外部依赖就绪后复验。

| 顺序 | 要打通的链路 | 具体修改 | 完成验收 |
|---|---|---|---|
| B1 | **统一解析 → 课程草稿资产（规则基线已实现）** | 解析完成后，基于 `DocumentBlock/Evidence` 生成 `CourseOutline`、`TeachingScript`、`GraphNodeReview` 候选和 `PatchProposal`；教师可编辑、接受/拒绝、发布。LLM 优化仍是后续策略版本。 | 上传一份 PPTX 后，不手填对象路径即可得到可审核的结构、讲稿、图谱候选和带 Evidence 引用的提案。 |
| B2 | **PPT 页码—知识点正式映射** | 新建映射任务，输入已发布 Outline 与 PPT 文档块，输出页码、知识点、Evidence、置信度和版本；支持教师调整。 | “教学 PPT 映射”页不再显示 pending；学生跳转、引用、动画和返回锚点能使用同一映射。 |
| B3 | **Evidence / Citation 正式门面** | 将已解析、已发布的 Evidence 通过正式学生读取 API 提供；保留文档版本、stale、课程权限和定位失败语义。 | 学生能点开 PPT/PDF 页和文本片段；无证据时明确不可用，不出现 Shadow 503。 |
| B4 | **R2 与图谱的课程级接入** | 在材料发布后构建课程 sidecar/R2 索引；R2 不可用时由普通 V1 问答接管，并给出“图谱解析暂不可用”的提示。 | 同一课程的 R2 命中、无命中、解析失败三种路径均不会阻断聊天。 |
| B5 | **TeachingAgent / CodingEduAgent 动作串联** | 用稳定 session、课程能力、学生状态、图谱、题库和 `ExperimentRun.run_id` 接线；把受限 CodingDiagnosis 返回给 EduAgent。 | 学生代码运行后，Agent 只读已验证诊断并给出下一步练习/动画/补学动作；不泄露源码、Judge0 token，不直接改认知分。 |
| B6 | **可视化计划闭环** | 教师/Agent 只能生成白名单 `VisualizationPlan` JSON；审核、发布、播放，并从学习页携带返回锚点。 | 一个二分/排序示例能从学习问题打开、播放、返回原知识点，且无任意 JS/HTML 执行。 |
| B7 | **题库真实闭环** | 实现指定 Excel 的本地导入、unassigned 状态、教师题源映射、发布、六维推荐、答题证据。 | 未归属/未发布题不能被学生看到；推荐含策略版本、原因和证据。 |
| B8 | **前端已实现能力接通与清理** | 将加入申请、课程分组、泛雅同步的真实 API 加入前端；删除“planned”遗留文案；补课程分组导航。 | 用户不再看到“未实现”，而实际后端已可用的功能。 |
| B9 | **媒体与数字人 Provider 适配层** | 保持 `TTSProvider`、`DigitalHumanProvider`、`ObjectStorageProvider` 可替换；接上真实 Provider 后不改业务表/页面契约。 | Fake、讯飞、不同数字人 Worker 可按配置切换；失败明确降级。 |
| B10 | **持久任务运行器** | 将 `asyncio.create_task` 的本地 Worker 替换/补充为可恢复队列 Worker；任务状态、取消、重试保留。 | 后端重启后，任务不会悄然永远卡在 running；当前 Demo 可后置，但上线前必须完成。 |
| B11 | **真实 OSS Provider** | 完成 S3/MinIO/OSS Provider；把本地迁移账本接到真实上传、哈希校验、断点续传、软删除和 GC。 | `object_key` 不变即可从 LocalStorage 迁到 OSS 并正常回读。 |

---

## C. 必须联合验收的最小闭环

建议不要同时启用所有外部服务。按下列顺序验收，每通过一条才进入下一条：

```text
1. PaddleOCR + LibreOffice
   → 上传新 PPTX/PDF
   → 解析任务、DocumentBlock、Evidence 候选

2. CourseOutline + TeachingScript + PPT Mapping
   → 教师审核/发布
   → GraphSnapshot、课程资料 Markdown

3. 学生学习闭环
   → 普通问答 + 原文引用 + 图谱浏览 + 题库练习
   → Quiz 评分型证据

4. Judge0 + CodingEduAgent + JSAV
   → 代码运行
   → 受限诊断
   → 补学/动画/返回锚点

5. LLM / R2 / WebResearch
   → 课程证据优先
   → 无证据或外部故障时可解释降级

6. 讯飞 TTS + 数字人 + 对象存储
   → 教师资产预处理
   → 媒体生成、时间轴、学生播放
```

## D. 当前不应误判为“已上线”的能力

- Evidence V2、Document V2、Retrieval Demo 仍受 Shadow/feature flag 控制；
- `TEACHING_AGENT_MODE`、`R2_STUDENT_ANSWER_ENABLED`、`JUDGE0_ENABLED` 的代码默认值均为关闭；实际 `.env` 可以覆盖，但必须逐服务验收；
- TTS 和数字人默认 Provider 为 `fake`；
- 真实 S3/OSS Provider 尚未实现；
- 旧课程不会自动获得新解析、Evidence、图谱和 R2 数据，正确路径是重新上传；
- 课程分组和加入申请已有后端，但部分前端仍保留旧的 planned 描述，属于接线/文案债务，不是重新设计需求。

## E. 下一轮建议分工

**你先完成：** A1（OCR）、A3（Judge0 后端配置与课程能力）、A4（选择/提供 LLM）；如果暂不做媒体，则 A5–A8 可以后置。
**开发侧并行完成：** B1–B4 与 B8；它们能让课程建设、引用、图谱与学习页先形成可体验主线。
**待上述主线稳定后：** B5–B7；最后才是 B9–B11 的媒体、可恢复 Worker 与 OSS。
