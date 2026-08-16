# TeachingAgent 运行边界与课程解析降级

## 生效语义

- Agent 的课程权限仍由 Course Access v1 在请求入口校验。
- R2 课程侧车、Evidence、GraphSnapshot 是**课程/文档版本级**产物；一次解析可供该课程的多个学生使用。
- KG-MEST Shadow 报告是可选的学生级增强输入，不再是 Agent 可用性的前置条件。
- 没有正式认知状态时，Agent 只获得 `unknown` 读模型；不会自行补写认知结论。

## 旧课件与解析失败

未建立或暂时失效的课程侧车不会返回“学生/课程未配置”503。Agent 返回
`fallback_required / COURSE_KNOWLEDGE_GRAPH_PENDING`；前端随后调用既有 V1
`/chat/ask` 并显示：

> 课程知识图谱正在解析或暂不可用，本次已使用普通课程问答。

这不是授权绕过：课程访问校验仍先执行。后续可按课程和文档版本批量生成
Evidence/图谱，但不需要为每名学生重复执行 KG-MEST。

## 最小化记录与连续性

`AgentLearningEvent`、`AgentTraceRecord` 和 `AgentConversationSession` 只保存：

- 学生、课程、会话、trace 标识；
- 教学动作、意图、节点名、错误/告警码、证据 ID；
- 有界结构化会话状态（当前概念、上一意图/动作、告警）。

它们不保存原始提问、完整回答、完整 Prompt、完整模型 trace 或 Evidence 文本。
前端为同一学生/课程复用 session ID；服务器端摘要 30 分钟无活动后失效。

## 认知边界

上述 Agent 审计和会话记录**不是**正式 `LearningEvent` 或评分型
`LearningEvidence`，不会写入 `observed_performance_score`、`MasteryState` 或
任何正式认知结论。只有独立契约下的 Quiz/Judge0 评分等来源才可产生评分证据。

## 学习调整与回顾续接（2026-08-13 本地 P0）

TeachingAgent 可在一次已验证的回答后提供可选的学习调整提案，但不拥有播放器控制权。三种坐标严格分离：

- `QuestionObservation`：学生发送问题时的 item-local 位置，仅供本轮理解上下文；
- `ReviewTarget`：服务端只由 active `CourseRelease`、active `MediaRelease`、`MediaReleaseItem` 与 frozen `MediaReleaseCue` 计算的回顾目的地；
- `ReturnAnchor`：学生点击开始回顾瞬间的位置，用于之后主动返回。

每个坐标必须包含 `media_release_id`、`media_release_item_id`、`outline_node_id`、`local_time_ms` 与 `page`。可选 `global_time_ms` 仅为同一不可变 `audio-playlist/v1` 的兼容/展示时钟，绝不单独作为定位输入。草稿、可编辑 PPT 映射、最新材料和浏览器提交的回顾目的地均不能作为回顾目标兜底来源。

`LearningAdjustmentRecord` 的生命周期只有 `proposed → applied → returned`。其中 `applied` 的语义是“学习者已接受/授权回顾”，不是“浏览器已切换媒体或 seek 成功”；浏览器必须先完成本地媒体恢复，才可请求 `returned`。P0 不做 AI 自动判定“已复习”、Cue 结束自动返回或自动写入完成/掌握证据。无有效冻结目标或依赖异常时，普通问答继续可用且不显示空回顾卡片。

**回顾提案的触发条件（2026-08-16 收紧）**：只有 `prerequisite_review`（回退学习前置知识点）教学动作才产出回顾提案。`diagnostic_question`（先诊断提问，非回顾）、`misconception_repair` / `hint_scaffolding`（目标是当前知识点而非前置知识点）以及普通回答均不再触发“建议回顾第 X 页”提示框；此前诊断动作在数据稀疏时几乎每轮都弹框，属于误报。配套修复：问答链路中的 `RecommendationPort` 会把图节点 `node_key`（如 `kn_xxx`）解析为课程内数字节点 id 再生成推荐，使 `_find_confirmed_weak_prerequisites` 在节点作用域内生效，`prereq_review` 推荐与 `prerequisite_review` 教学动作可在提问后随认知刷新稳定复现（此前端口以 `node_id=None` 生成课程级推荐，薄弱前置检测恒为空，链路易饿死）。

`/api/v1/compat/progress/adjust` 不是独立理解度算法。它只能凭 `qaRecordId` 查到同一学习者、同一课程、仍有效的调整提案及 Conversation Domain 中同一 trace 的助手回答；任一关联缺失都返回 `503 LEARNING_ADJUSTMENT_CONTEXT_UNAVAILABLE`。外部 `understandingLevel` 不会成为掌握度、推荐或虚构补充内容的来源。

自动化验证覆盖 release/item/Cue 校验、跨学习者隔离、点击时 ReturnAnchor、幂等 transition、无证据/无媒体降级和兼容回合关联。跨媒体项回顾、浏览器 `canplay/seeked` 失败、主动返回和刷新恢复仍需非生产浏览器人工验收；ASR/语音打断不在本 P0 范围，保持 `ASR_UNAVAILABLE`。

## 迁移与回滚

`agent-log-minimization-v1` 先做 SQLite 预检，再将历史原始日志替换为最小化
红删标记，并记录幂等批次。回滚函数仅删除迁移账本；出于隐私原则，已清除的
原始内容不可恢复。
# 统一学习数据适配契约（2026-08-07）

学生学习页当前已通过 facade 写入 `LearningEvent`，并从 `StudentLearningProjection` 恢复
`release_id + outline_node_id` 的学习状态和最近锚点。TeachingAgent 仍不直接读取这些表；
`StudentStateTool`、`CognitionTool`、`LearningEventTool` 以及 `LearningContextPort` 等适配
接口继续标记为 `planned/unimplemented`。没有正式评分证据时只能返回 `unknown`，没有图谱映射
时返回 `not_available`，学习链路不可因认知/推荐刷新失败而阻断。

TeachingAgent 不直接访问学习表。未来通过 planned/unimplemented 的
`LearningContextPort`、`LearningProjectionPort`、`LearningEvidenceContextPort`
读取当前 `release_id + outline_node_id` 的学习摘要；`StudentStateTool` 只返回
exposure、cognition、recommendation 三段最小字段，`LearningEventTool` 只记录经过
治理的教学动作和幂等键。当前实现仍由学习门面 API 负责接线，不能把这些 Port/Tool
描述为已完成能力。

### Planned Port/Tool 字段契约（未实现）

以下接口只冻结请求/返回形状，当前不能被前端或 Agent 直接调用。身份由服务端注入，
不信任模型输出或浏览器传入的学生身份。

| 接口 | 请求字段 | 最小返回字段 | 权限与失败语义 |
|---|---|---|---|
| `LearningContextPort` | `course_id`, `student_id`, `release_id?`, `outline_node_id?` | `release_id`, `items[].outline_node_id`, `learning`, `cognition`, `recommendation`, `recent_anchor` | 本人需 `course.learn + analytics_eligible`；`unknown/not_available/degraded` 原样保留 |
| `LearningProjectionPort` | `course_id`, `student_id`, `release_id`, `outline_node_id` | `exposure_status`, `completion_ratio`, `completion_reason`, `current_timestamp`, `current_page`, `last_accessed_at` | 跨课程/release/node `NODE_NOT_IN_RELEASE`，只读本人或 `analytics.view_member` |
| `LearningEvidenceContextPort` | `evidence_id`, `course_id`, `source_release_id?`, `outline_node_id?`, `event_id?` | `knowledge_node_key`, `source_release_id`, `outline_node_id`, `event_id`, `status` | 仅正式评分证据；来源不完整 `SOURCE_RELEASE_AND_OUTLINE_NODE_REQUIRED`，无法唯一映射为 `unknown` |
| `CognitionPort` | `course_id`, `student_id`, `release_id`, `outline_node_id`, `knowledge_node_key?` | `mastery_level`, `mastery_score`, `evidence_confidence`, `sample_size`, `reason_codes`, `computed_at` | 无正式证据 `unknown/insufficient_evidence`；服务失败 `degraded` |
| `RecommendationPort` | 上述身份 + `exposure_status`, `completion_ratio`, `mastery_level`, `evidence_confidence` | `status`, `recommendation_id?`, `type?`, `title?`, `reason_codes` | 低置信度只能 `pending`；无图谱 `not_available`；依赖失败 `degraded` |
| `LearningEventPort`（统一学习事实） | `course_id`, `student_id`, `release_id`, `outline_node_id`, `event_type`, `idempotency_key`, `occurred_at`, `payload`, `source` | `event_id`, `projection_version`, `exposure_status` | 重复键返回原事件；冲突 `IDEMPOTENCY_KEY_CONFLICT`；权限/release 校验 fail-closed |
| `StudentStateTool` | `course_id`, `student_id`, `release_id`, `outline_node_id?` | `learning`, `cognition`, `recommendation`, `recent_anchor` | 只返回摘要，不返回聊天正文、完整答案或 LLM trace |
| `CognitionTool` | `course_id`, `student_id`, `release_id`, `outline_node_id`, `knowledge_node_key?` | 同 `CognitionPort` | 只读认知投影；失败 `COGNITION_UNAVAILABLE` |
| `LearningEventTool` | 治理后的教学动作、事件字段和幂等键 | `event_id`, `status`, `error_code?` | 仅记录允许的教学动作；Prep Agent 不拥有此工具 |

`unknown`=证据不足，`pending`=异步刷新未完成，`degraded`=依赖不可用，
`not_available`=没有合法图谱映射；四者不能互换，也不能由前端自行推导最终状态。
