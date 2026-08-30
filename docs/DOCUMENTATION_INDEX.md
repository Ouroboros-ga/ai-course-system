# 文档导航与状态

> 2026-08-20 新增：**挑战杯 XH-202620 改造启动**（面向一流学科建设的学科垂类大模型与创新应用开发，
> 发榜单位科大讯飞）。差距分析与产品定位（计算机学科版，含 9/5 材料截止路线图与决策清单）见
> [phase1/2026-08-20_XH202620差距分析与产品定位.md](phase1/2026-08-20_XH202620差距分析与产品定位.md)；
> 基线分支 `feature/xh202620`（自 dev-liu @9c52bd1 切出）。历史《赛题差距分析与重构建议.md》
> 已于 2026-08-20 删除，禁止引用其"完全重构"结论。
>
> 2026-08-20 更新（XH-202620 R1）：① 讯飞星火 LLM Provider 接入——`LLM_PROVIDER=spark`，
> OpenAI 兼容 `spark-api-open.xf-yun.com/v1`，fail-closed；单测 `tests/test_llm_spark_provider.py`
> 6 passed。② CS 学科知识库首批填充——`knowledge_data/`（11 数据结构 + 13 算法节点 + 21 关系），
> `validate.py` 校验通过，未接线。③ 典型问题测试案例集——[phase1/XH202620_典型问题测试案例集.md](phase1/XH202620_典型问题测试案例集.md)
> 6 用例（标准答案 + 权威来源 + 评测方法，实际输出 R2 回填）。

> 2026-08-20 更新（XH-202620 R2 部分完成）：① 学科知识库接线为只读检索服务
> `GET/POST /api/v1/discipline-knowledge/*`（检索含权威来源/节点+邻居/概览/重载），
> `tests/test_discipline_knowledge.py` 13 passed；② LoRA/SFT 微调管线可复现交付
> （`backend/finetune/`：指令集生成 ✅ 46+5 条、评测基准 `eval_baseline.json` 6 用例 ✅、
> 批量评测 `evaluate.py` fail-closed ✅、训练脚本 `train_lora.py` 需 GPU **未执行**）。

> 2026-08-20 更新（XH-202620 R3 部分完成）：① 参赛材料 01–07 骨架建立于根目录 `competition/`
> （伦理声明已起草、作品方案全文 + PPT 大纲、代码/模型清单、效果验证报告模板、测试报告说明、
> 报名检查清单）。② 助研"学术写作辅助"（writing_assist）已实现：工具注册 + 意图路由 +
> 结构化 LLM 草稿生成（AI 生成标识）+ LLM 不可用 fail-closed，`tests/test_research_writing_assist.py`
> 7 passed。9/5 前需完成：Demo 部署、真实用户试用回填、材料定稿打包。

> 2026-08-20 更新（XH-202620 R4）：学情诊断报告外化已实现——`GET /api/v1/cognitive/course/{id}/diagnosis`
> （教师端，规则聚合薄弱知识点 + 建议动作，只读不调 LLM），`tests/test_course_diagnosis.py` 6 passed。

> 2026-08-20 更新（XH-202620 R5）：① 助研趋势分析（trend_analysis）实现——论文元数据确定性聚合
> （关键词/年份/趋势方向/主题分类），`tests/test_research_trends.py` 8 passed；② 学科知识库扩充
> 操作系统课程（10 节点 + 12 关系），检索升级 CJK 二元组分词，校验 34 节点/32 关系，
> `tests/test_discipline_knowledge.py` 14 passed。

> 2026-08-20 更新（XH-202620 R6）：学科知识库扩充计算机网络（9 节点）+ 数据库系统（10 节点），
> 现 53 节点/49 关系（5 门课），校验通过；材料 04 新增 PPT 演讲脚本（10 页答辩词）；
> 微调数据集 98+10 条；知识库测试 15 passed。

> 2026-08-20 更新（XH-202620 R7）：学科知识库补齐软件工程（9 节点）+ 机器学习（10 节点），
> 六门核心课计划完成（72 节点/64 关系）；新增参赛打包预检 `competition/preflight.py` +
> 《打包检查清单.md》；微调数据集 128+14 条；知识库测试 16 passed。
> 2026-08-20 更新（XH-202620 R8）：前端学科知识检索页上线（`/app/discipline-knowledge`，
> 遵循 design.md 三层滚动/语义令牌/SfxButton），API 客户端 + 路由 + 一级导航接入；
> 前端契约测试 +2（75 passed）、单测 57 passed、Vite 构建通过；修复 2 个既有前端测试
> （Sprite2DRenderer 导出、playerWorkspaceAdapter 期望）。

> 2026-08-20 更新（XH-202620 R9）：典型问题测试案例集扩充至 10 用例（新增 SE 测试用例设计、
> ML 混淆矩阵 F1、算法 0-1 背包、OS 死锁判定），`eval_baseline.json` 同步并验证；微调指令集
> 132+14；材料 04 新增《PPT内容稿.md》。

> 2026-08-20 更新（XH-202620 R10）：学科知识库扩充编译原理（9 节点）+ 计算机组成原理（9 节点），
> 现 90 节点/82 关系/9 门课；微调指令集 164+18；知识库测试 17 passed；全量后端回归复跑
> 2749 passed / 6 failed / 22 skipped（6 失败为可选环境依赖缺失，非改造引入）。

> 2026-08-20 更新（XH-202620 R11）：冲刺就绪三件套——06《验收操作手册.md》、01《团队信息填写表.md》、
> 《命名与提交决策单.md》；preflight 复跑全 OK。剩余阻塞为外部输入（星火 Key/部署授权/真实用户/报名命名）。

> 2026-08-20 更新（XH-202620 R12）：基座决策落地 **DeepSeek**（`LLM_PROVIDER=deepseek`，`deepseek-chat`）——
> 新增 DeepSeek Provider（单测 6 passed）并设为默认；用团队 Key 完成 10 用例真实评测，自动判定
> **9/9 通过**（C3 待 Judge0 人工补验），结果 `backend/finetune/results_deepseek.json`；评测引擎新增
> `contains_grouped` 分组容差 + LaTeX 归一化（单测 6 passed）；案例集回填区与材料 06 已回填；
> 全材料同步"基座=DeepSeek（双轨可插拔）"。

> 2026-08-20 新增：**数据库无用字段审计**——[phase1/2026-08-20_数据库无用字段审计.md](phase1/2026-08-20_数据库无用字段审计.md)：
> 2592 个模型字段中识别 35 个零业务引用死字段（A 类 30 个建议部署窗口移除、B 类 5 个暂保留）；
> 本轮仅审计留档，未执行删列。

> 2026-08-20 新增：**47.99.97.154 部署升级方案**——[phase1/2026-08-20_部署升级方案_4799154.md](phase1/2026-08-20_部署升级方案_4799154.md)：
> 后端同步 + Alembic 迁移 + 前端构建发布 + nginx 校验 + 回滚方案；**待用户明确授权与 SSH 只读核实后执行**。

> 2026-08-13 更新：现行代码沙箱契约和统一学习契约已登记 CodingAgent 的受限源码读取、
> EduAgent 的无源码结构化摘要、服务端 `coding_execution` 证据、泛化投影 outbox，以及
> 题库 1.0 / 代码 1.5 的认知融合策略。

> 2026-08-13 更新：[实验室-代码沙箱可信评测契约](phase1/实验室代码沙箱可信评测契约.md) 记录正式实验的异步评测、ACM/ICPC 评分、可信实验室投影、脱敏 CodingAgent 反馈和 TeachingAgent 教师确认推荐。旧实验室写记录和学生终结成绩入口已下线；既有课程能力默认关闭，真实 Judge0 鉴权 smoke 与演示课程灰度仍需单独人工验收。

> 2026-08-11 新增：**代码库探索结果摘要与差距分析**（根目录《代码库探索结果摘要与差距分析.md》）——以 2026-08-11 真实代码为唯一依据的架构/模块/功能/差距探索基线；配套《文档更新清单.md》登记旧文档状态与更新原因。所有规划文档（挑战杯方案、产品二、可视化规划等）均已按此复核标注状态，勿再引用旧结论证明功能状态。

> 2026-08-09 更新：账户名称已收敛为唯一 `username`。管理员、个人中心、右上角和登录的实际契约说明见[平台管理员、Provider 与开放 API 兼容层](phase1/平台管理员Provider与开放API兼容层.md)；登录兼容数字用户 ID，旧 `real_name` 不再作为账户昵称。

> 2026-08-10 更新：首轮智能备课的材料证据整理保持有界 Map/Reduce，但面向高密度课件将 Map + Reduce 共享调用预算由 64 提升至 160；总材料、分块数与并发上限不变。Map/Reduce 的描述性列表归一化和 Map 嵌套 `stage` 移除已落地，证据 ID 与其他未知字段继续 fail-closed。资源上限、证据追溯与当前端到端验收状态登记在[统一课程建设与解析基线](phase1/统一课程建设与解析基线.md)和[功能现状审计表](phase1/功能现状审计表.md)。公开课程建设路由不变，无数据库迁移。

> 2026-08-11 更新：课程建设助教的单节点提案、批量一键操作、审核决定与提案列表增加展示安全的 `change_summary` / `display`。教师端状态固定为 `pending_review`、`applied`、`rejected`、`no_change`，不再显示内部 `target`；原始 `PatchProposalOperation.target` 保持持久化/API 兼容以支持审计和已有决定链路，无数据库迁移。实现与回归证据见[功能现状审计表](phase1/功能现状审计表.md)。

> 2026-08-11 更新：课程建设助教自由文本改由 Prep 结构化意图路由器按语义判断既有 action，移除关键词兜底；低置信度或路由不可用时澄清/返回 `PREP_AGENT_INTENT_UNAVAILABLE`，显式按钮 action 仍绕过分类器。两个一键入口在 batch API 前写入带 `quick_action`/`immediate_apply` 元数据的本地教师消息并展示授权徽标；无数据库迁移。实现与回归证据见[功能现状审计表](phase1/功能现状审计表.md)。

> 2026-08-11 更新：初始备课新增“讲稿覆盖问题”安全记录与 `partial_success` 语义；教师可在当前草稿讲稿页手工补齐，缺失/空讲稿升级为不可绕过的发布 BLOCKER。实现、迁移和验证边界见[课程生成核心逻辑与统一建设链](phase1/课程生成核心逻辑与统一建设链.md)及[功能现状审计表](phase1/功能现状审计表.md)。

> 2026-08-12 更新：当前“实验平台”仅表示代码沙箱。教师可在课程设置中用窄权限接口启用/关闭；关闭时师生二级导航不显示“实验任务”。汽车工程等非代码课程保持关闭；后续仿真类实验必须另建能力与任务链，不得冒充现有代码沙箱。实际权限和验证证据见[功能现状审计表](phase1/功能现状审计表.md)。

> 2026-08-12 更新：新课程默认开放知识图谱、证据、认知分析和安全策略配置；当前实验平台只接入代码沙箱，`experiment`/`coding_sandbox` 默认关闭并由教师按课程显式启用。课程设置中的智能体策略仅开放运行时已消费的 `enabled` 启动开关；逐工具治理仍由独立 `AgentToolPolicy` 链路负责，未在该设置页伪造未接线配置。平台 `ADMIN` 权限在所有课程持有成员列表不可见的“课程所有者”身份，facade 首页与建设列表对管理员返回全部课程（含草稿）。实现与验证证据见[功能现状审计表](phase1/功能现状审计表.md)与 [Course Access 权限解析](phase1/权限架构重构Goal.md)。

> 2026-08-13 更新：TeachingAgent 学习调整 P0 在本地实现了提问位置、冻结回顾目标和点击时返回锚点的三坐标语义；回顾只由学习者确认，`applied` 不表示浏览器已跳转，也不会形成掌握度证据。泛雅兼容 `/progress/adjust` 仅可关联到同一真实问答回合，否则返回显式 `503`。已通过定向自动化验证，跨媒体浏览器回顾与主动返回仍待非生产人工验收。现行边界见 [TeachingAgent 运行边界与课程解析降级](phase1/TeachingAgent运行边界与课程解析降级.md)，实施记录见 [TeachingAgent Hardness 计划](superpowers/plans/2026-08-12-teaching-agent-hardness-governance.md)。

> 2026-08-07 新增：[平台管理员、Provider 与开放 API 兼容层](phase1/平台管理员Provider与开放API兼容层.md)。该文档记录全局 user/admin 角色收敛、历史大写 TEACHER 账号升级管理员、后台配置、密钥脱敏、Provider 热刷新及可移除的泛雅·超星 AI 示例协议参考兼容包边界。

> 2026-08-12 更新：[ResearchAgent 整体架构、前端与上线基线](phase1/研究智能体整体架构与前端设计.md) 的真实部署数据库兼容基线确认为 PostgreSQL 16.14 + pgvector 0.7.4：仅只读验证 `0053` 五表、`vector` 和 `<=>`；Provider 对 vector SQL 不可用显式降级关键词，不改变服务器配置或服务。arXiv 仍是唯一论文源，多源/全文/写作/完整仓库复现保持 Research Preview。执行清单见 [ResearchAgent Harness Todo](phase1/ResearchAgent_Harness_TODO.md)。

> 更新：2026-08-08。本文是仓库文档的入口与分类规则，不以文档替代代码事实。

当前统一学习数据契约：[统一学习进度认知推荐统计契约](phase1/统一学习进度认知推荐统计契约.md)。该契约已覆盖新学习页和教师 `/analytics` 页的 available facade 接口；认知/推荐/Agent Port 与 Tool 扩展仍明确标记为 planned/unimplemented。

本轮清理已删除根目录 CodeMind/V3 方案、旧安装提示以及 `docs/archive/` 下的历史实现文档。它们不再作为当前设计或实现依据；需要追溯历史时使用 Git 历史。

## 先读什么

0. [服务器环境一致性与外部链路审计](phase1/2026-08-09_服务器环境一致性与外部链路审计.md)：2026-08-09 Ubuntu 实际环境、解析/RAG/Judge0 部署基线、Fake/未接入链路与回滚说明。
1. [AGENTS.md](../AGENTS.md)：当前授权、安全边界、Course Access v1 和测试规则。
2. [功能现状审计表](phase1/功能现状审计表.md)：当前代码审计结论与已知缺口。
2. [实验室-代码沙箱可信评测契约](phase1/实验室代码沙箱可信评测契约.md)：代码实验、可信记录和灰度开放边界。
3. [统一课程建设实施状态](phase1/统一课程建设实施状态.md)：统一上传、解析、草稿资产和 OCR 阻塞状态。
4. [PageDesign 待打通能力清单](phase1/PageDesign待打通能力_配置与开发分工清单.md)：外部服务配置与可由开发完成的接线任务。
3. [统一课程建设与解析基线](phase1/统一课程建设与解析基线.md)：本轮确认的统一上传、解析、RAG、课程树、讲稿和 PPT 映射目标。
4. [路由契约基线](phase1/路由契约基线.md) 与 `backend/app/main.py`：实际 API 注册事实。
5. [关键业务回归矩阵](phase1/关键业务回归矩阵.md)：改动后的最低验证范围。
6. [阶段 8：媒体与数字人当前方案](phase1/阶段8_媒体TTS数字人PPT_实施规划.md)：课程级批量媒体、PPT manifest、audio-playlist/v1、PixiJS 播放和当前阻塞的唯一现行基线。
7. [ResearchAgent 整体架构、前端与上线基线](phase1/研究智能体整体架构与前端设计.md)：Harness 图、工作区/记忆、论文检索、研究证据、写作和复现边界、API、页面与分阶段上线门。
8. [ResearchAgent Harness Todo](phase1/ResearchAgent_Harness_TODO.md)：2026-08-11 的可勾选执行与验证事实。

## 目录分类

| 位置 | 性质 | 使用方式 |
| --- | --- | --- |
| `docs/phase1/` | 当前 Demo 的运行说明、审计、契约与实施基线 | 可作为当前工作入口，但仍须核对代码。 |
| `docs/phase1/decisions/` | 已确认讨论的原文与架构决策 | 解释方向，不证明实现。 |
| `docs/research/`、`research/` | 离线研究、实验和评测材料 | 不得表述为真实教学效果或生产结论。 |
| `docs/refactor/` | 历次重构、Shadow、ADR、迁移与评审记录 | 用于追溯；其中的完成结论均需复核当前代码。 |
| `docs/frontend-design/` | 页面设计与前端契约设计 | 产品目标，不等于前端已经接入。 |
| `frontend/docs/` | 历史前端技术说明与设计稿 | 仅作参考；当前路由/API 以实际代码与契约测试为准。 |
| `backend/docs/` | 历史部署、Docling、NLP、TTS 说明 | 仅作参考；外部依赖以当前配置、锁文件和部署文件为准。 |
| `docs/refactor/` | 历史重构、Shadow、迁移和评审材料 | 不作为当前实现依据；保留的内容只用于追溯。 |
| 根目录产品/比赛/CodeMind 文档 | 历史产品构想、比赛材料或远期规划 | 不可反推当前能力。 |

### 媒体与数字人文档状态

- `phase1/阶段8_媒体TTS数字人PPT_实施规划.md`：2026-08-11 新增缓存优先的异步 `media.ppt_manifest`：复用映射页图、只补渲染缺页、轮询安全页数进度，且激活不再同步触发 LibreOffice。2026-08-10 已更新平台女性讲师 `platform-female-instructor-v1@1.0.0` 的预设、对象存储签发与旧汽车教师退休规则；课程 87 已在显式 Demo 模式以三知识点合成 fixture 创建新 MediaRelease/正式 CourseRelease，并在真实本地 Chrome 完成播放、跨节点、静态降级和 480p 短测。该 fixture 不覆盖历史 20 节点快照，Fake WAV/无头短测不证明真实 TTS 或长时设备性能。
- `phase1/阶段8_P5.1_音色与角色注册表.md`：平台注册的音色/角色版本冻结、签名 manifest 与前后端接入（2026-08-07 已实现）。
- `phase1/阶段8_P5.2_OSS与旧链隔离.md`：Local PUT、S3/OSS presigned POST、confirm 校验、本地签名 scope 与 `/video-gen` 兼容隔离（2026-08-07 已实现）。

- `phase1/阶段8_P5.3_一次受控豆包验收.md`：单次短文本豆包 TTS POC 的授权边界、脱敏诊断、`words`/`phonemes`/时长误差记录及本回合外部调用审批阻塞（2026-08-07）。

- `phase1/阶段8_P5.0_Provider配置基线.md`：2026-08-07 新增；统一 `MEDIA_DEMO_MODE`、
  `fake-demo`/`doubao` 页面状态与正式 Provider fail-closed 规则。

- 课程 87 的浏览器功能回归已有 2026-08-10 记录；后续入口是有头目标设备连续 10 分钟性能验收，以及每次都需教师重新授权的受控真实 TTS POC。
- `phase1/阶段8_附加_教师数字人资产中心.md`：后续教师授权资产扩展；当前不是首版发布前置。
- `phase1/阶段8_附加_DH_live浏览器实时渲染PoC验证报告.md`：DH_live 浏览器本地实时渲染与素材预处理的独立 PoC 实测记录（2026-08-06）；不改变主链，作为 M4 引擎接入评估依据。
- `backend/docs/数字人合成api.md`、`backend/docs/video_create.md`、`docs/refactor/R1D-DuixAvatar*`、`docs/refactor/R2B数字人与PPT任务迁移报告.md`：已废弃/仅历史追溯，不得作为当前数字人路线或完成度依据。

## 已删除的过期活动文档

以下文档在旧文档审查中已被明确列为落后，且本次已删除：

- `docs/api接口文档.md`：接口前缀、鉴权和响应语义与当前路由不一致。
- `docs/PPTX上传处理流程.md`：描述旧同步 `/document/upload` 链，不能代表统一上传目标。
- `docs/产品一-功能文档.md`、`docs/产品一-泛雅AI互动智课平台.md`、`docs/产品一-现有功能与影子能力说明.md`：产品一历史功能规划，已被现行 README/phase1 审计取代（2026-08-20 删除）。
- `docs/产品二-CodeNexus计算机学科智能教学系统.md`：产品二远期规划，无实现消费者（2026-08-20 删除）。
- `docs/创新点建议与PPT呈现结构.md`、`docs/平台技术亮点与竞争优势说明.md`：旧宣传/呈现材料，结论需按代码复核（2026-08-20 删除）。
- `docs/文档状态审查清单.md`、`docs/CODING_AGENT.md`、`docs/README.md`：过时入口/说明（2026-08-20 删除）。
- `docs/赛题差距分析与重构建议.md`：2026-06-21 旧差距分析，结论已被后续开发推翻，顶部已标注废弃后删除（2026-08-20 删除）。

历史归档材料中的旧链接不再维护；它们只反映当时的文本快照。需要追溯时使用 Git 历史。

## 文档维护规则

- 新的现行文档写入 `docs/phase1/`，并在本索引登记。
- 已完成的执行记录、审计报告和决策原文保留，不覆盖历史结论。
- 被替代的活动文档先在此索引标注，再删除；需要追溯的提交使用 Git 历史，现行文档统一放在 `docs/phase1/`。
- API、模型、权限或任务语义变更时，至少同步更新功能现状审计表、路由契约/测试和本索引。
- 与开发者讨论后形成的方案或技术路线变化，必须同步 README、对应现行阶段文档和本索引；被替代文档必须标记“已废弃/仅历史追溯”，不能继续被实现或验收引用。

## 2026-08-11 数据库迁移基线

- [SQLite 到独立 PostgreSQL 的迁移与服务器切换](phase1/2026-08-11_SQLite到PostgreSQL迁移与服务器切换.md)：当前 PostgreSQL 兼容修复、可审计 SQLite 快照迁移、隔离预演、维护窗口切换、回滚边界和备份恢复入口。`0048` 对历史 `media_release_items → script_nodes` 失效引用采用数据原样迁移、源/目标按关系计数一致校验和 PostgreSQL `NOT VALID` 外键；`0049/0050` 保留误写入小写值所需的类型兼容标签，`0051/0052` 补齐 SQLAlchemy 枚举成员名并将三列历史数据归一化为大写。服务器实际部署文件为 `deploy/postgres/`；运行库已切换后不得直接回退到 SQLite 接收写入。
